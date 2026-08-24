from __future__ import annotations

import json
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

from deploy.snapshot_contract import (
    MANIFEST_ARTIFACTS,
    TARGET_GENERATED_ROOT,
    sha256,
)
from deploy.sqlite_snapshot_repository import (
    MedicalRecordFilePath,
    SqliteSnapshotRepository,
    SqliteSnapshotRepositoryError,
)


class SnapshotExportError(RuntimeError):
    """Raised when a local snapshot cannot be exported safely."""


@dataclass(frozen=True)
class SnapshotRequest:
    main_db: Path
    reminders_db: Path
    generated_root: Path
    source_generated_root: PurePath
    output_dir: Path


@dataclass(frozen=True)
class SnapshotReport:
    document_count: int
    rewritten_path_count: int
    output_dir: Path


def export_snapshot(request: SnapshotRequest) -> SnapshotReport:
    """Create a complete snapshot without modifying source databases or documents."""
    _validate_request(request)
    if request.output_dir.exists():
        raise SnapshotExportError("snapshot output directory already exists")
    repository = SqliteSnapshotRepository()

    try:
        sqlite_dir = request.output_dir / "sqlite"
        sqlite_dir.mkdir(parents=True)
        copied_main_db = sqlite_dir / "main.db"
        copied_reminders_db = sqlite_dir / "reminders.db"
        repository.backup_database(request.main_db, copied_main_db)
        repository.backup_database(request.reminders_db, copied_reminders_db)
        _assert_sqlite_health(repository, copied_main_db)
        _assert_sqlite_health(repository, copied_reminders_db)

        mapped_paths = [
            (record, _map_document_path(record.file_path, request))
            for record in repository.list_medical_record_file_paths(copied_main_db)
        ]
        _assert_referenced_documents_exist(mapped_paths)
        _rewrite_copied_paths(repository, copied_main_db, mapped_paths)
        _assert_sqlite_health(repository, copied_main_db)

        archive_path = request.output_dir / "generated-medical-documents.tar"
        document_count = _archive_generated_documents(request.generated_root, archive_path)
        _write_metadata(
            request.output_dir / "metadata.json",
            document_count=document_count,
            rewritten_path_count=len(mapped_paths),
        )
        _write_manifest(request.output_dir)
        (request.output_dir / "COMPLETE").write_text("complete\n", encoding="utf-8")
    except SnapshotExportError:
        raise
    except (OSError, SqliteSnapshotRepositoryError) as error:
        raise SnapshotExportError(str(error)) from error

    return SnapshotReport(
        document_count=document_count,
        rewritten_path_count=len(mapped_paths),
        output_dir=request.output_dir,
    )


def dry_run_snapshot(request: SnapshotRequest) -> SnapshotReport:
    """Validate the full export path without creating the requested output directory."""
    with tempfile.TemporaryDirectory(prefix="vps-snapshot-dry-run-") as temporary_dir:
        temporary_request = SnapshotRequest(
            main_db=request.main_db,
            reminders_db=request.reminders_db,
            generated_root=request.generated_root,
            source_generated_root=request.source_generated_root,
            output_dir=Path(temporary_dir) / "snapshot",
        )
        report = export_snapshot(temporary_request)

    return SnapshotReport(
        document_count=report.document_count,
        rewritten_path_count=report.rewritten_path_count,
        output_dir=request.output_dir,
    )


def _validate_request(request: SnapshotRequest) -> None:
    for database_path in (request.main_db, request.reminders_db):
        if not database_path.is_file():
            raise SnapshotExportError("source SQLite database is missing")
    if not request.generated_root.is_dir():
        raise SnapshotExportError("generated document directory is missing")
    if not _is_approved_source_root(request.source_generated_root):
        raise SnapshotExportError("source generated root must be an absolute local path")


def _is_approved_source_root(source_root: PurePath) -> bool:
    if isinstance(source_root, PureWindowsPath):
        return (
            source_root.is_absolute()
            and bool(source_root.drive)
            and not source_root.drive.startswith("\\\\")
        )
    return isinstance(source_root, PurePosixPath) and source_root.is_absolute()


