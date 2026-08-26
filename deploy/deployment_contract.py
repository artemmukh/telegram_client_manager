from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class DeploymentContractError(RuntimeError):
    """Raised when tracked deployment files violate the ZB VPS contract."""


@dataclass(frozen=True)
class DeploymentContract:
    compose_services: tuple[str, ...]
    environment: dict[str, str]
    published_ports: tuple[str, ...]
    data_mount: str
    container_user: str
    no_new_privileges: bool
    read_only_root: bool
    init: bool
    tmpfs: tuple[str, ...]
    log_max_size: str
    systemd_bot_unit: str
    backup_service_unit: str
    backup_timer_unit: str
    backup_timer_on_calendar: str
    backup_timer_persistent: bool
    backup_stops_service: str
    backup_restarts_service_on_failure: bool


def validate_deployment_contract(deploy_root: Path) -> DeploymentContract:
    """Validate the repository's narrow ZB Docker and systemd deployment shape."""
    compose_path = _find_project_file(deploy_root, "compose.yaml")
    dockerfile_path = _find_project_file(deploy_root, "Dockerfile")
    compose_text = _read_file(compose_path, "compose")
    dockerfile_text = _read_file(dockerfile_path, "Dockerfile")

    services = _read_compose_services(compose_text)
    if services != ("bot-zb",):
        raise DeploymentContractError("compose must define only the bot-zb service")
    if re.search(r"^\s+ports:\s*$", compose_text, re.MULTILINE):
        raise DeploymentContractError("compose must not publish ports")

    environment = {
        "BOT_INSTANCE": _required_compose_value(compose_text, "BOT_INSTANCE"),
        "DATA_BASE": _required_compose_value(compose_text, "DATA_BASE"),
    }
    if environment != {"BOT_INSTANCE": "zb", "DATA_BASE": "/app/data/zb.db"}:
        raise DeploymentContractError("compose environment must be literal ZB values")

    _require_text(compose_text, r"-\s+/srv/medical-bot/data:/app/data\s*$", "data mount")
    _require_text(compose_text, r'user:\s*["\']10001:10001["\']', "container user")
    _require_text(compose_text, r"cap_drop:\s*\n\s*-\s+ALL\s*$", "cap_drop ALL")
    _require_text(compose_text, r"-\s+no-new-privileges:true\s*$", "no-new-privileges")
    _require_text(compose_text, r"read_only:\s*true\s*$", "read-only root")
    _require_text(compose_text, r"tmpfs:\s*\n\s*-\s+/tmp\s*$", "tmpfs /tmp")
    _require_text(compose_text, r"init:\s*true\s*$", "init")
    _require_text(compose_text, r"stop_grace_period:\s*30s\s*$", "graceful stop")
    _require_text(compose_text, r'restart:\s*unless-stopped\s*$', "restart policy")
    _require_text(compose_text, r'max-size:\s*["\']10m["\']\s*$', "log max-size")
    _require_text(compose_text, r'max-file:\s*["\']3["\']\s*$', "log max-file")
    _require_text(dockerfile_text, r"USER\s+10001:10001\s*$", "Dockerfile non-root user")

    systemd_root = deploy_root / "systemd"
    bot_unit = _read_file(systemd_root / "bot-zb.service", "bot systemd unit")
    backup_unit = _read_file(systemd_root / "bot-zb-backup.service", "backup systemd unit")
    timer_unit = _read_file(systemd_root / "bot-zb-backup.timer", "backup systemd timer")
    deploy_script = _read_file(deploy_root / "ci" / "deploy-zb", "deploy script")
    backup_wrapper = _read_file(deploy_root / "ci" / "run-zb-backup", "backup lifecycle wrapper")
    _require_text(bot_unit, r"/opt/telegram_client_manager", "bot repository path")
    _require_text(bot_unit, r"/srv/medical-bot/data", "bot data path")
    _require_text(bot_unit, r"docker compose.*up -d bot-zb", "bot compose start")
    _require_text(bot_unit, r"docker compose.*stop bot-zb", "bot compose stop")
    if re.search(r"(?:After|Requires|Wants)=.*bot-zb-backup\.service", bot_unit):
        raise DeploymentContractError("bot unit must not create a backup ordering cycle")
    _require_text(backup_unit, r"^Wants=network-online\.target\s*$", "backup network")
    _require_text(
        backup_unit,
        r"^After=docker\.service network-online\.target bot-zb\.service\s*$",
        "backup network and bot-zb ordering",
    )
    _require_text(backup_unit, r"^TimeoutStartSec=900\s*$", "backup start timeout")
    _require_text(
        backup_unit,
        r"^ExecStart=/usr/local/lib/zb-deploy/run-zb-backup\s*$",
        "backup ExecStart lifecycle wrapper",
    )
    if re.search(r"^Exec(?:StartPre|StopPost)=", backup_unit, re.MULTILINE):
        raise DeploymentContractError(
            "backup unit must not split its lifecycle across ExecStartPre or ExecStopPost"
        )
    _validate_backup_wrapper(deploy_script, backup_wrapper)
    _require_text(timer_unit, r"OnCalendar=\*-\*-\* 03:30:00", "backup schedule")
    _require_text(timer_unit, r"Persistent=true", "persistent backup timer")

    return DeploymentContract(
        compose_services=services,
        environment=environment,
        published_ports=(),
        data_mount="/srv/medical-bot/data:/app/data",
        container_user="10001:10001",
        no_new_privileges=True,
        read_only_root=True,
        init=True,
        tmpfs=("/tmp",),
        log_max_size="10m",
        systemd_bot_unit="bot-zb.service",
        backup_service_unit="bot-zb-backup.service",
        backup_timer_unit="bot-zb-backup.timer",
        backup_timer_on_calendar="*-*-* 03:30:00",
        backup_timer_persistent=True,
        backup_stops_service="bot-zb",
        backup_restarts_service_on_failure=True,
    )


