from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_vps_snapshot_export import make_request
from test_vps_snapshot_verifier import (
    WINDOWS_ADVERSARIAL_MEMBER_NAMES,
    _replace_document_archive,
)

from deploy.restore_drill import RestoreDrillError, restore_snapshot
from deploy.snapshot_export import export_snapshot


@pytest.mark.asyncio
async def test_restore_drill_restores_only_verified_snapshot_into_isolated_directory(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    destination = tmp_path / "restore-drill"

    report = restore_snapshot(request.output_dir, destination)

    assert report.verified is True
    assert (destination / "sqlite" / "main.db").is_file()
    assert (destination / "sqlite" / "reminders.db").is_file()
    assert (destination / "generated-medical-documents" / "2026" / "record-1.docx").read_bytes() == b"referenced document"
    with sqlite3.connect(destination / "sqlite" / "main.db") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


@pytest.mark.asyncio
async def test_restore_drill_rejects_incomplete_snapshot_without_creating_destination(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    (request.output_dir / "COMPLETE").unlink()
    destination = tmp_path / "restore-drill"

    with pytest.raises(RestoreDrillError, match="COMPLETE|verified"):
        restore_snapshot(request.output_dir, destination)

    assert destination.exists() is False


@pytest.mark.asyncio
async def test_restore_drill_never_targets_live_data_directory(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    live_data = tmp_path / "live-data"
    live_data.mkdir()
    sentinel = live_data / "zb.db"
    sentinel.write_bytes(b"live database")

    with pytest.raises(RestoreDrillError, match="live|production|isolated"):
        restore_snapshot(request.output_dir, live_data, live_data_root=live_data)

    assert sentinel.read_bytes() == b"live database"


@pytest.mark.parametrize(
    "member_names",
    [
        [r"..\..\escaped.docx"],
        [r"C:\escaped.docx"],
        [r"\\server\share\escaped.docx"],
        ["../escaped.docx"],
        ["2026/record.docx", "2026/record.docx"],
    ],
    ids=["backslash-traversal", "windows-drive", "windows-unc", "posix-traversal", "duplicate"],
)
@pytest.mark.asyncio
async def test_restore_drill_rejects_unsafe_archive_without_creating_outside_files(
    tmp_path: Path,
    member_names: list[str],
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    _replace_document_archive(request.output_dir, member_names)
    destination = tmp_path / "restore-drill"

    with pytest.raises(RestoreDrillError, match="verified|unsafe|duplicate|could not restore"):
        restore_snapshot(request.output_dir, destination)

    assert destination.exists() is False
    assert list(tmp_path.rglob("escaped.docx")) == []


@pytest.mark.parametrize(
    "member_names",
    WINDOWS_ADVERSARIAL_MEMBER_NAMES,
    ids=lambda member_names: member_names[0],
)
@pytest.mark.asyncio
async def test_restore_drill_rejects_windows_unsafe_names_before_destination_creation(
    tmp_path: Path,
    member_names: tuple[str, ...],
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    _replace_document_archive(request.output_dir, member_names)
    destination = tmp_path / "restore-drill"

    with pytest.raises(RestoreDrillError, match="verified|unsafe|duplicate|invalid"):
        restore_snapshot(request.output_dir, destination)

    assert destination.exists() is False
    assert list(tmp_path.rglob("*bad.docx")) == []
