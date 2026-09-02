"""Systemd entry point for a verified, instance-principal OCI backup."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from deploy.oci_backup_orchestration import (
    GoogleDriveBackupConfig,
    OciBackupConfig,
    OciBackupError,
    SubprocessGoogleDriveUploader,
    SubprocessOciUploader,
    create_verified_bundle,
    make_backup_object_name,
)
from deploy.snapshot_contract import sha256
from deploy.snapshot_export import SnapshotExportError, SnapshotRequest, export_snapshot


@dataclass(frozen=True)
class _BackupSourcePaths:
    data_root: Path
    main_db: Path
    reminders_db: Path
    generated_root: Path


def main(argv: list[str] | None = None) -> int:
    """Create and upload a backup after systemd has quiesced ``bot-zb``."""
    parser = argparse.ArgumentParser(description="Upload a verified ZB OCI backup")
    parser.add_argument("--data-root", required=True, type=Path)
    arguments = parser.parse_args(argv)

    try:
        _run_backup(arguments.data_root)
    except (OciBackupError, SnapshotExportError, OSError):
        print("Backup failed", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - CLI errors must never disclose local data paths
        print("Backup failed", file=sys.stderr)
        return 1
    return 0


def _run_backup(
    data_root: Path,
    *,
    when: datetime | None = None,
    backup_id: UUID | None = None,
) -> None:
    source_paths = _validated_source_paths(data_root)
    config = OciBackupConfig(
        region=_required_environment("OCI_REGION"),
        namespace=_required_environment("OCI_NAMESPACE"),
        bucket=_required_environment("OCI_BUCKET"),
        object_name=make_backup_object_name(
            when if when is not None else datetime.now(UTC),
            backup_id if backup_id is not None else uuid4(),
        ),
    )
    google_drive_config = _optional_google_drive_config()
    work_dir = _create_work_dir(source_paths.data_root)
    snapshot_dir = work_dir / "snapshot"
    request = SnapshotRequest(
        main_db=source_paths.main_db,
        reminders_db=source_paths.reminders_db,
        generated_root=source_paths.generated_root,
        source_generated_root=PurePosixPath("/app/data/history_of_illness/generated"),
        output_dir=snapshot_dir,
    )
    export_snapshot(request)
    bundle_path = create_verified_bundle(
        snapshot_dir=snapshot_dir,
        output_dir=work_dir / "outer",
        object_name=config.object_name,
    )
    bundle_sha256 = sha256(bundle_path)
    try:
        asyncio.run(
            SubprocessOciUploader().upload(
                path=bundle_path,
                namespace=config.namespace,
                region=config.region,
                bucket=config.bucket,
                object_name=config.object_name,
                sha256=bundle_sha256,
                auth="instance_principal",
                no_overwrite=True,
                verify_checksum=True,
            )
        )
    except Exception as error:
        raise OciBackupError("OCI upload failed") from error
    if google_drive_config is not None:
        try:
            asyncio.run(
                SubprocessGoogleDriveUploader().upload(
                    path=bundle_path,
                    config=google_drive_config,
                    sha256=bundle_sha256,
                )
            )
        except Exception as error:
            raise OciBackupError("Google Drive mirror failed") from error
    _remove_successful_work_dir(work_dir, source_paths.data_root)


def _validated_data_root(data_root: Path) -> Path:
    if data_root.is_symlink() or not data_root.is_dir():
        raise OciBackupError("backup data root is invalid")
    _assert_no_symlink_components(data_root)
    try:
        return data_root.resolve(strict=True)
    except OSError as error:
        raise OciBackupError("backup data root is invalid") from error


def _validated_source_paths(data_root: Path) -> _BackupSourcePaths:
    resolved_data_root = _validated_data_root(data_root)
    main_db = resolved_data_root / "zb.db"
    reminders_db = resolved_data_root / "reminders.db"
    history_root = resolved_data_root / "history_of_illness"
    generated_root = history_root / "generated"

    _assert_real_regular_file(main_db, resolved_data_root)
    _assert_real_regular_file(reminders_db, resolved_data_root)
    _assert_real_directory(history_root, resolved_data_root)
    _assert_real_directory(generated_root, resolved_data_root)
    return _BackupSourcePaths(
        data_root=resolved_data_root,
        main_db=main_db,
        reminders_db=reminders_db,
        generated_root=generated_root,
    )


def _assert_real_regular_file(path: Path, data_root: Path) -> None:
    _assert_safe_source_path(path, data_root)
    if not path.is_file():
        raise OciBackupError("backup source paths are invalid")


def _assert_real_directory(path: Path, data_root: Path) -> None:
    _assert_safe_source_path(path, data_root)
    if not path.is_dir():
        raise OciBackupError("backup source paths are invalid")


def _assert_safe_source_path(path: Path, data_root: Path) -> None:
    _assert_no_symlink_components(path)
    try:
        path.resolve(strict=True).relative_to(data_root)
    except (OSError, ValueError) as error:
        raise OciBackupError("backup source paths are invalid") from error


def _assert_no_symlink_components(path: Path) -> None:
    if _has_symlink_component(path):
        raise OciBackupError("backup source paths are invalid")


def _has_symlink_component(path: Path) -> bool:
    absolute_path = Path(os.path.abspath(path))
    current_path = Path(absolute_path.anchor)
    for component in absolute_path.parts[1:]:
        current_path = current_path / component
        if current_path.is_symlink():
            return True
    return False


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise OciBackupError("OCI backup configuration is invalid")
    return value


def _optional_google_drive_config() -> GoogleDriveBackupConfig | None:
    enabled = os.environ.get("GOOGLE_DRIVE_BACKUP_ENABLED", "").strip().casefold()
    if enabled in {"", "0", "false"}:
        return None
    if enabled not in {"1", "true"}:
        raise OciBackupError("Google Drive mirror configuration is invalid")
    remote = os.environ.get("GOOGLE_DRIVE_RCLONE_REMOTE", "")
    config_path = os.environ.get("GOOGLE_DRIVE_RCLONE_CONFIG", "")
    if not remote.strip() or not config_path.strip():
        raise OciBackupError("Google Drive mirror configuration is invalid")
    return GoogleDriveBackupConfig(remote=remote, config_path=Path(config_path))


def _create_work_dir(data_root: Path) -> Path:
    configured_root = os.environ.get("OCI_BACKUP_WORK_ROOT")
    candidate_root = (
        Path(configured_root).expanduser() if configured_root else Path(tempfile.gettempdir())
    )
    if not candidate_root.is_absolute():
        raise OciBackupError("backup work root is invalid")

    lexical_candidate_root = Path(os.path.abspath(candidate_root))
    if _is_within(lexical_candidate_root, data_root) or _has_symlink_component(
        lexical_candidate_root
    ):
        raise OciBackupError("backup work root is invalid")
    try:
        lexical_candidate_root.mkdir(parents=True, exist_ok=True)
        if _has_symlink_component(lexical_candidate_root):
            raise OciBackupError("backup work root is invalid")
        resolved_candidate_root = lexical_candidate_root.resolve(strict=True)
    except OciBackupError:
        raise
    except OSError as error:
        raise OciBackupError("backup work root is invalid") from error
    if _is_within(resolved_candidate_root, data_root):
        raise OciBackupError("backup work root is invalid")
    try:
        return Path(
            tempfile.mkdtemp(
                prefix="medical-bot-oci-backup-",
                dir=resolved_candidate_root,
            )
        )
    except OSError as error:
        raise OciBackupError("backup work root is invalid") from error


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _remove_successful_work_dir(work_dir: Path, data_root: Path) -> None:
    try:
        resolved_work_dir = work_dir.resolve(strict=True)
        resolved_data_root = data_root.resolve(strict=True)
        unsafe_target = (
            work_dir.is_symlink()
            or not work_dir.is_dir()
            or _has_symlink_component(work_dir)
            or _is_within(resolved_work_dir, resolved_data_root)
            or _is_within(resolved_data_root, resolved_work_dir)
        )
        if unsafe_target:
            raise OciBackupError("local backup cleanup failed")
        shutil.rmtree(work_dir)
    except OciBackupError:
        raise
    except Exception as error:
        raise OciBackupError("local backup cleanup failed") from error


if __name__ == "__main__":
    raise SystemExit(main())
