from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from deploy.deployment_contract import (
    DeploymentContractError,
    validate_deployment_contract,
)


@pytest.mark.asyncio
async def test_deployment_contract_is_zb_only_and_hardened() -> None:
    contract = validate_deployment_contract(Path("deploy"))

    assert contract.compose_services == ("bot-zb",)
    assert contract.environment["BOT_INSTANCE"] == "zb"
    assert contract.environment["DATA_BASE"] == "/app/data/zb.db"
    assert contract.published_ports == ()
    assert contract.data_mount == "/srv/medical-bot/data:/app/data"
    assert contract.container_user == "10001:10001"
    assert contract.no_new_privileges is True
    assert contract.read_only_root is True
    assert contract.init is True
    assert contract.tmpfs == ("/tmp",)
    assert contract.log_max_size == "10m"


@pytest.mark.asyncio
async def test_deployment_contract_contains_daily_persistent_backup_and_restart_safety() -> None:
    contract = validate_deployment_contract(Path("deploy"))

    assert contract.systemd_bot_unit == "bot-zb.service"
    assert contract.backup_service_unit == "bot-zb-backup.service"
    assert contract.backup_timer_unit == "bot-zb-backup.timer"
    assert contract.backup_timer_on_calendar == "*-*-* 03:30:00"
    assert contract.backup_timer_persistent is True
    assert contract.backup_stops_service == "bot-zb"
    assert contract.backup_restarts_service_on_failure is True


def test_backup_unit_requires_long_start_timeout() -> None:
    backup_text = Path("deploy/systemd/bot-zb-backup.service").read_text(encoding="utf-8")

    assert re.search(r"^TimeoutStartSec=900\s*$", backup_text, re.MULTILINE)


@pytest.mark.asyncio
async def test_deployment_contract_rejects_mm_service_or_published_port_in_synthetic_tree(
    tmp_path: Path,
) -> None:
    deploy_root = tmp_path / "deploy"
    deploy_root.mkdir()
    (deploy_root / "compose.yaml").write_text(
        """services:\n  bot-mm:\n    ports:\n      - '8080:8080'\n""",
        encoding="utf-8",
    )
    (deploy_root / "Dockerfile").write_text("USER 10001:10001\n", encoding="utf-8")

    with pytest.raises(DeploymentContractError, match="bot-zb|port"):
        validate_deployment_contract(deploy_root)


def test_dockerfile_uses_exact_per_file_runtime_seed_copy_allowlist() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    expected_sources = {
        "data/history_of_illness/templates/docx_gen_prompt.txt",
        "data/history_of_illness/templates/zub_mudsrosti_med_card_filled.md",
        "data/history_of_illness/templates/zub_mudsrosti_med_card_unfilled.md",
        "data/history_of_illness/medical_card_filled.pdf",
        "data/history_of_illness/medical_card_wisdom_tooth.docx",
        "data/location/location.png",
        "data/location/location_mm.png",
        "data/price_list/price_mm.jpg",
        "data/price_list/rus_1pg.png",
        "data/price_list/rus_2pg.png",
        "data/price_list/schedule_mm.jpg",
        "data/price_list/uzb_1pg.png",
        "data/price_list/uzb_2pg.png",
    }
    actual_sources: set[str] = set()
    for line in dockerfile.splitlines():
        if not line.startswith("COPY data/"):
            continue
        actual_sources.update(line.split()[1:-1])

    assert actual_sources == expected_sources
    assert not re.search(
        r"^COPY\s+data/(?:history_of_illness/templates|location|price_list)/\s",
        dockerfile,
        re.MULTILINE,
    )


def _synthetic_deploy_tree(tmp_path: Path) -> Path:
    deploy_root = tmp_path / "deploy"
    deploy_root.mkdir()
    shutil.copy2("compose.yaml", deploy_root / "compose.yaml")
    shutil.copy2("Dockerfile", deploy_root / "Dockerfile")
    shutil.copytree("deploy/systemd", deploy_root / "systemd")
    shutil.copytree("deploy/ci", deploy_root / "ci")
    return deploy_root


@pytest.mark.asyncio
async def test_deployment_contract_rejects_backup_unit_without_network_and_bot_ordering(
    tmp_path: Path,
) -> None:
    deploy_root = _synthetic_deploy_tree(tmp_path)
    backup_unit = deploy_root / "systemd" / "bot-zb-backup.service"
    backup_text = backup_unit.read_text(encoding="utf-8")
    backup_text = re.sub(
        r"^Wants=network-online\.target\s*$\n?",
        "",
        backup_text,
        flags=re.MULTILINE,
    )
    backup_text = re.sub(
        r"^After=.*$",
        "After=docker.service",
        backup_text,
        flags=re.MULTILINE,
    )
    backup_unit.write_text(backup_text, encoding="utf-8")

    with pytest.raises(DeploymentContractError, match="network|ordering|bot-zb"):
        validate_deployment_contract(deploy_root)


