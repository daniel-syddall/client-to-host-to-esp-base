"""SSH-based remote client management.

Provides commands the host can execute on remote clients over SSH:
reboot, shutdown, clock sync, service control, and arbitrary commands.
Uses paramiko for SSH transport.
"""

import asyncio
import logging
from typing import Any

import paramiko

from base.config import SSHCredentials

logger = logging.getLogger(__name__)


class RemoteClient:
    """SSH interface to a remote client machine.

    Args:
        creds: SSHCredentials with ip, user, password.
        timeout: Connection timeout in seconds.
    """

    def __init__(self, creds: SSHCredentials, timeout: float = 10.0) -> None:
        self._creds = creds
        self._timeout = timeout

    @property
    def ip(self) -> str:
        return self._creds.ip

    # ======================== Core ======================== #

    async def execute(self, command: str) -> tuple[int, str, str]:
        """Execute a command on the remote machine via SSH.

        Returns:
            Tuple of (exit_code, stdout, stderr).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._execute_sync, command)

    def _execute_sync(self, command: str) -> tuple[int, str, str]:
        """Synchronous SSH command execution."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=self._creds.ip,
                username=self._creds.user,
                password=self._creds.password,
                timeout=self._timeout,
            )
            stdin, stdout, stderr = client.exec_command(command, timeout=self._timeout)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()

            logger.debug("SSH %s: '%s' -> rc=%d", self._creds.ip, command, exit_code)
            return exit_code, out, err

        except Exception as e:
            logger.error("SSH %s failed: %s", self._creds.ip, e)
            return -1, "", str(e)
        finally:
            client.close()

    # ======================== Common Commands ======================== #

    async def reboot(self) -> bool:
        """Reboot the remote machine."""
        logger.info("Rebooting %s", self._creds.ip)
        rc, _, _ = await self.execute("sudo reboot")
        return rc in (0, -1)  # -1 expected as connection drops.

    async def shutdown(self) -> bool:
        """Shut down the remote machine."""
        logger.info("Shutting down %s", self._creds.ip)
        rc, _, _ = await self.execute("sudo shutdown -h now")
        return rc in (0, -1)

    async def sync_clock(self) -> bool:
        """Force an NTP time sync on the remote machine."""
        logger.info("Clock sync on %s", self._creds.ip)
        rc, out, err = await self.execute("sudo timedatectl set-ntp true && timedatectl status")
        if rc == 0:
            logger.info("Clock synced: %s", out.split('\n')[0] if out else "ok")
        return rc == 0

    async def get_system_info(self) -> dict[str, Any]:
        """Get basic system info from the remote machine."""
        info: dict[str, Any] = {"ip": self._creds.ip}

        # CPU temperature.
        rc, out, _ = await self.execute("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
        if rc == 0 and out:
            try:
                info["cpu_temp"] = round(int(out) / 1000, 1)
            except ValueError:
                pass

        # CPU usage (1-second sample).
        rc, out, _ = await self.execute(
            "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'"
        )
        if rc == 0 and out:
            try:
                info["cpu_usage"] = round(float(out), 1)
            except ValueError:
                pass

        # Memory usage.
        rc, out, _ = await self.execute(
            "free -m | awk '/Mem:/ {printf \"%.1f\", $3/$2*100}'"
        )
        if rc == 0 and out:
            try:
                info["mem_usage"] = round(float(out), 1)
            except ValueError:
                pass

        # Uptime.
        rc, out, _ = await self.execute("cat /proc/uptime")
        if rc == 0 and out:
            try:
                info["uptime"] = round(float(out.split()[0]), 0)
            except (ValueError, IndexError):
                pass

        return info

    async def ping(self) -> bool:
        """Check if the remote machine is reachable (SSH-level)."""
        rc, _, _ = await self.execute("echo ok")
        return rc == 0

    async def get_autoboot(self, container: str) -> bool:
        """Check if the Docker container is set to restart automatically."""
        rc, out, _ = await self.execute(
            f"docker inspect --format '{{{{.HostConfig.RestartPolicy.Name}}}}' {container}"
        )
        if rc == 0:
            return out.strip() in ("always", "unless-stopped", "on-failure")
        return False

    async def set_autoboot(self, container: str, enabled: bool) -> bool:
        """Set the Docker container restart policy."""
        policy = "unless-stopped" if enabled else "no"
        rc, _, _ = await self.execute(f"docker update --restart={policy} {container}")
        return rc == 0

    async def service_restart(self, service_name: str) -> bool:
        """Restart a systemd service on the remote machine."""
        logger.info("Restarting service '%s' on %s", service_name, self._creds.ip)
        rc, _, err = await self.execute(f"sudo systemctl restart {service_name}")
        if rc != 0:
            logger.error("Service restart failed on %s: %s", self._creds.ip, err)
        return rc == 0

    async def service_status(self, service_name: str) -> str:
        """Get the status of a systemd service on the remote machine."""
        rc, out, _ = await self.execute(f"systemctl is-active {service_name}")
        return out.strip() if rc == 0 else "unknown"