def _find_project_file(deploy_root: Path, filename: str) -> Path:
    local_path = deploy_root / filename
    if local_path.is_file():
        return local_path
    return deploy_root.parent / filename


def _read_file(path: Path, label: str) -> str:
    if not path.is_file():
        raise DeploymentContractError(f"{label} is missing")
    return path.read_text(encoding="utf-8")


def _read_compose_services(compose_text: str) -> tuple[str, ...]:
    match = re.search(r"^services:\s*$([\s\S]*)", compose_text, re.MULTILINE)
    if match is None:
        raise DeploymentContractError("compose services section is missing")
    services = re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", match.group(1), re.MULTILINE)
    return tuple(services)


def _required_compose_value(compose_text: str, name: str) -> str:
    match = re.search(rf"^\s+{re.escape(name)}:\s*(\S+)\s*$", compose_text, re.MULTILINE)
    if match is None:
        raise DeploymentContractError(f"compose {name} is missing")
    return match.group(1).strip('"\'')


def _require_text(text: str, pattern: str, label: str) -> None:
    if re.search(pattern, text, re.MULTILINE) is None:
        raise DeploymentContractError(f"deployment contract is missing {label}")


def _validate_backup_wrapper(deploy_script: str, backup_wrapper: str) -> None:
    """Require one lock owner for backup quiesce, snapshot, and restart."""
    maintenance_lock = "/run/lock/zb-bot-maintenance.lock"
    _require_text(deploy_script, re.escape(maintenance_lock), "deploy maintenance lock")
    _require_text(backup_wrapper, re.escape(maintenance_lock), "backup maintenance lock")
    _require_text(backup_wrapper, r"exec 9>\"\$MAINTENANCE_LOCK\"", "backup lock descriptor")
    _require_text(backup_wrapper, r"/usr/bin/flock -n 9", "non-blocking backup lock")
    _require_text(backup_wrapper, r"trap restart_bot_before_unlock EXIT", "backup restart trap")

    stop_match = re.search(
        r"/usr/bin/docker compose -f \"\$COMPOSE_FILE\" stop bot-zb",
        backup_wrapper,
    )
    backup_match = re.search(
        r"/usr/bin/python3 -m deploy\.backup_to_oci --data-root /srv/medical-bot/data",
        backup_wrapper,
    )
    restart_match = re.search(
        r"/usr/bin/docker compose -f \"\$COMPOSE_FILE\" start bot-zb",
        backup_wrapper,
    )
    if stop_match is None or backup_match is None or restart_match is None:
        raise DeploymentContractError(
            "backup lifecycle wrapper must stop bot-zb, run the backup module, and start bot-zb"
        )
    if not stop_match.start() < backup_match.start() < restart_match.start():
        raise DeploymentContractError("backup lifecycle wrapper has an unsafe stop/backup/start order")