def test_deployment_contract_rejects_backup_unit_without_long_start_timeout(
    tmp_path: Path,
) -> None:
    deploy_root = _synthetic_deploy_tree(tmp_path)
    backup_unit = deploy_root / "systemd" / "bot-zb-backup.service"
    backup_text = backup_unit.read_text(encoding="utf-8")
    backup_text = re.sub(r"^TimeoutStartSec=.*$\n?", "", backup_text, flags=re.MULTILINE)
    backup_unit.write_text(backup_text, encoding="utf-8")

    with pytest.raises(DeploymentContractError, match="timeout|TimeoutStartSec"):
        validate_deployment_contract(deploy_root)


@pytest.mark.asyncio
async def test_deployment_contract_requires_backup_network_and_bot_ordering() -> None:
    backup_text = Path("deploy/systemd/bot-zb-backup.service").read_text(encoding="utf-8")

    assert "Wants=network-online.target" in backup_text
    assert re.search(
        r"^After=.*network-online\.target.*bot-zb\.service.*$",
        backup_text,
        re.MULTILINE,
    )


def test_backup_unit_runs_tracked_backup_as_python_module() -> None:
    backup_text = Path("deploy/systemd/bot-zb-backup.service").read_text(encoding="utf-8")
    wrapper_text = Path("deploy/ci/run-zb-backup").read_text(encoding="utf-8")

    assert "ExecStart=/usr/local/lib/zb-deploy/run-zb-backup" in backup_text
    assert re.search(r"^ExecStart=.*run-zb-backup\s*$", backup_text, re.MULTILINE)
    assert re.search(r"python3[\s\S]*-m[\s\S]*deploy\.backup_to_oci", wrapper_text)
    assert "--data-root" in wrapper_text
    assert "/srv/medical-bot/data" in wrapper_text
    assert not re.search(
        r"^ExecStart=/usr/bin/python3\s+/.+backup_to_oci\.py\s+",
        backup_text,
        re.MULTILINE,
    )


def test_backup_wrapper_uses_shared_lock_and_holds_it_across_lifecycle() -> None:
    deploy_text = Path("deploy/ci/deploy-zb").read_text(encoding="utf-8")
    backup_text = Path("deploy/ci/run-zb-backup").read_text(encoding="utf-8")

    lock_pattern = r"\bMAINTENANCE_LOCK\s*=\s*['\"]?(/run/lock/[A-Za-z0-9_.-]+)"
    deploy_lock = re.search(lock_pattern, deploy_text)
    backup_lock = re.search(lock_pattern, backup_text)
    assert deploy_lock and backup_lock
    assert deploy_lock.group(1) == backup_lock.group(1)

    lock_position = re.search(
        r"(?:flock|exec\s+\d+>).*?(?:MAINTENANCE_LOCK|/run/lock/)",
        backup_text,
    )
    stop_position = re.search(
        r"docker compose.*\bstop\s+(?:bot-zb|\$COMPOSE_SERVICE)\b",
        backup_text,
    )
    backup_position = re.search(
        r"python3[\s\S]{0,100}-m[\s\S]{0,100}deploy\.backup_to_oci",
        backup_text,
    )
    restart_position = re.search(
        r"docker compose.*\bstart\s+(?:bot-zb|\$COMPOSE_SERVICE)\b",
        backup_text,
    )
    assert lock_position and stop_position and backup_position and restart_position
    assert lock_position.start() <= stop_position.start() < backup_position.start() < restart_position.start()

    unlocks = list(re.finditer(r"(?:flock\s+-u|exec\s+\d+>&-)", backup_text))
    assert not unlocks or all(unlock.start() > restart_position.start() for unlock in unlocks)


@pytest.mark.asyncio
async def test_deployment_contract_rejects_absolute_backup_script_execution(
    tmp_path: Path,
) -> None:
    deploy_root = _synthetic_deploy_tree(tmp_path)
    backup_unit = deploy_root / "systemd" / "bot-zb-backup.service"
    backup_text = backup_unit.read_text(encoding="utf-8")
    backup_text = re.sub(
        r"^ExecStart=.*$",
        "ExecStart=/usr/bin/python3 /opt/telegram_client_manager/deploy/backup_to_oci.py --data-root /srv/medical-bot/data",
        backup_text,
        flags=re.MULTILINE,
    )
    backup_unit.write_text(backup_text, encoding="utf-8")

    with pytest.raises(DeploymentContractError, match="module|backup_to_oci|ExecStart"):
        validate_deployment_contract(deploy_root)


def test_snapshot_export_and_contract_layers_do_not_execute_sqlite_directly() -> None:
    for source_path in (Path("deploy/snapshot_export.py"), Path("deploy/snapshot_contract.py")):
        source = source_path.read_text(encoding="utf-8")
        assert re.search(r"\.execute(?:many)?\s*\(", source) is None, source_path
