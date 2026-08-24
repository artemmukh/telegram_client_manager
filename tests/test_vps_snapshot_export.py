from __future__ import annotations

import hashlib
import json
import sqlite3
import tarfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from deploy.snapshot_export import (
    SnapshotExportError,
    SnapshotRequest,
    dry_run_snapshot,
    export_snapshot,
)

SOURCE_ROOT = PureWindowsPath(r"C:\\medical-bot\\data\\history_of_illness\\generated")
TARGET_ROOT = PurePosixPath("/app/data/history_of_illness/generated")


def _create_source_databases(tmp_path: Path) -> tuple[Path, Path]:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    main_db = source_dir / "main.db"
    reminders_db = source_dir / "reminders.db"

    with sqlite3.connect(main_db) as connection:
        connection.execute(
            "CREATE TABLE medical_records (id INTEGER PRIMARY KEY, file_path TEXT)"
        )
        connection.execute(
            "INSERT INTO medical_records (id, file_path) VALUES (?, ?)",
            (1, str(SOURCE_ROOT / "2026" / "record-1.docx")),
        )
        connection.execute(
            "INSERT INTO medical_records (id, file_path) VALUES (?, NULL)",
            (2,),
        )

    with sqlite3.connect(reminders_db) as connection:
        connection.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY, text TEXT)")
        connection.execute("INSERT INTO reminders (id, text) VALUES (1, 'reminder')")

    return main_db, reminders_db


def _create_generated_documents(tmp_path: Path) -> Path:
    generated_root = tmp_path / "generated"
    document_dir = generated_root / "2026"
    document_dir.mkdir(parents=True)
    (document_dir / "record-1.docx").write_bytes(b"referenced document")
    (document_dir / "unreferenced.docx").write_bytes(b"unreferenced document")
    return generated_root


def make_request(tmp_path: Path) -> SnapshotRequest:
    main_db, reminders_db = _create_source_databases(tmp_path)
    return SnapshotRequest(
        main_db=main_db,
        reminders_db=reminders_db,
        generated_root=_create_generated_documents(tmp_path),
        source_generated_root=SOURCE_ROOT,
        output_dir=tmp_path / "snapshot",
    )


def _metadata_values(value: object) -> list[object]:
    if isinstance(value, dict):
        values: list[object] = []
        for nested_value in value.values():
            values.extend(_metadata_values(nested_value))
        return values
    if isinstance(value, list):
        values = []
        for nested_value in value:
            values.extend(_metadata_values(nested_value))
        return values
    return [value]


