"""Project Entry Point.

Usage:
    python run.py --mode host   [--config path/to/host.toml]
    python run.py --mode client [--config path/to/client.toml]

Service management:
    python run.py --mode host   --install
    python run.py --mode client --install
    python run.py --mode host   --uninstall
"""

import argparse
import asyncio
import logging
from pathlib import Path

from base.config import load_config
from base.service.systemd import install_service, uninstall_service, generate_unit
from app.models.config import ProjectClientConfig, ProjectHostConfig
from app.client.runtime import ClientRuntime
from app.host.runtime import HostRuntime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("project")

CONFIG_DIR = Path(__file__).parent / "config"

DEFAULTS = {
    "host":   CONFIG_DIR / "host.toml",
    "client": CONFIG_DIR / "client.toml",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Project — Client-Host System")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["host", "client"],
        help="Run as 'host' or 'client'.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a TOML config file. Defaults to config/<mode>.toml.",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install as a systemd service and exit.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Uninstall the systemd service and exit.",
    )
    return parser.parse_args()


# ======================== Service Management ======================== #

def handle_service(args: argparse.Namespace) -> None:
    """Handle --install and --uninstall flags."""
    config_path = args.config or DEFAULTS[args.mode]
    project_root = Path(__file__).parent

    if args.mode == "client":
        config = load_config(config_path, ProjectClientConfig)
        service_cfg = config.service
        description = f"Project Client ({config.pid})"
        privileged = True
    else:
        config = load_config(config_path, ProjectHostConfig)
        service_cfg = config.service
        description = "Project Host"
        privileged = False

    if args.install:
        service_cfg.enabled = True
        logger.info("Installing service: %s", service_cfg.name)

        unit = generate_unit(
            service_config=service_cfg,
            mode=args.mode,
            description=description,
            working_dir=project_root,
            entry_point=project_root / "run.py",
            config_path=args.config,
            privileged=privileged,
        )
        print("\n--- Generated unit file ---")
        print(unit)
        print("--- End unit file ---\n")

        success = install_service(
            service_config=service_cfg,
            mode=args.mode,
            description=description,
            working_dir=project_root,
            entry_point=project_root / "run.py",
            config_path=args.config,
            privileged=privileged,
        )
        if success:
            logger.info("Service installed successfully")
        else:
            logger.error("Service installation failed")

    elif args.uninstall:
        logger.info("Uninstalling service: %s", service_cfg.name)
        success = uninstall_service(service_cfg)
        if success:
            logger.info("Service uninstalled successfully")
        else:
            logger.error("Service uninstallation failed")


# ======================== Main ======================== #

def main() -> None:
    args = parse_args()

    # Handle service management flags.
    if args.install or args.uninstall:
        handle_service(args)
        return

    config_path = args.config or DEFAULTS[args.mode]

    if args.mode == "client":
        config = load_config(config_path, ProjectClientConfig)
        logger.info("CLIENT  pid=%s  broker=%s:%s", config.pid, config.mqtt.host, config.mqtt.port)
        runtime = ClientRuntime(config)
        asyncio.run(runtime.run())
    else:
        config = load_config(config_path, ProjectHostConfig)
        logger.info("HOST  broker=%s:%s  api=%s:%s", config.mqtt.host, config.mqtt.port, config.api.host, config.api.port)
        runtime = HostRuntime(config, config_path=config_path)
        asyncio.run(runtime.run())


if __name__ == "__main__":
    main()
