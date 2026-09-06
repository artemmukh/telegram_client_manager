from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


class AssetProvisioningError(RuntimeError):
    """Raised when static runtime assets cannot be provisioned safely."""


STATIC_ASSET_PATHS = frozenset(
    {
        "history_of_illness/templates/docx_gen_prompt.txt",
        "history_of_illness/templates/zub_mudsrosti_med_card_filled.md",
        "history_of_illness/templates/zub_mudsrosti_med_card_unfilled.md",
        "history_of_illness/medical_card_filled.pdf",
        "history_of_illness/medical_card_wisdom_tooth.docx",
        "location/location.png",
        "location/location_mm.png",
        "price_list/price_mm.jpg",
        "price_list/rus_1pg.png",
        "price_list/rus_2pg.png",
        "price_list/schedule_mm.jpg",
        "price_list/uzb_1pg.png",
        "price_list/uzb_2pg.png",
    }
)

REFRESHABLE_STATIC_ASSET_PATHS = frozenset(
    {
        "history_of_illness/templates/docx_gen_prompt.txt",
    }
)


@dataclass(frozen=True)
class AssetProvisioningReport:
    copied_paths: set[str]


def provision_runtime_assets(seed_root: Path, data_root: Path) -> AssetProvisioningReport:
    """Copy new static seed files without touching mutable runtime data."""
    if seed_root.is_symlink() or not seed_root.is_dir():
        raise AssetProvisioningError("runtime seed directory is missing or a symlink")

    data_root.mkdir(parents=True, exist_ok=True)
    if data_root.is_symlink() or not data_root.is_dir():
        raise AssetProvisioningError("runtime data directory is unsafe")

    resolved_seed_root = seed_root.resolve()
    resolved_data_root = data_root.resolve()
    copied_paths: set[str] = set()
    for source_path in sorted(seed_root.rglob("*")):
        if source_path.is_symlink():
            raise AssetProvisioningError("runtime seed contains a symlink")
        if source_path.is_dir():
            continue
        if not source_path.is_file():
            raise AssetProvisioningError("runtime seed contains an unsupported entry")

        relative_path = _safe_relative_path(source_path, resolved_seed_root)
        destination_path = data_root.joinpath(*relative_path.parts)
        _assert_no_destination_symlinks(data_root, relative_path)
        if _is_dynamic_path(relative_path) or not _is_intended_static_asset(relative_path):
            continue
        _assert_within_data_root(destination_path, resolved_data_root)
        if destination_path.exists():
            if relative_path.as_posix() not in REFRESHABLE_STATIC_ASSET_PATHS:
                continue
            if destination_path.read_bytes() == source_path.read_bytes():
                continue
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_destination_symlinks(data_root, relative_path)
        _assert_within_data_root(destination_path, resolved_data_root)
        shutil.copy2(source_path, destination_path)
        copied_paths.add(relative_path.as_posix())

    return AssetProvisioningReport(copied_paths=copied_paths)


def _safe_relative_path(source_path: Path, resolved_seed_root: Path) -> Path:
    try:
        relative_path = source_path.resolve().relative_to(resolved_seed_root)
    except ValueError as error:
        raise AssetProvisioningError("runtime seed entry is outside the seed root") from error
    if not relative_path.parts or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise AssetProvisioningError("runtime seed entry is unsafe")
    return relative_path


def _assert_within_data_root(destination_path: Path, resolved_data_root: Path) -> None:
    try:
        destination_path.resolve().relative_to(resolved_data_root)
    except ValueError as error:
        raise AssetProvisioningError("runtime destination is outside the data root") from error


def _assert_no_destination_symlinks(data_root: Path, relative_path: Path) -> None:
    current_path = data_root
    for component in relative_path.parts:
        current_path /= component
        if current_path.is_symlink():
            raise AssetProvisioningError("runtime destination contains a symlink")
        if not current_path.exists():
            break


def _is_intended_static_asset(relative_path: Path) -> bool:
    return relative_path.as_posix() in STATIC_ASSET_PATHS


def _is_dynamic_path(relative_path: Path) -> bool:
    parts = tuple(part.casefold() for part in relative_path.parts)
    filename = parts[-1]
    return (
        any(part.startswith(("generated", "snapshot")) for part in parts)
        or any(part in {"log", "logs"} for part in parts)
        or filename == ".env"
        or filename.startswith(".env.")
        or filename.endswith(
            (".db", ".sqlite", ".sqlite3", "-wal", "-shm", ".log", ".tar", ".tar.gz", ".tgz")
        )
    )
