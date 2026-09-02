from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

WORKFLOW_PATH = Path(__file__).parents[1] / ".github" / "workflows" / "deploy-zb.yml"
DEPLOY_SCRIPT_PATH = Path(__file__).parents[1] / "deploy" / "ci" / "deploy-zb"
DEPLOY_WRAPPER_PATH = Path(__file__).parents[1] / "deploy" / "ci" / "deploy-zb-wrapper"
SUDOERS_PATH = Path(__file__).parents[1] / "deploy" / "ci" / "gha-zb-deploy.sudoers"
BACKUP_UNIT_PATH = Path(__file__).parents[1] / "deploy" / "systemd" / "bot-zb-backup.service"
BACKUP_WRAPPER_PATH = Path(__file__).parents[1] / "deploy" / "ci" / "run-zb-backup"
PRODUCTION_BRANCH = "codex/vps-migration"
PRODUCTION_ENVIRONMENT = "zb-production"
PRODUCTION_PATH = "/opt/telegram_client_manager"
PRODUCTION_SERVICE = "bot-zb.service"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    if not WORKFLOW_PATH.is_file():
        pytest.fail(f"deployment workflow is missing: {WORKFLOW_PATH}")
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def deploy_ci_text() -> str:
    paths = (DEPLOY_SCRIPT_PATH, DEPLOY_WRAPPER_PATH, SUDOERS_PATH)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        pytest.fail(f"deployment CI file(s) missing: {', '.join(missing)}")
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


@pytest.fixture(scope="module")
def runner_wrapper_text() -> str:
    paths = (DEPLOY_WRAPPER_PATH, SUDOERS_PATH)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        pytest.fail(f"self-hosted runner file(s) missing: {', '.join(missing)}")
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


@pytest.fixture(scope="module")
def backup_unit_text() -> str:
    if not BACKUP_UNIT_PATH.is_file():
        pytest.fail(f"backup systemd unit is missing: {BACKUP_UNIT_PATH}")
    return BACKUP_UNIT_PATH.read_text(encoding="utf-8")


def test_workflow_is_manual_and_requires_explicit_production_confirmation(
    workflow_text: str,
) -> None:
    """A push must never deploy, and a manual run must state its intent."""
    assert re.search(r"^\s*workflow_dispatch:\s*$", workflow_text, re.MULTILINE)
    assert not re.search(r"^\s*push:\s*$", workflow_text, re.MULTILINE)
    assert not re.search(r"^\s*schedule:\s*$", workflow_text, re.MULTILINE)

    confirmation = re.search(
        r"(?ms)^\s{6}(?:confirm|confirmation):\s*$.*?(?=^\s{6}\w[\w-]*:\s*$|^\s{4}\w[\w-]*:\s*$|\Z)",
        workflow_text,
    )
    assert confirmation, "workflow_dispatch must define a confirmation input"
    confirmation_block = confirmation.group(0)
    assert re.search(r"^\s+required:\s*true\s*$", confirmation_block, re.MULTILINE)
    assert "DEPLOY_ZB" in workflow_text
    assert re.search(r"deploy|production|вкат|подтверд", confirmation_block, re.IGNORECASE)


def test_deploy_is_restricted_to_the_approved_branch_and_environment(
    workflow_text: str,
) -> None:
    assert PRODUCTION_BRANCH in workflow_text
    assert re.search(
        rf"github\.ref\s*==\s*['\"]refs/heads/{re.escape(PRODUCTION_BRANCH)}['\"]",
        workflow_text,
    ) or re.search(
        rf"github\.ref_name\s*==\s*['\"]{re.escape(PRODUCTION_BRANCH)}['\"]",
        workflow_text,
    )

    assert re.search(
        rf"(?m)^\s*name:\s*{re.escape(PRODUCTION_ENVIRONMENT)}\s*$",
        workflow_text,
    )


