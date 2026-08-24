from __future__ import annotations

import json
import tarfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from deploy.snapshot_contract import (
    MANIFEST_ARTIFACTS,
    SnapshotContractError,
    sha256,
    validate_artifact_name,
    validate_document_members,
)
from deploy.sqlite_snapshot_repository import (
    SqliteSnapshotRepository,
    SqliteSnapshotRepositoryError,
)


class SnapshotVerificationError(RuntimeError):
    """Raised when a snapshot cannot be safely trusted or restored."""


@dataclass(frozen=True)
class SnapshotVerificationReport:
    complete: bool
    artifact_count: int
    document_count: int


def verify_snapshot(snapshot_dir: Path) -> SnapshotVerificationReport:
    """Read and validate a snapshot without creating or repairing any files."""
    repository = SqliteSnapshotRepository()
    try:
        _assert_complete(snapshot_dir)
        _assert_expected_layout(snapshot_dir)
        manifest = _read_manifest(snapshot_dir / "SHA256SUMS")
        _verify_manifest(snapshot_dir, manifest)
        metadata = _read_metadata(snapshot_dir / "metadata.json")
        _assert_sqlite_health(repository, snapshot_dir / "sqlite" / "main.db")
        _assert_sqlite_health(repository, snapshot_dir / "sqlite" / "reminders.db")
        document_count = _verify_document_archive(
            snapshot_dir / "generated-medical-documents.tar",
            metadata,
        )
    except SnapshotVerificationError:
        raise
    except (OSError, json.JSONDecodeError, tarfile.TarError, SnapshotContractError) as error:
        raise SnapshotVerificationError(str(error)) from error

    return SnapshotVerificationReport(
        complete=True,
        artifact_count=len(manifest),
        document_count=document_count,
    )


def _assert_expected_layout(snapshot_dir: Path) -> None:
    if snapshot_dir.is_symlink() or not snapshot_dir.is_dir():
        raise SnapshotVerificationError("snapshot layout is invalid")

    expected_files = set(MANIFEST_ARTIFACTS) | {"SHA256SUMS", "COMPLETE"}
    observed_files: set[str] = set()
    observed_directories: set[str] = set()
    pending_directories = [snapshot_dir]
    while pending_directories:
        directory = pending_directories.pop()
        for entry in directory.iterdir():
            relative_path = entry.relative_to(snapshot_dir).as_posix()
            if entry.is_symlink():
                raise SnapshotVerificationError("snapshot layout contains a symlink")
            if entry.is_dir():
                observed_directories.add(relative_path)
                pending_directories.append(entry)
            elif entry.is_file():
                observed_files.add(relative_path)
            else:
                raise SnapshotVerificationError("snapshot layout contains an unexpected entry")

    if observed_directories != {"sqlite"} or observed_files != expected_files:
        raise SnapshotVerificationError("snapshot layout contains unexpected artifacts")


def _assert_complete(snapshot_dir: Path) -> None:
    complete_path = snapshot_dir / "COMPLETE"
    if not complete_path.is_file() or complete_path.read_text(encoding="utf-8") != "complete\n":
        raise SnapshotVerificationError("snapshot COMPLETE marker is missing or invalid")


def _read_manifest(manifest_path: Path) -> dict[str, str]:
    if not manifest_path.is_file():
        raise SnapshotVerificationError("snapshot checksum manifest is missing")

    checksums: dict[str, str] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        try:
            digest, artifact_name = line.split(maxsplit=1)
        except ValueError as error:
            raise SnapshotVerificationError("invalid checksum manifest") from error
        validate_artifact_name(artifact_name)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise SnapshotVerificationError("invalid checksum manifest")
        if artifact_name in checksums:
            raise SnapshotVerificationError("invalid checksum manifest")
        checksums[artifact_name] = digest

    if set(checksums) != set(MANIFEST_ARTIFACTS):
        raise SnapshotVerificationError("invalid checksum manifest")
    return checksums


def _verify_manifest(snapshot_dir: Path, checksums: dict[str, str]) -> None:
    for artifact_name, expected_digest in checksums.items():
        artifact_path = snapshot_dir / PurePosixPath(artifact_name)
        if not artifact_path.is_file() or sha256(artifact_path) != expected_digest:
            raise SnapshotVerificationError("snapshot checksum verification failed")


def _read_metadata(metadata_path: Path) -> dict[str, object]:
    if not metadata_path.is_file():
        raise SnapshotVerificationError("snapshot metadata is missing")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise SnapshotVerificationError("snapshot metadata is invalid")
    expected_fields = {
        "format_version",
        "created_at_utc",
        "document_count",
        "rewritten_path_count",
        "artifacts",
    }
    if set(metadata) != expected_fields:
        raise SnapshotVerificationError("snapshot metadata is invalid")
    if type(metadata["format_version"]) is not int or metadata["format_version"] != 1:
        raise SnapshotVerificationError("snapshot metadata format is invalid")
    if metadata["artifacts"] != list(MANIFEST_ARTIFACTS):
        raise SnapshotVerificationError("snapshot metadata is invalid")
    if not _is_utc_timestamp(metadata["created_at_utc"]):
        raise SnapshotVerificationError("snapshot metadata is invalid")
    if not _is_nonnegative_int(metadata["document_count"]):
        raise SnapshotVerificationError("snapshot metadata is invalid")
    if not _is_nonnegative_int(metadata["rewritten_path_count"]):
        raise SnapshotVerificationError("snapshot metadata is invalid")
    return metadata


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        timestamp = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return False
    return timestamp.utcoffset() == timedelta(0)


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _assert_sqlite_health(
    repository: SqliteSnapshotRepository,
    database_path: Path,
) -> None:
    try:
        repository.assert_healthy(database_path)
    except SqliteSnapshotRepositoryError as error:
        raise SnapshotVerificationError(str(error)) from error


def _verify_document_archive(archive_path: Path, metadata: dict[str, object]) -> int:
    if not archive_path.is_file():
        raise SnapshotVerificationError("generated document archive is missing")
    with tarfile.open(archive_path, "r") as archive:
        members = archive.getmembers()
    try:
        validate_document_members(members)
    except SnapshotContractError as error:
        raise SnapshotVerificationError(str(error)) from error
    document_count = len(members)
    if document_count != metadata["document_count"]:
        raise SnapshotVerificationError("generated document archive count is invalid")
    return document_count
