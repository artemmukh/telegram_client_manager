from __future__ import annotations

import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from deploy.snapshot_contract import SnapshotContractError, validate_document_members
from deploy.snapshot_verifier import SnapshotVerificationError, verify_snapshot

DEFAULT_LIVE_DATA_ROOT = Path("/srv/medical-bot/data")


class RestoreDrillError(RuntimeError):
    """Raised when an isolated restore drill would be unsafe or unverified."""


@dataclass(frozen=True)
class RestoreDrillReport:
    verified: bool
    destination: Path


def restore_snapshot(
    snapshot_dir: Path,
    destination: Path,
    *,
    live_data_root: Path | None = None,
) -> RestoreDrillReport:
    """Restore a verified snapshot into a new, isolated destination only."""
    try:
        verify_snapshot(snapshot_dir)
    except SnapshotVerificationError as error:
        raise RestoreDrillError("snapshot is not verified") from error

    _assert_isolated_destination(destination, live_data_root)
    try:
        with tarfile.open(snapshot_dir / "generated-medical-documents.tar", "r") as archive:
            members = archive.getmembers()
            relative_paths = validate_document_members(members)
            _restore_verified_snapshot(destination, snapshot_dir, archive, members, relative_paths)
    except (OSError, tarfile.TarError, SnapshotContractError) as error:
        raise RestoreDrillError("could not restore isolated snapshot drill") from error

    return RestoreDrillReport(verified=True, destination=destination)


def _assert_isolated_destination(destination: Path, live_data_root: Path | None) -> None:
    if destination.exists():
        raise RestoreDrillError("restore destination must be a new isolated directory")

    protected_roots = [DEFAULT_LIVE_DATA_ROOT]
    if live_data_root is not None:
        protected_roots.append(live_data_root)
    resolved_destination = destination.resolve()
    for protected_root in protected_roots:
        try:
            resolved_destination.relative_to(protected_root.resolve())
        except ValueError:
            continue
        raise RestoreDrillError("restore destination cannot target live production data")


def _restore_verified_snapshot(
    destination: Path,
    snapshot_dir: Path,
    archive: tarfile.TarFile,
    members: list[tarfile.TarInfo],
    relative_paths: list[PurePosixPath],
) -> None:
    sqlite_destination = destination / "sqlite"
    document_destination = destination / "generated-medical-documents"
    sqlite_destination.mkdir(parents=True)
    shutil.copy2(snapshot_dir / "sqlite" / "main.db", sqlite_destination / "main.db")
    shutil.copy2(snapshot_dir / "sqlite" / "reminders.db", sqlite_destination / "reminders.db")
    _extract_documents(archive, members, relative_paths, document_destination)


def _extract_documents(
    archive: tarfile.TarFile,
    members: list[tarfile.TarInfo],
    relative_paths: list[PurePosixPath],
    document_destination: Path,
) -> None:
    resolved_document_destination = document_destination.resolve()
    for member, relative_path in zip(members, relative_paths, strict=True):
        target_path = document_destination.joinpath(*relative_path.parts)
        resolved_target_path = target_path.resolve()
        try:
            resolved_target_path.relative_to(resolved_document_destination)
        except ValueError as error:
            raise RestoreDrillError("generated document archive is unsafe") from error
        target_path.parent.mkdir(parents=True, exist_ok=True)
        source_file = archive.extractfile(member)
        if source_file is None:
            raise RestoreDrillError("generated document archive is unreadable")
        with source_file, target_path.open("wb") as destination_file:
            shutil.copyfileobj(source_file, destination_file)
