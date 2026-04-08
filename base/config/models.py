from pydantic import BaseModel


# ======================== MQTT ======================== #

class MQTTConfig(BaseModel):
    """MQTT broker connection settings."""
    host: str = "localhost"
    port: int = 1883
    keepalive: int = 60
    reconnect_interval: float = 5.0
    topic_prefix: str = "project"


# ======================== Database ======================== #

class DatabaseConfig(BaseModel):
    """SQLite database settings."""
    enabled: bool = True
    filename: str = "data.db"
    path: str = "./data"


# ======================== API ======================== #

class APIConfig(BaseModel):
    """Web API server settings."""
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8080


# ======================== Service ======================== #

class ServiceConfig(BaseModel):
    """Systemd service settings."""
    enabled: bool = False
    name: str = "project"


# ======================== SSH Credentials ======================== #

class SSHCredentials(BaseModel):
    """SSH credentials for remote client management."""
    ip: str
    user: str
    password: str


# ======================== Client Entry ======================== #

class ClientEntry(BaseModel):
    """A registered client as seen from the host config."""
    pid: str
    ssh: SSHCredentials
    mqtt_topic: str = ""
    container_name: str = ""


# ======================== Base Client Config ======================== #

class BaseClientConfig(BaseModel):
    """Base configuration for any client. Extend this in your app."""
    pid: str
    mqtt: MQTTConfig = MQTTConfig()
    database: DatabaseConfig = DatabaseConfig()
    service: ServiceConfig = ServiceConfig()


# ======================== Base Host Config ======================== #

class BaseHostConfig(BaseModel):
    """Base configuration for any host. Extend this in your app."""
    project_name: str = ""
    mqtt: MQTTConfig = MQTTConfig()
    database: DatabaseConfig = DatabaseConfig()
    api: APIConfig = APIConfig()
    service: ServiceConfig = ServiceConfig()
    clients: list[ClientEntry] = []
