from __future__ import annotations

import hashlib
import tarfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath

TARGET_GENERATED_ROOT = PurePosixPath("/app/data/history_of_illness/generated")
MANIFEST_ARTIFACTS = (
    "sqlite/main.db",
    "sqlite/reminders.db",
    "generated-medical-documents.tar",
    "metadata.json",
)
WINDOWS_INVALID_COMPONENT_CHARACTERS = frozenset('<>:"|?*')
WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "conin$",
        "conout$",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
        "com¹",
        "com²",
        "com³",
        "lpt¹",
        "lpt²",
        "lpt³",
    }
)


class SnapshotContractError(RuntimeError):
    """Raised when an on-disk snapshot artifact violates its contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_artifact_name(artifact_name: str) -> None:
    path = PurePosixPath(artifact_name)
    if (
        not artifact_name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise SnapshotContractError("manifest contains an unsafe artifact path")


def validate_document_members(
    members: Sequence[tarfile.TarInfo],
) -> list[PurePosixPath]:
    """Return validated archive paths that are safe on both Windows and POSIX."""
    validated_paths: list[PurePosixPath] = []
    seen_paths: set[str] = set()
    for member in members:
        relative_path = _validate_document_member(member)
        normalized_path = _normalize_windows_path(relative_path)
        if normalized_path in seen_paths:
            raise SnapshotContractError("generated document archive has duplicate member")
        seen_paths.add(normalized_path)
        validated_paths.append(relative_path)
    return validated_paths


def _validate_document_member(member: tarfile.TarInfo) -> PurePosixPath:
    member_name = member.name
    if not member.isfile() or not member_name or "\\" in member_name:
        raise SnapshotContractError("generated document archive has unsafe member")

    windows_path = PureWindowsPath(member_name)
    path_parts = member_name.split("/")
    relative_path = PurePosixPath(member_name)
    if (
        windows_path.drive
        or relative_path.is_absolute()
        or any(part in {"", ".", ".."} for part in path_parts)
        or relative_path.suffix.lower() != ".docx"
    ):
        raise SnapshotContractError("generated document archive has unsafe member")
    for component in relative_path.parts:
        _validate_windows_component(component)
    return relative_path


def _validate_windows_component(component: str) -> None:
    if (
        component.endswith((" ", "."))
        or any(
            character in WINDOWS_INVALID_COMPONENT_CHARACTERS
            or ord(character) <= 31
            for character in component
        )
    ):
        raise SnapshotContractError("generated document archive has unsafe member")

    device_base_name = component.split(".", maxsplit=1)[0].rstrip(" .").casefold()
    if device_base_name in WINDOWS_RESERVED_DEVICE_NAMES:
        raise SnapshotContractError("generated document archive has unsafe member")


def _normalize_windows_path(relative_path: PurePosixPath) -> str:
    return "/".join(component.casefold() for component in relative_path.parts)
