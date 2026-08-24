from __future__ import annotations

from pathlib import Path

import pytest

from deploy.runtime_assets import AssetProvisioningError, provision_runtime_assets


@pytest.mark.asyncio
async def test_provision_runtime_assets_copies_only_static_seed_files(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "image-seed"
    allowed_seed_files = {
        "history_of_illness/templates/docx_gen_prompt.txt": b"prompt",
        "history_of_illness/templates/zub_mudsrosti_med_card_filled.md": b"filled",
        "history_of_illness/templates/zub_mudsrosti_med_card_unfilled.md": b"unfilled",
        "history_of_illness/medical_card_filled.pdf": b"pdf",
        "history_of_illness/medical_card_wisdom_tooth.docx": b"docx",
        "location/location.png": b"location",
        "location/location_mm.png": b"location mm",
        "price_list/price_mm.jpg": b"price mm",
        "price_list/rus_1pg.png": b"rus 1",
        "price_list/rus_2pg.png": b"rus 2",
        "price_list/schedule_mm.jpg": b"schedule",
        "price_list/uzb_1pg.png": b"uzb 1",
        "price_list/uzb_2pg.png": b"uzb 2",
    }
    for relative_path, content in allowed_seed_files.items():
        seed_path = seed / relative_path
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_bytes(content)
    data = tmp_path / "data"
    data.mkdir()
    protected = {
        "zb.db": b"database",
        "zb.db-wal": b"wal",
        "zb.db-shm": b"shm",
        "snapshot.tar": b"snapshot",
        ".env": b"secret",
        "bot.log": b"log",
    }
    for name, content in protected.items():
        (data / name).write_bytes(content)
    generated = data / "history_of_illness" / "generated" / "2026"
    generated.mkdir(parents=True)
    (generated / "record.docx").write_bytes(b"generated")

    report = provision_runtime_assets(seed, data)

    assert report.copied_paths == set(allowed_seed_files)
    for relative_path, content in allowed_seed_files.items():
        assert (data / relative_path).read_bytes() == content
    for name, content in protected.items():
        assert (data / name).read_bytes() == content
    assert (generated / "record.docx").read_bytes() == b"generated"


@pytest.mark.asyncio
async def test_provision_runtime_assets_does_not_copy_seed_dynamic_or_secret_files(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "image-seed"
    seed.mkdir()
    (seed / "zb.db").write_bytes(b"seed database")
    (seed / "generated.docx").write_bytes(b"generated")
    (seed / "snapshot.tar").write_bytes(b"snapshot")
    (seed / ".env").write_bytes(b"secret")
    data = tmp_path / "data"

    report = provision_runtime_assets(seed, data)

    assert report.copied_paths == set()
    assert list(data.rglob("*")) == []


@pytest.mark.asyncio
async def test_provision_runtime_assets_rejects_symlink_escape(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "image-seed"
    seed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    link = seed / "logo.png"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this Windows test host")

    with pytest.raises(AssetProvisioningError, match="symlink|outside"):
        provision_runtime_assets(seed, tmp_path / "data")


@pytest.mark.asyncio
async def test_provision_runtime_assets_never_copies_unknown_or_credential_seed_files(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "image-seed"
    forbidden_paths = (
        "unknown.bin",
        "local-secret.key",
        "credentials.json",
        "server.pem",
        "bot.token",
        "history_of_illness/templates/credentials.txt",
        "history_of_illness/templates/unknown.docx",
        "location/unknown.png",
        "price_list/unknown.png",
    )
    for relative_path in forbidden_paths:
        seed_path = seed / relative_path
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_bytes(b"synthetic credential material")
    data = tmp_path / "data"

    try:
        provision_runtime_assets(seed, data)
    except AssetProvisioningError:
        pass

    for relative_path in forbidden_paths:
        assert (data / relative_path).exists() is False


@pytest.mark.asyncio
async def test_provision_runtime_assets_does_not_overwrite_existing_allowed_static_asset(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "image-seed"
    source = seed / "location" / "location.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new seed image")
    data = tmp_path / "data"
    destination = data / "location" / "location.png"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing runtime image")

    report = provision_runtime_assets(seed, data)

    assert destination.read_bytes() == b"existing runtime image"
    assert "location/location.png" not in report.copied_paths


@pytest.mark.parametrize("target_kind", ["inside", "outside"])
@pytest.mark.asyncio
async def test_provision_runtime_assets_rejects_existing_destination_symlink_component(
    tmp_path: Path,
    target_kind: str,
) -> None:
    seed = tmp_path / "image-seed"
    (seed / "history_of_illness" / "templates").mkdir(parents=True)
    (seed / "history_of_illness" / "templates" / "record.docx").write_bytes(b"template")

    data = tmp_path / "data"
    data.mkdir()
    target = data / "generated" if target_kind == "inside" else tmp_path / "outside"
    target.mkdir()
    destination_component = data / "history_of_illness"
    try:
        destination_component.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this Windows test host")

    with pytest.raises(AssetProvisioningError, match="symlink|unsafe|outside"):
        provision_runtime_assets(seed, data)

    assert destination_component.is_symlink()
    assert (target / "templates" / "record.docx").exists() is False