def test_checkout_is_pinned_to_the_full_dispatched_commit(workflow_text: str) -> None:
    checkout = re.search(
        r"(?ms)^[ \t]*-[ \t]+uses:[ \t]+actions/checkout@[^\n]+\n(?P<body>.*?)(?=^[ \t]*-[ \t]+name:|^[ \t]*-[ \t]+uses:|\Z)",
        workflow_text,
    )
    assert checkout, "workflow must check out the dispatched commit"
    checkout_block = checkout.group("body")
    assert re.search(r"^\s+ref:\s+\$\{\{\s*github\.sha\s*\}\}\s*$", checkout_block, re.MULTILINE)
    assert re.search(r"^\s+fetch-depth:\s+0\s*$", checkout_block, re.MULTILINE)
    assert re.search(r'git rev-parse HEAD\)?["\']?\s*=\s*["\']?\$GITHUB_SHA', workflow_text)

def test_production_concurrency_never_cancels_an_in_progress_deploy(
    workflow_text: str,
) -> None:
    concurrency = re.search(
        r"(?ms)^concurrency:\s*$.*?(?=^jobs:\s*$|\Z)",
        workflow_text,
    )
    assert concurrency, "production deploy must have a concurrency policy"
    block = concurrency.group(0)
    assert re.search(r"^\s+group:\s*[^\n]+zb[^\n]*deploy", block, re.IGNORECASE | re.MULTILINE)
    assert re.search(r"^\s+cancel-in-progress:\s*false\s*$", block, re.MULTILINE)


def test_workflow_runs_only_on_the_approved_self_hosted_runner(
    workflow_text: str,
) -> None:
    runs_on = re.search(r"(?ms)^\s*runs-on:\s*(?P<value>[^\n]+(?:\n\s+-\s+[^\n]+)*)", workflow_text)
    assert runs_on, "workflow must declare its runner labels"
    runs_on_block = runs_on.group("value")
    for label in ("self-hosted", "linux", "ARM64", PRODUCTION_ENVIRONMENT):
        assert re.search(rf"(?m)^\s*-\s*{re.escape(label)}\s*$", runs_on_block) or re.search(
            rf"\b{re.escape(label)}\b", runs_on_block,
        ), f"missing runner label: {label}"
    assert "ubuntu-latest" not in runs_on_block


def test_workflow_uses_only_local_wrapper_and_has_no_ssh_transport_or_key_material(
    workflow_text: str,
) -> None:
    forbidden_transport_or_key_patterns = (
        r"\bssh\b",
        r"\bscp\b",
        r"\bsftp\b",
        r"ssh-keyscan",
        r"DEPLOY_ZB_SSH",
        r"(?:authorized_keys|id_rsa|id_ed25519|known_hosts)",
        r"\bsecrets\.",
    )
    for pattern in forbidden_transport_or_key_patterns:
        assert not re.search(pattern, workflow_text, re.IGNORECASE), pattern

    assert re.search(
        r"(?m)^\s*sudo\s+-n\s+--\s+/usr/local/sbin/gha-zb-deploy-wrapper\s+"
        r"deploy\s+[\"']?\$GITHUB_SHA[\"']?\s+<\s+[\"']?\$bundle_file[\"']?\s*$",
        workflow_text,
    ), "workflow must feed the bundle to the fixed local runner wrapper via stdin"


def test_workflow_does_not_pass_a_raw_sha_as_the_bundle_ref(workflow_text: str) -> None:
    """Git bundle needs an advertised ref (for example detached ``HEAD``)."""
    bundle_create = re.search(r"(?m)^\s*git bundle create [^\n]+$", workflow_text)
    assert bundle_create, "workflow must create an exact Git bundle"
    command = bundle_create.group(0)
    assert "$GITHUB_SHA" not in command
    assert re.search(r"\bHEAD\b|bundle[_-]?ref", command, re.IGNORECASE)


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _shell_function_bodies(script: str) -> dict[str, str]:
    """Return simple, top-level shell function bodies from the deploy script.

    The deployment script keeps its checkout operations in small functions.
    Extracting those functions lets the contract tests distinguish a
    post-checkout invariant from the preflight status check in ``main``.
    """
    return {
        match.group("name"): match.group("body")
        for match in re.finditer(
            r"(?ms)^(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\(\)\s*\{(?P<body>.*?)^\}",
            script,
        )
    }


