"""Systemd service file generator and manager.

Generates, installs, and manages systemd unit files so the project
can run on boot. Works for both host and client modes. Designed to
be reusable across all projects.
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from base.config import ServiceConfig

logger = logging.getLogger(__name__)

SYSTEMD_DIR = Path("/etc/systemd/system")

# Template for the .service unit file.
UNIT_TEMPLATE = """\
[Unit]
Description={description}
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={working_dir}
ExecStart={python} {entry_point} --mode {mode}{config_flag}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Hardening
NoNewPrivileges={no_new_privs}
ProtectSystem=full
ProtectHome=read-only

[Install]
WantedBy=multi-user.target
"""


def generate_unit(
    service_config: ServiceConfig,
    mode: str,
    description: str = "",
    user: str = "root",
    working_dir: str | Path = ".",
    entry_point: str | Path = "run.py",
    config_path: str | Path | None = None,
    privileged: bool = False,
) -> str:
    """Generate the contents of a systemd .service unit file.

    Args:
        service_config: ServiceConfig with name and enabled flag.
        mode: 'host' or 'client'.
        description: Human-readable description for the unit.
        user: Linux user to run the service as.
        working_dir: Absolute path to the project root.
        entry_point: Path to run.py (relative to working_dir or absolute).
        config_path: Optional custom config file path.
        privileged: If True, disables NoNewPrivileges (needed for raw sockets).

    Returns:
        The full unit file contents as a string.
    """
    config_flag = f" --config {config_path}" if config_path else ""
    desc = description or f"{service_config.name} ({mode})"

    return UNIT_TEMPLATE.format(
        description=desc,
        user=user,
        working_dir=str(Path(working_dir).resolve()),
        python=sys.executable,
        entry_point=str(entry_point),
        mode=mode,
        config_flag=config_flag,
        no_new_privs="false" if privileged else "true",
    )


def unit_file_path(service_config: ServiceConfig) -> Path:
    """Get the systemd unit file path for this service."""
    return SYSTEMD_DIR / f"{service_config.name}.service"


def install_service(
    service_config: ServiceConfig,
    mode: str,
    description: str = "",
    user: str = "root",
    working_dir: str | Path = ".",
    entry_point: str | Path = "run.py",
    config_path: str | Path | None = None,
    privileged: bool = False,
) -> bool:
    """Generate, write, and enable the systemd service.

    Returns True if successful, False otherwise.
    """
    if not service_config.enabled:
        logger.info("Service disabled in config — skipping install")
        return False

    unit_content = generate_unit(
        service_config=service_config,
        mode=mode,
        description=description,
        user=user,
        working_dir=working_dir,
        entry_point=entry_point,
        config_path=config_path,
        privileged=privileged,
    )

    unit_path = unit_file_path(service_config)

    try:
        unit_path.write_text(unit_content)
        logger.info("Unit file written: %s", unit_path)

        _run_cmd(["systemctl", "daemon-reload"])
        _run_cmd(["systemctl", "enable", service_config.name])
        _run_cmd(["systemctl", "start", service_config.name])

        logger.info("Service '%s' installed and started", service_config.name)
        return True

    except PermissionError:
        logger.error("Permission denied — run with sudo to install services")
        return False
    except Exception as e:
        logger.error("Service install failed: %s", e)
        return False


def uninstall_service(service_config: ServiceConfig) -> bool:
    """Stop, disable, and remove the systemd service.

    Returns True if successful, False otherwise.
    """
    try:
        _run_cmd(["systemctl", "stop", service_config.name], check=False)
        _run_cmd(["systemctl", "disable", service_config.name], check=False)

        unit_path = unit_file_path(service_config)
        if unit_path.exists():
            unit_path.unlink()
            logger.info("Unit file removed: %s", unit_path)

        _run_cmd(["systemctl", "daemon-reload"])
        logger.info("Service '%s' uninstalled", service_config.name)
        return True

    except PermissionError:
        logger.error("Permission denied — run with sudo to uninstall services")
        return False
    except Exception as e:
        logger.error("Service uninstall failed: %s", e)
        return False


def service_status(service_config: ServiceConfig) -> dict[str, Any]:
    """Get the current status of the service."""
    name = service_config.name
    result = {
        "name": name,
        "installed": unit_file_path(service_config).exists(),
        "active": False,
        "enabled": False,
        "status": "unknown",
    }

    try:
        out = _run_cmd(["systemctl", "is-active", name], check=False, capture=True)
        result["active"] = out.strip() == "active"
        result["status"] = out.strip()

        out = _run_cmd(["systemctl", "is-enabled", name], check=False, capture=True)
        result["enabled"] = out.strip() == "enabled"
    except Exception:
        pass

    return result


# ======================== Internal ======================== #

def _run_cmd(
    cmd: list[str],
    check: bool = True,
    capture: bool = False,
) -> str:
    """Run a shell command."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=check,
    )
    if capture:
        return result.stdout
    return ""
