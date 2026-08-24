from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
from collections.abc import Iterable
from pathlib import Path

import pytest
from test_vps_snapshot_export import make_request

from deploy.snapshot_export import export_snapshot
from deploy.snapshot_verifier import SnapshotVerificationError, verify_snapshot

WINDOWS_ADVERSARIAL_MEMBER_NAMES = (
    ("2026/Record.docx", "2026/record.docx"),
    ("2026/record:stream.docx",),
    ("2026:ads/record.docx",),
    ("2026/record<bad.docx",),
    ("2026/record>bad.docx",),
    ('2026/record"bad.docx',),
    ("2026/record|bad.docx",),
    ("2026/record?bad.docx",),
    ("2026/record*bad.docx",),
    ("2026/record.docx.",),
    ("2026/record.docx ",),
    ("2026/record\x01.docx",),
) + tuple(
    (f"2026/{device_name}.docx",)
    for device_name in (
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    )
) + tuple(
    (f"2026/{device_name}.docx",)
    for device_name in (
        "COM¹",
        "COM²",
        "COM³",
        "LPT¹",
        "LPT²",
        "LPT³",
        "CONIN$",
        "CONOUT$",
    )
) + tuple(
    (f"2026/{device_name}/record.docx",)
    for device_name in (
        "COM¹",
        "COM²",
        "COM³",
        "LPT¹",
        "LPT²",
        "LPT³",
        "CONIN$",
        "CONOUT$",
    )
)


def _replace_document_archive(snapshot_dir: Path, member_names: Iterable[str]) -> None:
    names = list(member_names)
    archive_path = snapshot_dir / "generated-medical-documents.tar"
    with tarfile.open(archive_path, "w") as archive:
        for index, name in enumerate(names):
            payload = f"synthetic document {index}".encode()
            member = tarfile.TarInfo(name=name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))

    metadata_path = snapshot_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["document_count"] = len(names)
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    _refresh_manifest_digest(snapshot_dir, "generated-medical-documents.tar")
    _refresh_manifest_digest(snapshot_dir, "metadata.json")


def _refresh_manifest_digest(snapshot_dir: Path, artifact_name: str) -> None:
    manifest_path = snapshot_dir / "SHA256SUMS"
    digest = hashlib.sha256((snapshot_dir / artifact_name).read_bytes()).hexdigest()
    lines = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        old_digest, name = line.split(maxsplit=1)
        lines.append(f"{digest if name == artifact_name else old_digest}  {name}")
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_verify_snapshot_checks_complete_manifest_hashes_and_sqlite_integrity(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)

    report = verify_snapshot(request.output_dir)

    assert report.complete is True
    assert report.artifact_count == 4
    assert report.document_count == 2


@pytest.mark.asyncio
async def test_verify_snapshot_is_read_only_and_rejects_missing_complete_marker(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    before = {
        path.relative_to(request.output_dir): path.read_bytes()
        for path in request.output_dir.rglob("*")
        if path.is_file()
    }
    (request.output_dir / "COMPLETE").unlink()
    before.pop(Path("COMPLETE"))

    with pytest.raises(SnapshotVerificationError, match="COMPLETE"):
        verify_snapshot(request.output_dir)

    after = {
        path.relative_to(request.output_dir): path.read_bytes()
        for path in request.output_dir.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.asyncio
async def test_verify_snapshot_rejects_tampered_artifact_without_repairing_it(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    metadata_path = request.output_dir / "metadata.json"
    original = metadata_path.read_bytes()
    metadata_path.write_bytes(original + b"tampered")

    with pytest.raises(SnapshotVerificationError, match="checksum"):
        verify_snapshot(request.output_dir)

    assert metadata_path.read_bytes() == original + b"tampered"


@pytest.mark.asyncio
async def test_verify_snapshot_rejects_sqlite_foreign_key_corruption(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    copied_db = request.output_dir / "sqlite" / "main.db"
    with sqlite3.connect(copied_db) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
        )
        connection.execute("INSERT INTO child (id, parent_id) VALUES (1, 404)")
        connection.commit()

    # Refreshing the manifest is intentionally not enough: the verifier must
    # independently run foreign_key_check rather than trusting SHA256SUMS.
    manifest = request.output_dir / "SHA256SUMS"
    lines = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, artifact = line.split(maxsplit=1)
        if artifact == "sqlite/main.db":
            digest = hashlib.sha256(copied_db.read_bytes()).hexdigest()
        lines.append(f"{digest}  {artifact}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SnapshotVerificationError, match="foreign key"):
        verify_snapshot(request.output_dir)


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
async def test_verify_snapshot_rejects_unsafe_or_duplicate_tar_members(
    tmp_path: Path,
    member_names: list[str],
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    _replace_document_archive(request.output_dir, member_names)

    with pytest.raises(SnapshotVerificationError, match="unsafe|duplicate"):
        verify_snapshot(request.output_dir)


@pytest.mark.parametrize(
    "extra_path",
    [
        Path(".env"),
        Path("sqlite/main.db-wal"),
        Path("sqlite/main.db-shm"),
        Path("unexpected-artifact.txt"),
        Path("unexpected-directory"),
    ],
    ids=["env", "wal", "shm", "regular-artifact", "directory"],
)
@pytest.mark.asyncio
async def test_verify_snapshot_rejects_any_unmanifested_layout_entry(
    tmp_path: Path,
    extra_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    added_path = request.output_dir / extra_path
    if extra_path.name == "unexpected-directory":
        added_path.mkdir()
    else:
        added_path.write_bytes(b"unexpected synthetic content")

    with pytest.raises(SnapshotVerificationError, match="layout|unexpected|artifact"):
        verify_snapshot(request.output_dir)


@pytest.mark.asyncio
async def test_verify_snapshot_rejects_unmanifested_symlink(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    target = tmp_path / "outside.txt"
    target.write_bytes(b"outside")
    link = request.output_dir / "unexpected-link"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this Windows test host")

    with pytest.raises(SnapshotVerificationError, match="layout|unexpected|symlink"):
        verify_snapshot(request.output_dir)


@pytest.mark.parametrize("format_version", [None, 999], ids=["missing", "unknown"])
@pytest.mark.asyncio
async def test_verify_snapshot_rejects_missing_or_unknown_metadata_format_version(
    tmp_path: Path,
    format_version: int | None,
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    metadata_path = request.output_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if format_version is None:
        metadata.pop("format_version", None)
    else:
        metadata["format_version"] = format_version
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    _refresh_manifest_digest(request.output_dir, "metadata.json")

    with pytest.raises(SnapshotVerificationError, match="metadata|format"):
        verify_snapshot(request.output_dir)


@pytest.mark.parametrize(
    "member_names",
    WINDOWS_ADVERSARIAL_MEMBER_NAMES,
    ids=lambda member_names: member_names[0],
)
@pytest.mark.asyncio
async def test_verify_snapshot_rejects_windows_unsafe_member_names(
    tmp_path: Path,
    member_names: tuple[str, ...],
) -> None:
    request = make_request(tmp_path)
    export_snapshot(request)
    _replace_document_archive(request.output_dir, member_names)

    with pytest.raises(SnapshotVerificationError, match="unsafe|duplicate|invalid"):
        verify_snapshot(request.output_dir)
