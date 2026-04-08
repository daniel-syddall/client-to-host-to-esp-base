"""Service management CLI.

Usage:
    python scripts/service.py install --mode host   [--config path/to/host.toml]
    python scripts/service.py install --mode client [--config path/to/client.toml]
    python scripts/service.py uninstall --mode host
    python scripts/service.py uninstall --mode client
    python scripts/service.py status --mode host
    python scripts/service.py status --mode client
    python scripts/service.py generate --mode host   (prints unit file without installing)

Must be run with sudo for install/uninstall.
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path.
sys.path.insert(0, str(Path(__file__).parent.parent))

from base.config import load_config
from base.service.systemd import (
    generate_unit,
    install_service,
    uninstall_service,
    service_status,
)
from app.models.config import ProjectClientConfig, ProjectHostConfig


PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

DEFAULTS = {
    "host":   CONFIG_DIR / "host.toml",
    "client": CONFIG_DIR / "client.toml",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Project Service Manager")
    parser.add_argument(
        "action",
        choices=["install", "uninstall", "status", "generate"],
        help="Action to perform.",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["host", "client"],
        help="Which mode to manage.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config file.",
    )
    parser.add_argument(
        "--user",
        default="root",
        help="Linux user to run the service as (default: root).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = args.config or DEFAULTS[args.mode]

    if args.mode == "client":
        config = load_config(config_path, ProjectClientConfig)
        service_cfg = config.service
        description = f"Project Client ({config.pid})"
        privileged = True  # Clients may need raw hardware access.
    else:
        config = load_config(config_path, ProjectHostConfig)
        service_cfg = config.service
        description = "Project Host"
        privileged = False

    if args.action == "generate":
        unit = generate_unit(
            service_config=service_cfg,
            mode=args.mode,
            description=description,
            user=args.user,
            working_dir=PROJECT_ROOT,
            entry_point=PROJECT_ROOT / "run.py",
            config_path=config_path if args.config else None,
            privileged=privileged,
        )
        print(unit)

    elif args.action == "install":
        # Force enabled for install action.
        service_cfg.enabled = True
        success = install_service(
            service_config=service_cfg,
            mode=args.mode,
            description=description,
            user=args.user,
            working_dir=PROJECT_ROOT,
            entry_point=PROJECT_ROOT / "run.py",
            config_path=config_path if args.config else None,
            privileged=privileged,
        )
        sys.exit(0 if success else 1)

    elif args.action == "uninstall":
        success = uninstall_service(service_cfg)
        sys.exit(0 if success else 1)

    elif args.action == "status":
        status = service_status(service_cfg)
        print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