def _shell_function_definition(script: str, function_name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(function_name)}\(\)\s*\{{.*?^\}}",
        script,
    )
    assert match, f"deploy script function is missing: {function_name}"
    return match.group(0)


def _bash_command() -> list[str]:
    if Path(r"C:\Program Files\Git\bin\bash.exe").is_file():
        return [r"C:\Program Files\Git\bin\bash.exe"]
    if Path(r"C:\Program Files\Git\usr\bin\bash.exe").is_file():
        return [r"C:\Program Files\Git\usr\bin\bash.exe"]
    return [shutil.which("bash") or "bash"]


def _run_bash(harness: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _bash_command() + ["-c", harness],
        check=False,
        capture_output=True,
        text=True,
    )


def _function_has_post_checkout_revision_check(body: str) -> bool:
    """Check for HEAD equality and tracked worktree/index cleanliness."""
    return (
        re.search(r"\brun_git\s+rev-parse\s+HEAD\b", body) is not None
        and re.search(r"\b(?:test|\[\[)[^\n]*(?:=|==)[^\n]*\$\w*revision\b", body)
        is not None
        and (
            re.search(r"\brun_git\s+status\s+--porcelain\b", body) is not None
            or "verify_repository_status_clean" in body
        )
    )


def _has_branch_assertion(body: str) -> bool:
    return (
        re.search(r"\brun_git\s+symbolic-ref\s+--quiet\s+--short\s+HEAD\b", body)
        is not None
        and re.search(r"\b(?:test|\[\[)[^\n]*(?:=|==)[^\n]*DEPLOY_BRANCH\b", body)
        is not None
    )


def _function_has_revision_contract(
    functions: dict[str, str],
    function_name: str,
    seen: set[str] | None = None,
) -> bool:
    """Resolve a revision/clean verifier through nested helper calls."""
    seen = set() if seen is None else seen
    if function_name in seen:
        return False
    seen.add(function_name)

    body = functions[function_name]
    if _function_has_post_checkout_revision_check(body):
        return True

    for verifier_name in functions:
        if verifier_name in seen or verifier_name not in body:
            continue
        if not re.search(rf"\b{re.escape(verifier_name)}\b[^\n]*\$revision\b", body):
            continue
        if _function_has_revision_contract(functions, verifier_name, seen.copy()):
            return True
    return False


def _function_has_post_finalize_branch_check(
    functions: dict[str, str],
    function_name: str,
    seen: set[str] | None = None,
) -> bool:
    """Resolve branch assertion plus nested HEAD/status verification."""
    seen = set() if seen is None else seen
    if function_name in seen:
        return False
    seen.add(function_name)

    body = functions[function_name]
    if _has_branch_assertion(body) and _function_has_revision_contract(
        functions,
        function_name,
    ):
        return True

    for verifier_name in functions:
        if verifier_name in seen or verifier_name not in body:
            continue
        if not re.search(rf"\b{re.escape(verifier_name)}\b[^\n]*\$revision\b", body):
            continue
        if _function_has_post_finalize_branch_check(
            functions,
            verifier_name,
            seen.copy(),
        ):
            return True
    return False


def _function_or_called_verifier_has(
    functions: dict[str, str],
    function_name: str,
    predicate: Callable[[str], bool],
) -> bool:
    """Allow direct checks or one small, explicitly called verifier helper."""
    return _function_or_called_verifier_has_recursive(functions, function_name, predicate, set())


