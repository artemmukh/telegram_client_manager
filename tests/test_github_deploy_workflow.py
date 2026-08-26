from __future__ import annotations

import re
import subprocess
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


def test_ssh_uses_pinned_hosts_and_never_discovers_hosts_at_runtime(
    workflow_text: str,
) -> None:
    assert re.search(r"StrictHostKeyChecking=(?:yes|true)", workflow_text)
    assert re.search(r"UserKnownHostsFile=", workflow_text)
    assert "ssh-keyscan" not in workflow_text


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
        r"ubuntu\s+ALL=\(root\)\s+NOPASSWD:\s+/usr/local/sbin/gha-zb-deploy-wrapper",
        deploy_ci_text,
    )
    assert not re.search(r"NOPASSWD:\s+ALL\b", deploy_ci_text)


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
    """The workflow may use GitHub secret references, never copy live data/configs."""
    forbidden_artifact_patterns = (
        r"(?:^|[\s/'\"])(?:\.env|[^\s/'\"]+\.env)(?:$|[\s/'\"])",
        r"[^\s/'\"]+\.(?:db|sqlite|sqlite3)(?:$|[\s/'\"])",
        r"(?:authorized_keys|id_rsa|id_ed25519)(?:$|[\s/'\"])",
        r"/srv/medical-bot/data(?:/|$)",
    )
    for pattern in forbidden_artifact_patterns:
        assert not re.search(pattern, workflow_text, re.IGNORECASE), pattern
