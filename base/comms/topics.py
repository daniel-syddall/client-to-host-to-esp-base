"""Topic builder for MQTT.

All topic strings are derived from the configured prefix, keeping
topic management consistent and eliminating hardcoded strings.

Example with prefix "myproject":
    topics.client_status("pi-01")  -> "myproject/client/pi-01/status"
    topics.host_command()          -> "myproject/host/command"
    topics.all_clients()           -> "myproject/client/+/status"
"""


class TopicManager:
    """Builds MQTT topic strings from a configured prefix.

    Args:
        prefix: The project-level topic prefix (e.g. "myproject").
    """

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    # ======================== Client Topics ======================== #

    def client_status(self, pid: str) -> str:
        """Status heartbeats from a specific client."""
        return f"{self._prefix}/client/{pid}/status"

    def client_data(self, pid: str) -> str:
        """Data payloads from a specific client."""
        return f"{self._prefix}/client/{pid}/data"

    def client_response(self, pid: str) -> str:
        """Command responses from a specific client."""
        return f"{self._prefix}/client/{pid}/response"

    # ======================== Host Topics ======================== #

    def host_command(self) -> str:
        """Commands broadcast from the host."""
        return f"{self._prefix}/host/command"

    def host_command_to(self, pid: str) -> str:
        """Commands targeted at a specific client."""
        return f"{self._prefix}/host/command/{pid}"

    def host_status(self) -> str:
        """Host status / heartbeat."""
        return f"{self._prefix}/host/status"

    # ======================== Wildcard Subscriptions ======================== #

    def all_client_status(self) -> str:
        """Subscribe to status from ALL clients."""
        return f"{self._prefix}/client/+/status"

    def all_client_data(self) -> str:
        """Subscribe to data from ALL clients."""
        return f"{self._prefix}/client/+/data"

    def all_client_responses(self) -> str:
        """Subscribe to responses from ALL clients."""
        return f"{self._prefix}/client/+/response"

    def everything(self) -> str:
        """Subscribe to all topics under the prefix."""
        return f"{self._prefix}/#"