def _function_or_called_verifier_has_recursive(
    functions: dict[str, str],
    function_name: str,
    predicate: Callable[[str], bool],
    seen: set[str],
) -> bool:
    if function_name in seen:
        return False
    seen.add(function_name)

    body = functions[function_name]
    if predicate(body):
        return True

    for verifier_name, verifier_body in functions.items():
        if verifier_name in seen or verifier_name not in body:
            continue
        if predicate(verifier_body) and re.search(
            rf"\b{re.escape(verifier_name)}\b[^\n]*\$revision\b",
            body,
        ):
            return True
        if re.search(rf"\b{re.escape(verifier_name)}\b[^\n]*\$revision\b", body) and _function_or_called_verifier_has_recursive(
            functions,
            verifier_name,
            predicate,
            seen.copy(),
        ):
            return True
    return False


def _uses_deploy_user_boundary(functions: dict[str, str], body: str) -> bool:
    if re.search(r"(?:runuser|sudo)\b[^\n]*\$DEPLOY_USER", body):
        return True
    return any(
        verifier_name in body
        and re.search(r"(?:runuser|sudo)\b[^\n]*\$DEPLOY_USER", verifier_body)
        for verifier_name, verifier_body in functions.items()
    )


def _has_permission_check(
    functions: dict[str, str],
    body: str,
    permission: str,
) -> bool:
    if re.search(rf"(?:\btest\b|\[\[[^\n]*)[^\n]*{re.escape(permission)}", body):
        return True
    return any(
        verifier_name in body
        and re.search(
            rf"(?:\btest\b|\[\[[^\n]*)[^\n]*{re.escape(permission)}",
            verifier_body,
        )
        for verifier_name, verifier_body in functions.items()
    )


def test_detached_checkout_fails_closed_on_revision_or_tracked_tree_mismatch() -> None:
    """A successful Git checkout is not enough to start a production build."""
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    functions = _shell_function_bodies(script)

    assert "checkout_revision" in functions
    assert _function_or_called_verifier_has(
        functions,
        "checkout_revision",
        _function_has_post_checkout_revision_check,
    ), (
        "checkout_revision must verify exact HEAD and a clean tracked "
        "worktree/index after checkout"
    )


def test_finalized_branch_is_verified_before_success_is_reported() -> None:
    """The success message must be unreachable after an incomplete finalize."""
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    functions = _shell_function_bodies(script)

    assert "finalize_branch_revision" in functions
    assert _function_has_post_finalize_branch_check(
        functions,
        "finalize_branch_revision",
    ), (
        "finalize_branch_revision must verify branch, exact HEAD, and a clean "
        "tracked worktree/index before deploy-zb reports success"
    )

    success_message = re.search(
        r'''(?m)^printf ['"]deploy-zb: deployed %s successfully\\n['"] "\$EXPECTED_SHA"$''',
        script,
    )
    assert success_message, "deploy-zb must retain an explicit success message"
    finalize_invocation = re.search(
        r"(?m)^(?!\s*finalize_branch_revision\s*\(\))"
        r"(?=[^\n]*\bfinalize_branch_revision\b)[^\n]*$",
        script,
    )
    assert finalize_invocation, "deploy-zb must invoke finalization before success"
    assert finalize_invocation.start() < success_message.start()


def _checkout_harness(
    script: str,
    *,
    run_git_body: str,
    function_call: str,
) -> str:
    definitions = "\n\n".join(
        _shell_function_definition(script, function_name)
        for function_name in (
            "verify_repository_status_clean",
            "verify_revision_clean",
            "verify_branch_revision_clean",
            "checkout_revision",
            "finalize_branch_revision",
        )
    )
    return (
        "set -u\n"
        'DEPLOY_BRANCH="codex/vps-migration"\n'
        f"{definitions}\n\n"
        f"run_git() {{\n{run_git_body}\n}}\n\n"
        f"if {function_call}; then\n"
        "  printf 'RESULT=success\\n'\n"
        "else\n"
        "  printf 'RESULT=failure\\n'\n"
        "fi\n"
    )