@pytest.mark.asyncio
async def test_export_snapshot_rewrites_only_copy_and_creates_complete_contract(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    original_db_bytes = request.main_db.read_bytes()

    report = export_snapshot(request)

    assert report.document_count == 2
    assert report.rewritten_path_count == 1
    assert request.main_db.read_bytes() == original_db_bytes
    assert (request.output_dir / "sqlite" / "main.db").is_file()
    assert (request.output_dir / "sqlite" / "reminders.db").is_file()
    assert (request.output_dir / "generated-medical-documents.tar").is_file()
    assert (request.output_dir / "metadata.json").is_file()
    assert (request.output_dir / "SHA256SUMS").is_file()
    assert (request.output_dir / "COMPLETE").read_text(encoding="utf-8") == "complete\n"

    with sqlite3.connect(request.output_dir / "sqlite" / "main.db") as connection:
        copied_path = connection.execute(
            "SELECT file_path FROM medical_records WHERE id = 1"
        ).fetchone()[0]
    assert copied_path == str(TARGET_ROOT / "2026" / "record-1.docx")

    with tarfile.open(request.output_dir / "generated-medical-documents.tar") as archive:
        assert set(archive.getnames()) == {
            "2026/record-1.docx",
            "2026/unreferenced.docx",
        }

    metadata_path = request.output_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    forbidden_values = (
        str(tmp_path),
        str(SOURCE_ROOT),
        "BOT_TOKEN",
        "MISTRAL_API_KEY",
    )
    for value in _metadata_values(metadata):
        assert all(forbidden not in str(value) for forbidden in forbidden_values)

    expected_artifacts = {
        "sqlite/main.db",
        "sqlite/reminders.db",
        "generated-medical-documents.tar",
        "metadata.json",
    }
    checksum_lines = (
        request.output_dir / "SHA256SUMS"
    ).read_text(encoding="utf-8").splitlines()
    checksums: dict[str, str] = {}
    for line in checksum_lines:
        digest, artifact_name = line.split(maxsplit=1)
        checksums[artifact_name] = digest
    assert set(checksums) == expected_artifacts

    for artifact_name in expected_artifacts:
        artifact_path = request.output_dir / artifact_name
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        assert checksums[artifact_name] == digest


@pytest.mark.asyncio
async def test_export_snapshot_fails_without_complete_when_referenced_docx_is_missing(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    (request.generated_root / "2026" / "record-1.docx").unlink()

    with pytest.raises(SnapshotExportError, match="missing generated document"):
        export_snapshot(request)

    assert not (request.output_dir / "COMPLETE").exists()


@pytest.mark.asyncio
async def test_export_snapshot_rejects_file_path_outside_approved_windows_root(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    with sqlite3.connect(request.main_db) as connection:
        connection.execute(
            "UPDATE medical_records SET file_path = ? WHERE id = 1",
            (r"D:\\other\\record-1.docx",),
        )
        connection.commit()

    with pytest.raises(SnapshotExportError, match="outside approved generated root"):
        export_snapshot(request)

    assert not (request.output_dir / "COMPLETE").exists()


@pytest.mark.asyncio
async def test_dry_run_validates_without_creating_requested_output_dir(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)

    report = dry_run_snapshot(request)

    assert report.document_count == 2
    assert request.output_dir.exists() is False


@pytest.mark.asyncio
async def test_export_snapshot_accepts_legacy_posix_container_references(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    main_db = source_dir / "main.db"
    reminders_db = source_dir / "reminders.db"
    generated_root = tmp_path / "generated"
    (generated_root / "2026").mkdir(parents=True)
    (generated_root / "2026" / "record-1.docx").write_bytes(b"document")

    source_root = PurePosixPath("/app/data/history_of_illness/generated")
    with sqlite3.connect(main_db) as connection:
        connection.execute("CREATE TABLE medical_records (id INTEGER PRIMARY KEY, file_path TEXT)")
        connection.execute(
            "INSERT INTO medical_records (id, file_path) VALUES (1, ?)",
            (str(source_root / "2026" / "record-1.docx"),),
        )
    with sqlite3.connect(reminders_db) as connection:
        connection.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY, text TEXT)")

    request = SnapshotRequest(
        main_db=main_db,
        reminders_db=reminders_db,
        generated_root=generated_root,
        source_generated_root=source_root,
        output_dir=tmp_path / "snapshot",
    )

    report = export_snapshot(request)

    assert report.rewritten_path_count == 1
    with sqlite3.connect(request.output_dir / "sqlite" / "main.db") as connection:
        copied_path = connection.execute(
            "SELECT file_path FROM medical_records WHERE id = 1"
        ).fetchone()[0]
    assert copied_path == str(TARGET_ROOT / "2026" / "record-1.docx")


@pytest.mark.asyncio
async def test_export_snapshot_rejects_foreign_key_corruption_before_complete(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    main_db = source_dir / "main.db"
    reminders_db = source_dir / "reminders.db"
    generated_root = _create_generated_documents(tmp_path)

    with sqlite3.connect(main_db) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("CREATE TABLE patients (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE medical_records (id INTEGER PRIMARY KEY, patient_id INTEGER REFERENCES patients(id), file_path TEXT)"
        )
        connection.execute(
            "INSERT INTO medical_records (id, patient_id, file_path) VALUES (1, 999, ?)",
            (str(SOURCE_ROOT / "2026" / "record-1.docx"),),
        )
    with sqlite3.connect(reminders_db) as connection:
        connection.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY, text TEXT)")

    request = SnapshotRequest(
        main_db=main_db,
        reminders_db=reminders_db,
        generated_root=generated_root,
        source_generated_root=SOURCE_ROOT,
        output_dir=tmp_path / "snapshot",
    )

    with pytest.raises(SnapshotExportError, match="foreign key"):
        export_snapshot(request)

    assert not (request.output_dir / "COMPLETE").exists()
