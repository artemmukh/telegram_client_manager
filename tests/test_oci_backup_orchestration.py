from __future__ import annotations

import json
import subprocess
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest
from test_vps_snapshot_export import make_request

from deploy import backup_to_oci
from deploy.oci_backup_orchestration import (
    OciBackupError,
    SubprocessOciUploader,
    UploadReport,
    create_verified_bundle,
    make_backup_object_name,
)
from deploy.snapshot_contract import sha256 as snapshot_sha256
from deploy.snapshot_export import export_snapshot

VALID_SHA256 = "0123456789abcdef" * 4


@dataclass
class FakeSubprocessRunner:
    result: object
    calls: list[tuple[list[str], dict[str, object]]] = field(default_factory=list)

    def __call__(self, args: list[str], **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _create_valid_data_root(data_root: Path) -> None:
    data_root.mkdir()
    (data_root / "zb.db").write_bytes(b"main")
    (data_root / "reminders.db").write_bytes(b"reminders")
    (data_root / "history_of_illness" / "generated").mkdir(parents=True)


@pytest.mark.asyncio
async def test_subprocess_oci_uploader_uses_exact_instance_principal_cli_contract(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "snapshot.tar"
    payload.write_bytes(b"synthetic outer snapshot")
    runner = FakeSubprocessRunner(
        subprocess.CompletedProcess(
            args=["oci"],
            returncode=0,
            stdout=json.dumps({"etag": "etag-123"}),
            stderr="",
        )
    )
    uploader = SubprocessOciUploader(runner=runner, timeout_seconds=23)

    result = await uploader.upload(
        path=payload,
        namespace="namespace",
        region="me-dubai-1",
        bucket="medical-bot-backups",
        object_name="backups/zb/2026/08/24/id/snapshot.tar",
        sha256=snapshot_sha256(payload),
    )

    assert result.etag == "etag-123"
    assert runner.calls == [
        (
            [
                "oci",
                "--auth",
                "instance_principal",
                "--region",
                "me-dubai-1",
                "os",
                "object",
                "put",
                "--namespace",
                "namespace",
                "--bucket-name",
                "medical-bot-backups",
                "--name",
                "backups/zb/2026/08/24/id/snapshot.tar",
                "--file",
                str(payload),
                "--no-overwrite",
                "--verify-checksum",
                "--opc-checksum-algorithm",
                "SHA256",
                "--output",
                "json",
            ],
            {
                "shell": False,
                "check": False,
                "capture_output": True,
                "text": True,
                "timeout": 23,
            },
        )
    ]


@pytest.mark.parametrize(
    "runner_result",
    [
        subprocess.CompletedProcess(
            args=["oci"],
            returncode=7,
            stdout="{}",
            stderr="token=super-secret-value remote failure",
        ),
        subprocess.TimeoutExpired(cmd=["oci"], timeout=23),
        subprocess.CompletedProcess(
            args=["oci"],
            returncode=0,
            stdout="not-json",
            stderr="malformed response",
        ),
        subprocess.CompletedProcess(
            args=["oci"],
            returncode=0,
            stdout=json.dumps({"data": {"etag": "nested-etag"}}),
            stderr="missing etag",
        ),
    ],
    ids=["nonzero", "timeout", "malformed-json", "missing-etag"],
)
@pytest.mark.asyncio
async def test_subprocess_oci_uploader_raises_sanitized_bounded_typed_errors(
    tmp_path: Path,
    runner_result: object,
) -> None:
    payload = tmp_path / "snapshot.tar"
    payload.write_bytes(b"synthetic outer snapshot")
    runner = FakeSubprocessRunner(runner_result)
    uploader = SubprocessOciUploader(runner=runner, timeout_seconds=23)

    with pytest.raises(OciBackupError) as error_info:
        await uploader.upload(
            path=payload,
            namespace="namespace",
            region="me-dubai-1",
            bucket="medical-bot-backups",
            object_name="backups/zb/2026/08/24/id/snapshot.tar",
            sha256=VALID_SHA256,
        )

    message = str(error_info.value)
    assert "super-secret-value" not in message
    assert len(message) <= 512


@pytest.mark.asyncio
async def test_subprocess_oci_uploader_rejects_invalid_digest_before_runner_call(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "snapshot.tar"
    payload.write_bytes(b"synthetic outer snapshot")
    runner = FakeSubprocessRunner(
        subprocess.CompletedProcess(
            args=["oci"],
            returncode=0,
            stdout=json.dumps({"etag": "etag-123"}),
            stderr="",
        )
    )
    uploader = SubprocessOciUploader(runner=runner, timeout_seconds=23)

    with pytest.raises(OciBackupError, match="sha256|digest|checksum"):
        await uploader.upload(
            path=payload,
            namespace="namespace",
            region="me-dubai-1",
            bucket="medical-bot-backups",
            object_name="backups/zb/2026/08/24/id/snapshot.tar",
            sha256="not-a-sha256-digest",
        )

    assert runner.calls == []


@pytest.mark.asyncio
async def test_subprocess_oci_uploader_rejects_digest_mismatch_before_runner_call(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "snapshot.tar"
    payload.write_bytes(b"synthetic outer snapshot")
    runner = FakeSubprocessRunner(
        subprocess.CompletedProcess(
            args=["oci"],
            returncode=0,
            stdout=json.dumps({"etag": "etag-123"}),
            stderr="",
        )
    )
    uploader = SubprocessOciUploader(runner=runner, timeout_seconds=23)

    with pytest.raises(OciBackupError, match="checksum|digest"):
        await uploader.upload(
            path=payload,
            namespace="namespace",
            region="me-dubai-1",
            bucket="medical-bot-backups",
            object_name="backups/zb/2026/08/24/id/snapshot.tar",
            sha256="0" * 64,
        )

    assert runner.calls == []


def test_backup_object_name_is_date_partitioned_uuid_without_local_paths_or_secrets() -> None:
    backup_id = UUID("12345678-1234-5678-1234-567812345678")

    object_name = make_backup_object_name(
        datetime(2026, 8, 24, 3, 30, tzinfo=UTC),
        backup_id,
    )

    assert object_name == "backups/zb/2026/08/24/12345678-1234-5678-1234-567812345678/snapshot.tar"
    assert "C:\\" not in object_name
    assert "secret" not in object_name.casefold()


def test_create_verified_bundle_contains_exact_regular_snapshot_contract_members(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)

    bundle_path = create_verified_bundle(
        snapshot_dir=request.output_dir,
        output_dir=tmp_path / "outer",
        object_name="backups/zb/2026/08/24/id/snapshot.tar",
    )

    with tarfile.open(bundle_path, "r") as archive:
        members = archive.getmembers()

    assert {member.name for member in members} == {
        "sqlite/main.db",
        "sqlite/reminders.db",
        "generated-medical-documents.tar",
        "metadata.json",
        "SHA256SUMS",
        "COMPLETE",
    }
    assert all(member.isfile() for member in members)


def test_create_verified_bundle_rejects_unverified_snapshot_before_output_creation(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    (request.output_dir / "COMPLETE").unlink()
    outer_dir = tmp_path / "outer"

    with pytest.raises(OciBackupError, match="verified"):
        create_verified_bundle(
            snapshot_dir=request.output_dir,
            output_dir=outer_dir,
            object_name="backups/zb/2026/08/24/id/snapshot.tar",
        )

    assert outer_dir.exists() is False


def test_create_verified_bundle_rejects_preexisting_output_directory(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    outer_dir = tmp_path / "outer"
    outer_dir.mkdir()

    with pytest.raises(OciBackupError):
        create_verified_bundle(
            snapshot_dir=request.output_dir,
            output_dir=outer_dir,
            object_name="backups/zb/2026/08/24/id/snapshot.tar",
        )

    assert list(outer_dir.iterdir()) == []


@pytest.mark.parametrize(
    "symlink_kind",
    ["main-db", "reminders-db", "generated-root", "history-parent"],
)
def test_run_backup_rejects_symlinked_source_before_export_bundle_or_upload(
    tmp_path: Path,
    symlink_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setenv("OCI_REGION", "me-dubai-1")
    monkeypatch.setenv("OCI_NAMESPACE", "synthetic-namespace")
    monkeypatch.setenv("OCI_BUCKET", "synthetic-bucket")
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    monkeypatch.setattr(backup_to_oci, "_create_work_dir", lambda root: work_dir)
    (data_root / "zb.db").write_bytes(b"main")
    (data_root / "reminders.db").write_bytes(b"reminders")
    history_root = data_root / "history_of_illness"
    history_root.mkdir()
    (history_root / "generated").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if symlink_kind == "main-db":
        (data_root / "zb.db").unlink()
        (outside / "zb.db").write_bytes(b"outside main")
        try:
            (data_root / "zb.db").symlink_to(outside / "zb.db")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are unavailable on this Windows test host")
    elif symlink_kind == "reminders-db":
        (data_root / "reminders.db").unlink()
        (outside / "reminders.db").write_bytes(b"outside reminders")
        try:
            (data_root / "reminders.db").symlink_to(outside / "reminders.db")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are unavailable on this Windows test host")
    elif symlink_kind == "generated-root":
        (history_root / "generated").rmdir()
        try:
            (history_root / "generated").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are unavailable on this Windows test host")
    else:
        (history_root / "generated").rmdir()
        history_root.rmdir()
        try:
            history_root.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are unavailable on this Windows test host")

    calls: list[str] = []

    def export_was_called(*args: object, **kwargs: object) -> None:
        calls.append("export")
        raise OciBackupError("export called")

    monkeypatch.setattr(backup_to_oci, "export_snapshot", export_was_called)
    with pytest.raises(OciBackupError):
        backup_to_oci._run_backup(data_root)

    assert calls == []


def test_run_backup_rejects_work_root_inside_data_root_before_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _create_valid_data_root(data_root)
    forbidden_work = data_root / "forbidden-work"
    monkeypatch.setenv("OCI_REGION", "me-dubai-1")
    monkeypatch.setenv("OCI_NAMESPACE", "synthetic-namespace")
    monkeypatch.setenv("OCI_BUCKET", "synthetic-bucket")
    monkeypatch.setenv("OCI_BACKUP_WORK_ROOT", str(forbidden_work))
    events: list[str] = []

    def export_guard(*args: object, **kwargs: object) -> None:
        events.append("export")

    def bundle_guard(**kwargs: object) -> Path:
        events.append("bundle")
        raise AssertionError("bundle must not be created")

    class UploaderGuard:
        async def upload(self, **kwargs: object) -> UploadReport:
            events.append("upload")
            raise AssertionError("upload must not be attempted")

    monkeypatch.setattr(backup_to_oci, "export_snapshot", export_guard)
    monkeypatch.setattr(backup_to_oci, "create_verified_bundle", bundle_guard)
    monkeypatch.setattr(backup_to_oci, "SubprocessOciUploader", UploaderGuard)

    with pytest.raises(OciBackupError, match="work root|backup work"):
        backup_to_oci._run_backup(data_root)

    assert forbidden_work.exists() is False
    assert events == []


def test_run_backup_uses_host_paths_and_export_bundle_upload_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _create_valid_data_root(data_root)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    bundle_path = work_dir / "outer" / "bundle.tar"
    bundle_path.parent.mkdir()
    bundle_path.write_bytes(b"bundle")
    events: list[str] = []
    exported_request: dict[str, object] = {}
    uploaded: dict[str, object] = {}

    monkeypatch.setenv("OCI_REGION", "me-dubai-1")
    monkeypatch.setenv("OCI_NAMESPACE", "synthetic-namespace")
    monkeypatch.setenv("OCI_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(backup_to_oci, "_create_work_dir", lambda root: work_dir)
    fixed_when = datetime(2026, 8, 24, 3, 30, tzinfo=UTC)
    fixed_backup_id = UUID("12345678-1234-5678-1234-567812345678")

    def fake_export(request: object) -> None:
        events.append("export")
        exported_request["request"] = request

    def fake_bundle(**kwargs: object) -> Path:
        events.append("bundle")
        assert kwargs["snapshot_dir"] == work_dir / "snapshot"
        return bundle_path

    class FakeUploader:
        async def upload(self, **kwargs: object) -> UploadReport:
            events.append("upload")
            uploaded.update(kwargs)
            return UploadReport(etag="etag")

    monkeypatch.setattr(backup_to_oci, "export_snapshot", fake_export)
    monkeypatch.setattr(backup_to_oci, "create_verified_bundle", fake_bundle)
    monkeypatch.setattr(backup_to_oci, "SubprocessOciUploader", FakeUploader)
    monkeypatch.setattr(backup_to_oci, "sha256", lambda path: VALID_SHA256)

    backup_to_oci._run_backup(
        data_root,
        when=fixed_when,
        backup_id=fixed_backup_id,
    )

    request = exported_request["request"]
    assert request.main_db == data_root / "zb.db"
    assert request.reminders_db == data_root / "reminders.db"
    assert request.generated_root == data_root / "history_of_illness" / "generated"
    assert request.source_generated_root == PurePosixPath(
        "/app/data/history_of_illness/generated"
    )
    assert request.output_dir == work_dir / "snapshot"
    assert events == ["export", "bundle", "upload"]
    assert uploaded["namespace"] == "synthetic-namespace"
    assert uploaded["region"] == "me-dubai-1"
    assert uploaded["bucket"] == "synthetic-bucket"
    assert uploaded["object_name"] == (
        "backups/zb/2026/08/24/12345678-1234-5678-1234-567812345678/snapshot.tar"
    )
    assert uploaded["path"] == bundle_path
    assert uploaded["sha256"] == VALID_SHA256


def test_run_backup_removes_work_dir_after_successful_upload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _create_valid_data_root(data_root)
    work_dir = tmp_path / "work-success"
    work_dir.mkdir()
    bundle_path = work_dir / "outer" / "bundle.tar"
    bundle_path.parent.mkdir()
    bundle_path.write_bytes(b"bundle")
    events: list[str] = []

    monkeypatch.setenv("OCI_REGION", "me-dubai-1")
    monkeypatch.setenv("OCI_NAMESPACE", "synthetic-namespace")
    monkeypatch.setenv("OCI_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(backup_to_oci, "_create_work_dir", lambda root: work_dir)

    def fake_export(request: object) -> None:
        events.append("export")

    def fake_bundle(**kwargs: object) -> Path:
        events.append("bundle")
        return bundle_path

    class SuccessfulUploader:
        async def upload(self, **kwargs: object) -> UploadReport:
            events.append("upload")
            return UploadReport(etag="etag")

    monkeypatch.setattr(backup_to_oci, "export_snapshot", fake_export)
    monkeypatch.setattr(backup_to_oci, "create_verified_bundle", fake_bundle)
    monkeypatch.setattr(backup_to_oci, "SubprocessOciUploader", SuccessfulUploader)
    monkeypatch.setattr(backup_to_oci, "sha256", lambda path: VALID_SHA256)

    backup_to_oci._run_backup(
        data_root,
        when=datetime(2026, 8, 24, 3, 30, tzinfo=UTC),
        backup_id=UUID("12345678-1234-5678-1234-567812345678"),
    )

    assert events == ["export", "bundle", "upload"]
    assert work_dir.exists() is False


def test_run_backup_retains_work_dir_after_upload_failure_without_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _create_valid_data_root(data_root)
    work_dir = tmp_path / "work-failure"
    work_dir.mkdir()
    bundle_path = work_dir / "outer" / "bundle.tar"
    bundle_path.parent.mkdir()
    bundle_path.write_bytes(b"bundle")
    events: list[str] = []

    monkeypatch.setenv("OCI_REGION", "me-dubai-1")
    monkeypatch.setenv("OCI_NAMESPACE", "synthetic-namespace")
    monkeypatch.setenv("OCI_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(backup_to_oci, "_create_work_dir", lambda root: work_dir)

    def fake_export(request: object) -> None:
        events.append("export")

    def fake_bundle(**kwargs: object) -> Path:
        events.append("bundle")
        return bundle_path

    class FailingUploader:
        async def upload(self, **kwargs: object) -> UploadReport:
            events.append("upload")
            raise RuntimeError("ocid1.object.oc1..upload-secret")

    monkeypatch.setattr(backup_to_oci, "export_snapshot", fake_export)
    monkeypatch.setattr(backup_to_oci, "create_verified_bundle", fake_bundle)
    monkeypatch.setattr(backup_to_oci, "SubprocessOciUploader", FailingUploader)
    monkeypatch.setattr(backup_to_oci, "sha256", lambda path: VALID_SHA256)

    with pytest.raises(OciBackupError, match="OCI upload failed") as error_info:
        backup_to_oci._run_backup(
            data_root,
            when=datetime(2026, 8, 24, 3, 30, tzinfo=UTC),
            backup_id=UUID("12345678-1234-5678-1234-567812345678"),
        )

    assert events == ["export", "bundle", "upload"]
    assert work_dir.exists() is True
    assert "ocid1.object.oc1..upload-secret" not in str(error_info.value)


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"OCI_REGION": "", "OCI_NAMESPACE": "namespace", "OCI_BUCKET": "bucket"},
    ],
    ids=["missing", "blank-region"],
)
def test_backup_cli_invalid_config_has_only_generic_stderr(
    tmp_path: Path,
    environment: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root = tmp_path / "data"
    _create_valid_data_root(data_root)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    for name in ("OCI_REGION", "OCI_NAMESPACE", "OCI_BUCKET"):
        if name not in environment:
            monkeypatch.delenv(name, raising=False)

    result = backup_to_oci.main(["--data-root", str(data_root)])

    assert result == 1
    assert capsys.readouterr().err == "OCI backup failed\n"