@pytest.mark.parametrize(
    ("scenario", "run_git_body"),
    (
        (
            "checkout-command-failure",
            """
  if [[ "$1" == checkout ]]; then return 1; fi
  if [[ "$1" == rev-parse ]]; then printf 'old-sha\\n'; return 0; fi
  if [[ "$1" == status ]]; then return 0; fi
  return 0
""",
        ),
        (
            "sha-mismatch",
            """
  if [[ "$1" == checkout ]]; then return 0; fi
  if [[ "$1" == rev-parse ]]; then printf 'old-sha\\n'; return 0; fi
  if [[ "$1" == status ]]; then return 0; fi
  return 0
""",
        ),
        (
            "status-command-failure-with-empty-output",
            """
  if [[ "$1" == checkout ]]; then return 0; fi
  if [[ "$1" == rev-parse ]]; then printf 'requested-sha\\n'; return 0; fi
  if [[ "$1" == status ]]; then return 1; fi
  return 0
""",
        ),
    ),
)
def test_checkout_revision_rejects_masked_git_failures(
    scenario: str,
    run_git_body: str,
) -> None:
    """The real function must not turn a failed Git command into success."""
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    result = _run_bash(
        _checkout_harness(
            script,
            run_git_body=run_git_body,
            function_call='checkout_revision "requested-sha"',
        )
    )

    assert "RESULT=failure" in result.stdout, (
        f"{scenario} was masked by checkout_revision:\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_repository_status_preflight_rejects_status_command_failure() -> None:
    """A failed status command cannot be accepted as an empty worktree."""
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    function = _shell_function_definition(script, "verify_repository_status_clean")
    result = _run_bash(
        "set -u\n"
        f"{function}\n\n"
        "run_git() { return 1; }\n\n"
        'if verify_repository_status_clean all; then\n'
        "  printf 'RESULT=success\\n'\n"
        "else\n"
        "  printf 'RESULT=failure\\n'\n"
        "fi\n"
    )

    assert "RESULT=failure" in result.stdout, (
        "repository status failure was accepted as a clean preflight:\n"
        f"stdout={result.stdout!r}\\nstderr={result.stderr!r}"
    )


@pytest.mark.parametrize("failure_command", ("branch", "checkout", "symbolic-ref"))
def test_finalize_revision_rejects_masked_git_failures(failure_command: str) -> None:
    """Every branch, checkout, and branch-read failure must abort finalization."""
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    result = _run_bash(
        _checkout_harness(
            script,
            run_git_body=f"""
  if [[ "$1" == {failure_command} ]]; then return 1; fi
  if [[ "$1" == symbolic-ref ]]; then printf 'codex/vps-migration\\n'; return 0; fi
  if [[ "$1" == rev-parse ]]; then printf 'requested-sha\\n'; return 0; fi
  if [[ "$1" == status ]]; then return 0; fi
  return 0
""",
            function_call='finalize_branch_revision "requested-sha"',
        )
    )

    assert "RESULT=failure" in result.stdout, (
        f"{failure_command} failure was masked by finalize_branch_revision:\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def _tracked_directory_preflight_harness(
    script: str,
    *,
    run_git_body: str,
    boundary_body: str,
) -> str:
    preflight = _shell_function_definition(script, "verify_tracked_directories_writable")
    die = _shell_function_definition(script, "die")

    # Git Bash does not provide the production /usr/sbin/runuser path. Keep
    # the real function body and adapt only that privilege boundary so the
    # producer-failure behavior is deterministic on both Windows and POSIX.
    if "run_as_deploy_user" not in preflight:
        preflight = preflight.replace(
            '/usr/sbin/runuser -u "$DEPLOY_USER" -- /usr/bin/test -w "$directory"',
            'run_as_deploy_user /usr/bin/test -w "$directory"',
        )

    return (
        "set -u\n"
        'DEPLOY_USER="ubuntu"\n'
        'REPOSITORY_DIR="$PWD"\n'
        f"{die}\n\n{preflight}\n\n"
        f"run_as_deploy_user() {{\n{boundary_body}\n}}\n"
        f"run_git() {{\n{run_git_body}\n}}\n"
        "set +e\n"
        "verify_tracked_directories_writable\n"
        "status=$?\n"
        "printf 'STATUS=%s\\n' \"$status\"\n"
    )


def test_tracked_directory_preflight_rejects_ls_files_producer_failure() -> None:
    """A failed NUL-safe tracked-path producer cannot look like an empty tree."""
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    harness = _tracked_directory_preflight_harness(
        script,
        run_git_body="return 1",
        boundary_body='"$@"',
    )
    result = _run_bash(harness)

    assert result.returncode != 0 or "STATUS=0" not in result.stdout, (
        "ls-files producer failure was treated as an empty tracked tree:\n"
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_tracked_directory_preflight_accepts_a_fast_ls_files_producer() -> None:
    """A completed producer must not invalidate the file descriptor before reading."""
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    result = _run_bash(
        _tracked_directory_preflight_harness(
            script,
            run_git_body="""
  if [[ "$1" == ls-files ]]; then printf 'dir/file\\0'; return 0; fi
  return 0
""",
            boundary_body="return 0",
        )
    )

    assert result.returncode == 0 and "STATUS=0" in result.stdout, (
        "a successful fast ls-files producer did not complete the preflight:\n"
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_tracked_directory_preflight_requires_write_and_search_permissions() -> None:
    """A writable-but-unsearchable tracked parent must stop the deployment."""
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    result = _run_bash(
        _tracked_directory_preflight_harness(
            script,
            run_git_body="""
  if [[ "$1" == ls-files ]]; then printf 'dir/file\\0'; return 0; fi
  return 0
""",
            boundary_body="""
  for argument in "$@"; do
    if [[ "$argument" == -x ]]; then return 1; fi
  done
  return 0
""",
        )
    )

    assert result.returncode != 0 or "STATUS=0" not in result.stdout, (
        "preflight accepted a directory for which -w succeeded but -x failed:\n"
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_tracked_directory_preflight_preserves_newline_in_parent_path() -> None:
    """A newline in a tracked directory name must reach the permission check intact."""
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    result = _run_bash(
        _tracked_directory_preflight_harness(
            script,
            run_git_body="""
  if [[ "$1" == ls-files ]]; then printf 'dir\\n/file\\0'; return 0; fi
  return 0
""",
            boundary_body="""
  local expected_newline_directory
  expected_newline_directory="$REPOSITORY_DIR/dir"$'\\n'
  for argument in "$@"; do
    if [[ "$argument" == "$REPOSITORY_DIR" || "$argument" == "$expected_newline_directory" ]]; then
      return 0
    fi
  done
  return 1
""",
        )
    )

    assert result.returncode == 0 and "STATUS=0" in result.stdout, (
        "tracked parent path was not passed byte-for-byte to the permission boundary:\n"
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_deploy_checks_repository_directory_writability_before_receiving_bundle() -> None:
    """A root-owned worktree must fail before Git can leave a mixed checkout."""
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    functions = _shell_function_bodies(script)

    writable_preflights = {
        name: body
        for name, body in functions.items()
        if re.search(r"\brun_git\s+ls-files\s+-z\b", body)
        and re.search(r"\b(?:read\s+-r[^\n]*-d\s+(?:''|\\?0)|xargs[^\n]*-0|mapfile[^\n]*-d)", body)
        and re.search(r"\bdirname\b|%%/?\*|\$\{tracked_path%/\*\}", body)
        and _uses_deploy_user_boundary(functions, body)
        and _has_permission_check(functions, body, "-w")
        and _has_permission_check(functions, body, "-x")
        and re.search(r"\b(?:die|return\s+1|exit\s+1)\b", body)
    }
    assert writable_preflights, (
        "deploy-zb must derive parent directories from NUL-safe tracked paths "
        "and test writability as DEPLOY_USER, failing closed"
    )

    preflight_name = next(iter(writable_preflights))
    preflight_call = re.search(
        rf"(?m)^(?!\s*{re.escape(preflight_name)}\s*\(\))"
        rf"(?=[^\n]*\b{re.escape(preflight_name)}\b)[^\n]*$",
        script,
    )
    assert preflight_call, "the directory writability preflight must be invoked"

    branch_check = script.find("current_branch=")
    clean_check = script.find("verify_repository_status_clean all")
    bundle_install = script.find('install -d -m 0700 -o "$DEPLOY_USER"')
    bundle_creation = script.find('mktemp "$BUNDLE_DIR')
    bundle_unbundle = script.find("bundle unbundle")
    checkout_call = script.find('if ! checkout_revision "$EXPECTED_SHA"')

    assert -1 not in (
        branch_check,
        clean_check,
        bundle_install,
        bundle_creation,
        bundle_unbundle,
        checkout_call,
    )
    assert clean_check < preflight_call.start() < bundle_install
    assert preflight_call.start() < bundle_creation
    assert preflight_call.start() < bundle_unbundle
    assert preflight_call.start() < checkout_call


def _create_selected_commit_bundle(repository: Path, bundle_path: Path, commit_sha: str) -> None:
    """Model the workflow's detached-HEAD bundle strategy in isolation."""
    _git(repository, "checkout", "--detach", commit_sha)
    _git(repository, "bundle", "create", str(bundle_path), "HEAD")


def test_selected_commit_bundle_is_verifiable_single_ref_and_unbundlable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    restored = tmp_path / "restored"
    bundle = tmp_path / "selected.bundle"
    source.mkdir()
    restored.mkdir()

    _git(source, "init", "--quiet")
    _git(source, "config", "user.email", "test@example.invalid")
    _git(source, "config", "user.name", "Bundle Test")
    (source / "payload.txt").write_text("first\n", encoding="utf-8")
    _git(source, "add", "payload.txt")
    _git(source, "commit", "--quiet", "-m", "first")
    (source / "payload.txt").write_text("selected\n", encoding="utf-8")
    _git(source, "commit", "--quiet", "-am", "selected")
    selected_sha = _git(source, "rev-parse", "HEAD").strip()

    _create_selected_commit_bundle(source, bundle, selected_sha)

    heads = _git(source, "bundle", "list-heads", str(bundle)).splitlines()
    assert len(heads) == 1
    advertised_sha, advertised_ref = heads[0].split(maxsplit=1)
    assert advertised_sha == selected_sha
    assert advertised_ref == "HEAD"
    _git(source, "bundle", "verify", str(bundle))

    _git(restored, "init", "--quiet")
    _git(restored, "bundle", "unbundle", str(bundle))
    assert _git(restored, "cat-file", "-e", f"{selected_sha}^{{commit}}") == ""


def test_deploy_targets_fixed_service_and_repository_without_unsafe_cleanup(
    deploy_ci_text: str,
) -> None:
    assert PRODUCTION_PATH in deploy_ci_text
    assert PRODUCTION_SERVICE in deploy_ci_text

    unsafe_commands = (
        r"git\s+reset\s+--hard",
        r"git\s+clean(?:\s|$)",
        r"sudo\s+(?:bash|sh|\-i|\-s)\b",
        r"sudo\s+(?:rm|chmod\s+\-R|chown\s+\-R)\b",
    )
    for pattern in unsafe_commands:
        assert not re.search(pattern, deploy_ci_text, re.IGNORECASE), pattern

    assert re.search(
        r"gha-zb-runner\s+ALL=\(root\)\s+NOPASSWD:\s+/usr/local/sbin/gha-zb-deploy-wrapper",
        deploy_ci_text,
    )
    assert not re.search(r"NOPASSWD:\s+ALL\b", deploy_ci_text)


def test_self_hosted_runner_wrapper_accepts_only_one_sha_and_executes_fixed_deploy_script(
    runner_wrapper_text: str,
) -> None:
    assert "/usr/local/lib/zb-deploy/deploy-zb" in runner_wrapper_text
    assert re.search(r"\bEUID\s*!=\s*0", runner_wrapper_text)
    assert re.search(r"\(\(\s*\$#\s*==\s*2\s*\)\)", runner_wrapper_text)
    assert re.search(r"\[\[\s*\"?\$1\"?\s*==\s*['\"]deploy['\"]", runner_wrapper_text)
    assert re.search(r"\$2\"?\s*=~\s*\^\[0-9a-f\]\{40\}\$", runner_wrapper_text)
    assert re.search(r'exec\s+"\$DEPLOY_SCRIPT"\s+"\$2"', runner_wrapper_text)
    assert "SSH_ORIGINAL_COMMAND" not in runner_wrapper_text
    assert not re.search(r"\b(?:eval|bash\s+-c|sh\s+-c)\b", runner_wrapper_text)


def test_backup_and_deploy_share_a_lock_for_the_entire_backup_lifecycle(
    deploy_ci_text: str,
    backup_unit_text: str,
) -> None:
    """Backup must lock before stopping bot and release only after bot restart."""
    assert BACKUP_WRAPPER_PATH.is_file(), (
        "backup must use a dedicated lock-owning wrapper; an ExecStartPre stop "
        "cannot hold the deploy lock across the backup lifecycle"
    )
    backup_script = BACKUP_WRAPPER_PATH.read_text(encoding="utf-8")

    deploy_lock = re.search(r"/run/lock/[A-Za-z0-9_.-]+", deploy_ci_text)
    backup_lock = re.search(
        r"\bMAINTENANCE_LOCK\s*=\s*['\"]?(/run/lock/[A-Za-z0-9_.-]+)",
        backup_script,
    )
    assert deploy_lock and backup_lock
    assert deploy_lock.group(0) == backup_lock.group(1)

    assert re.search(r"ExecStart=.*run-zb-backup", backup_unit_text)
    assert not re.search(r"ExecStartPre=.*docker compose.*stop\s+bot-zb", backup_unit_text)

    lock_position = re.search(
        r"(?:flock|exec\s+\d+>).*?(?:MAINTENANCE_LOCK|/run/lock/)",
        backup_script,
    )
    stop_position = re.search(r"docker compose.*\bstop\s+(?:bot-zb|\$COMPOSE_SERVICE)\b", backup_script)
    backup_position = re.search(r"python3[\s\S]{0,100}-m[\s\S]{0,100}deploy\.backup_to_oci", backup_script)
    restart_position = re.search(r"docker compose.*\bstart\s+(?:bot-zb|\$COMPOSE_SERVICE)\b", backup_script)
    assert lock_position and stop_position and backup_position and restart_position
    assert lock_position.start() <= stop_position.start() < backup_position.start() < restart_position.start()

    unlocks = list(re.finditer(r"(?:flock\s+-u|exec\s+\d+>&-)", backup_script))
    assert not unlocks or all(unlock.start() > restart_position.start() for unlock in unlocks)


def test_workflow_does_not_handle_production_secret_or_data_artifacts(
    workflow_text: str,
) -> None:
    """The local runner receives code only, never live data or credentials."""
    forbidden_artifact_patterns = (
        r"(?:^|[\s/'\"])(?:\.env|[^\s/'\"]+\.env)(?:$|[\s/'\"])",
        r"[^\s/'\"]+\.(?:db|sqlite|sqlite3)(?:$|[\s/'\"])",
        r"(?:authorized_keys|id_rsa|id_ed25519)(?:$|[\s/'\"])",
        r"/srv/medical-bot/data(?:/|$)",
    )
    for pattern in forbidden_artifact_patterns:
        assert not re.search(pattern, workflow_text, re.IGNORECASE), pattern

    assert not re.search(r"\bsecrets\.", workflow_text, re.IGNORECASE)