def _assert_sqlite_health(
    repository: SqliteSnapshotRepository,
    database_path: Path,
) -> None:
    try:
        repository.assert_healthy(database_path)
    except SqliteSnapshotRepositoryError as error:
        raise SnapshotExportError(str(error)) from error


def _map_document_path(
    raw_path: str,
    request: SnapshotRequest,
) -> tuple[Path, PurePosixPath]:
    source_path = _parse_source_path(raw_path, request.source_generated_root)
    if any(part in {".", ".."} for part in source_path.parts):
        raise SnapshotExportError("file path is outside approved generated root")
    try:
        relative_path = source_path.relative_to(request.source_generated_root)
    except ValueError as error:
        raise SnapshotExportError("file path is outside approved generated root") from error
    if not relative_path.parts or any(part in {".", ".."} for part in relative_path.parts):
        raise SnapshotExportError("file path is outside approved generated root")

    resolved_root = request.generated_root.resolve()
    local_path = resolved_root.joinpath(*relative_path.parts)
    try:
        local_path.resolve().relative_to(resolved_root)
    except ValueError as error:
        raise SnapshotExportError("file path is outside approved generated root") from error
    return local_path, TARGET_GENERATED_ROOT.joinpath(*relative_path.parts)


def _parse_source_path(raw_path: str, source_root: PurePath) -> PurePath:
    source_path = type(source_root)(raw_path)
    if not source_path.is_absolute():
        raise SnapshotExportError("file path is outside approved generated root")
    if isinstance(source_path, PureWindowsPath) and (
        not source_path.drive or source_path.drive.startswith("\\\\")
    ):
        raise SnapshotExportError("file path is outside approved generated root")
    return source_path


def _assert_referenced_documents_exist(
    mapped_paths: list[tuple[MedicalRecordFilePath, tuple[Path, PurePosixPath]]],
) -> None:
    for _, (local_path, _) in mapped_paths:
        if (
            local_path.suffix.lower() != ".docx"
            or local_path.is_symlink()
            or not local_path.is_file()
        ):
            raise SnapshotExportError("missing generated document")


def _rewrite_copied_paths(
    repository: SqliteSnapshotRepository,
    database_path: Path,
    mapped_paths: list[tuple[MedicalRecordFilePath, tuple[Path, PurePosixPath]]],
) -> None:
    records = [
        MedicalRecordFilePath(record_id=record.record_id, file_path=str(target_path))
        for record, (_, target_path) in mapped_paths
    ]
    try:
        repository.rewrite_medical_record_file_paths(database_path, records)
    except SqliteSnapshotRepositoryError as error:
        raise SnapshotExportError(str(error)) from error


def _archive_generated_documents(generated_root: Path, archive_path: Path) -> int:
    resolved_root = generated_root.resolve()
    documents = sorted(
        path
        for path in generated_root.rglob("*")
        if path.suffix.lower() == ".docx" and path.is_file() and not path.is_symlink()
    )
    try:
        with tarfile.open(archive_path, "w") as archive:
            for document_path in documents:
                try:
                    relative_path = document_path.resolve().relative_to(resolved_root)
                except ValueError as error:
                    raise SnapshotExportError(
                        "generated document is outside approved root"
                    ) from error
                archive.add(document_path, arcname=relative_path.as_posix(), recursive=False)
    except (OSError, tarfile.TarError) as error:
        raise SnapshotExportError("could not archive generated medical documents") from error
    return len(documents)


def _write_metadata(
    metadata_path: Path,
    *,
    document_count: int,
    rewritten_path_count: int,
) -> None:
    metadata = {
        "format_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "document_count": document_count,
        "rewritten_path_count": rewritten_path_count,
        "artifacts": list(MANIFEST_ARTIFACTS),
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_manifest(output_dir: Path) -> None:
    checksums = {artifact: sha256(output_dir / artifact) for artifact in MANIFEST_ARTIFACTS}
    (output_dir / "SHA256SUMS").write_text(
        "".join(f"{digest}  {artifact}\n" for artifact, digest in checksums.items()),
        encoding="utf-8",
    )
    if any(sha256(output_dir / artifact) != digest for artifact, digest in checksums.items()):
        raise SnapshotExportError("snapshot checksum verification failed")
