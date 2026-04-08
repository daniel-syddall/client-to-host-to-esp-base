# Project Baseplate

A reusable async Python framework for building distributed client-host systems over MQTT. Designed for Raspberry Pi deployments where one or more **clients** collect data and stream it to a central **host**, which stores, serves, and displays it in real time through a live web dashboard.

The baseplate provides all the infrastructure — MQTT, heartbeats, state tracking, database, REST API, SSH remote management, and a web UI. Your project-specific logic (what data you collect, how you process it) goes in the `app/` directory.

## Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
  - [Running with Docker (Recommended)](#running-with-docker-recommended)
  - [Running Natively](#running-natively)
- [Configuration Reference](#configuration-reference)
  - [host.toml](#hosttoml)
  - [client.toml](#clienttoml)
  - [mosquitto.conf](#mosquittoconf)
- [Web Dashboard](#web-dashboard)
  - [Client Status Grid](#client-status-grid)
  - [Reboot](#reboot)
  - [Auto-boot](#auto-boot)
  - [Managing Clients](#managing-clients)
- [REST API Reference](#rest-api-reference)
  - [System Endpoints](#system-endpoints)
  - [Remote Management](#remote-management)
  - [Client Config CRUD](#client-config-crud)
  - [Project Endpoints](#project-endpoints)
- [MQTT Communication](#mqtt-communication)
  - [Envelope Format](#envelope-format)
  - [Topic Structure](#topic-structure)
  - [Message Flow](#message-flow)
  - [Message Types](#message-types)
- [Heartbeat & State Machine](#heartbeat--state-machine)
- [Database System](#database-system)
- [SSH Remote Management](#ssh-remote-management)
- [Service Management (systemd)](#service-management-systemd)
- [Building a New Project](#building-a-new-project)
  - [1. Config Models](#1-config-models)
  - [2. Database Tables](#2-database-tables)
  - [3. Data Models](#3-data-models)
  - [4. Client Runtime](#4-client-runtime)
  - [5. Host Runtime](#5-host-runtime)
  - [6. Database Stores](#6-database-stores)
  - [7. API Endpoints](#7-api-endpoints)
  - [8. Dashboard](#8-dashboard)
- [Base Modules Reference](#base-modules-reference)
- [Dependencies](#dependencies)

---

## Overview

The system is split into two roles:

- **Host** — Runs on a central machine (desktop, laptop, or server). Manages an MQTT broker, receives data from one or more clients, stores it in SQLite, serves a REST API, and displays a live web dashboard. Also manages client machines over SSH (reboot, clock sync, health checks, autoboot policy).
- **Client** — Runs on a Raspberry Pi (or any Linux machine). Collects project-specific data, publishes it to the host over MQTT, and monitors the host's availability. Configured to identify itself with a unique `pid`.

Both roles share the same codebase and Docker image. The `--mode` flag selects which role to run.

---

## Architecture

```
┌──────────────────────────────────────────┐         MQTT (port 1883)
│           HOST MACHINE                   │◄────────────────────────────┐
│                                          │                             │
│  ┌─────────────────┐  ┌───────────────┐  │                             │
│  │  HostRuntime    │  │  Mosquitto    │  │                             │
│  │  - MQTT client  │  │  Broker       │  │                    ┌────────────────────┐
│  │  - PeerRegistry │  │  :1883        │  │                    │   CLIENT (Pi)      │
│  │  - HostStore    │  └───────────────┘  │                    │                    │
│  │  - APIServer    │                     │                    │  ClientRuntime     │
│  │  - RemoteClient │  ┌───────────────┐  │   heartbeat (5s)   │  - MQTT client    │
│  │  - Heartbeat    │  │  Web Dashboard│  │◄───────────────────│  - Heartbeat      │
│  │  - Maintenance  │  │  :8080        │  │   data             │  - HostTracker    │
│  └─────────────────┘  └───────────────┘  │◄───────────────────│  - Store (opt.)   │
│                                          │   commands ────────►│                  │
└──────────────────────────────────────────┘                    └────────────────────┘

  SSH management (reboot, clock sync, health)
  ─────────────────────────────────────────►  (each client Pi)
```

---

## Project Structure

```
project/
├── run.py                          # Entry point — parses args, loads config, starts runtime
├── pyproject.toml                  # Project metadata and dependencies
├── Dockerfile                      # Single image used for both host and client
├── docker-compose.yml              # Orchestrates mosquitto, host, client services
├── host.sh                         # Build + start host (mosquitto + host container)
├── client.sh                       # Build + start client container
│
├── config/
│   ├── host.toml                   # Host configuration — edit this for your deployment
│   └── client.toml                 # Client configuration — copy to each Pi
│
├── data/
│   └── host.db                     # SQLite database (auto-created, mounted as volume)
│
├── mosquitto/
│   └── mosquitto.conf              # MQTT broker config (anonymous access, port 1883)
│
├── base/                           # *** BASEPLATE — DO NOT MODIFY ***
│   ├── config/                     # TOML loading and Pydantic models
│   ├── comms/                      # MQTT client, envelope, topics, heartbeat
│   ├── client/                     # HostTracker state machine
│   ├── host/                       # PeerRegistry state machine
│   ├── db/                         # Async SQLite wrapper (WAL mode)
│   ├── api/                        # FastAPI server + base routes + dashboard HTML
│   └── service/                    # Systemd management + SSH RemoteClient
│
├── app/                            # *** YOUR PROJECT-SPECIFIC CODE ***
│   ├── models/
│   │   ├── config.py               # Extend BaseClientConfig / BaseHostConfig
│   │   ├── messages.py             # Data payload Pydantic models
│   │   └── tables.py               # SQLite table definitions
│   ├── client/
│   │   ├── runtime.py              # ClientRuntime — all client logic
│   │   └── store.py                # Client-side DB operations
│   ├── host/
│   │   ├── runtime.py              # HostRuntime — all host logic
│   │   └── store.py                # Host-side DB operations
│   └── api/
│       └── routes.py               # Project-specific API endpoints
│
└── scripts/
    └── service.py                  # Standalone systemd service management CLI
```

---

## Quick Start

### Running with Docker (Recommended)

**Prerequisites:** Docker and Docker Compose installed on both machines.

**On the host machine:**

```bash
# Start the MQTT broker and host container
./host.sh

# Dashboard available at http://localhost:8080
```

**On each client Pi:**

1. Copy the project directory to the Pi.
2. Edit `config/client.toml` — set `pid` to a unique ID and `mqtt.host` to the host machine's IP.
3. Run:

```bash
./client.sh
```

Both scripts automatically rebuild the Docker image on every run (using `CACHEBUST`) so code changes are always picked up.

> **Port conflict on the client?** `client.sh` automatically kills any process or container holding port 1883 before starting — clients don't need a broker, but old containers can occupy the port.

---

### Running Natively

```bash
# Install dependencies
pip install -e .

# Start host
python run.py --mode host

# Start client (separate terminal or machine)
python run.py --mode client

# Use a custom config path
python run.py --mode host --config /path/to/host.toml
python run.py --mode client --config /path/to/client.toml
```

The MQTT broker must be running and reachable before either runtime connects. When running natively on the host machine, start Mosquitto separately:

```bash
mosquitto -c mosquitto/mosquitto.conf
```

---

## Configuration Reference

### host.toml

Located at `config/host.toml`. Mounted as a writable volume in Docker so that changes made through the web UI (adding/removing clients) are persisted to disk.

```toml
project_name = "client-to-host-base"   # Used to auto-derive Docker container names
                                        # Container name = {project_name}-{client_pid}
```

#### `[mqtt]`

| Key | Default | Description |
|-----|---------|-------------|
| `host` | `"mosquitto"` | Broker hostname or IP. When running in Docker Compose, use the service name `"mosquitto"`. When running natively, use `"localhost"`. |
| `port` | `1883` | MQTT broker port. |
| `keepalive` | `60` | Keepalive interval in seconds — how often the client pings the broker. |
| `reconnect_interval` | `5.0` | Seconds to wait before retrying a failed connection. |
| `topic_prefix` | `"project"` | All MQTT topics begin with this string. Must match across host and all clients. |

#### `[database]`

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `true` | Enable SQLite database. Set to `false` to skip all DB operations. |
| `filename` | `"host.db"` | Database file name. |
| `path` | `"./data"` | Directory where the database file is stored. Mapped to `./data` on the host machine via Docker volume. |

#### `[api]`

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `true` | Enable the FastAPI web server and dashboard. |
| `host` | `"0.0.0.0"` | Interface to bind on. `0.0.0.0` listens on all interfaces. |
| `port` | `8080` | HTTP port for the dashboard and API. |

#### `[service]`

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Register the host as a systemd service on startup. Set to `true` to auto-install. |
| `name` | `"project-host"` | Systemd unit name. Controls the service with `systemctl start/stop/status {name}`. |

#### `[[clients]]`

One `[[clients]]` block per registered client. These are managed at runtime through the web UI or REST API — you do not need to edit the file manually.

| Key | Description |
|-----|-------------|
| `pid` | Unique client identifier. Must match the `pid` in that client's `client.toml`. |
| `mqtt_topic` | Auto-derived as `{topic_prefix}/client/{pid}`. Do not set manually. |
| `container_name` | Auto-derived as `{project_name}-{pid}`. Used for Docker autoboot control via SSH. |
| `[clients.ssh].ip` | IP address of the client machine. |
| `[clients.ssh].user` | SSH login username. |
| `[clients.ssh].password` | SSH login password. |

**Example:**

```toml
[[clients]]
pid = "11"
mqtt_topic = "project/client/11"
container_name = "client-to-host-base-11"

[clients.ssh]
ip = "10.70.0.11"
user = "revector"
password = "yourpassword"
```

#### `[storage]`

| Key | Default | Description |
|-----|---------|-------------|
| `max_records` | `999` | Maximum rows per database table before the oldest are pruned. |
| `checkpoint_interval` | `30.0` | How often (seconds) the maintenance loop runs pruning and logs DB stats. |

#### `[sync]`

| Key | Default | Description |
|-----|---------|-------------|
| `clock_sync_interval` | `60.0` | How often (seconds) the host forces NTP time sync on all online clients via SSH. Set to `0` to disable. |
| `pi_check_interval` | `10.0` | How often (seconds) the host polls system info (CPU temp, memory, uptime) from all online clients via SSH. Set to `0` to disable. |

---

### client.toml

Located at `config/client.toml`. Copy to each Pi and set `pid` and `mqtt.host` before running.

```toml
pid = "11"                        # Unique ID — must match the entry in host.toml [[clients]]
```

#### `[mqtt]`

| Key | Default | Description |
|-----|---------|-------------|
| `host` | `"10.70.0.2"` | **Set this to the host machine's IP address.** This is where the MQTT broker runs. |
| `port` | `1883` | MQTT broker port — must match the host broker. |
| `keepalive` | `60` | Keepalive interval in seconds. |
| `reconnect_interval` | `5.0` | Seconds to wait before retrying a failed broker connection. |
| `topic_prefix` | `"project"` | Must match `mqtt.topic_prefix` in host.toml exactly. |

#### `[database]`

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Local SQLite on the client. Disabled by default — clients typically stream data to the host rather than storing locally. Enable if your project needs offline buffering. |
| `filename` | `"client.db"` | Database file name (if enabled). |
| `path` | `"./data"` | Directory for the database file (if enabled). |

#### `[service]`

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Register the client as a systemd service on startup. |
| `name` | `"project-client"` | Systemd unit name. |

---

### mosquitto.conf

Located at `mosquitto/mosquitto.conf`. Mounted read-only into the Mosquitto container.

```
listener 1883          # Accept connections on port 1883
allow_anonymous true   # No authentication required
```

For production deployments consider adding password authentication (`password_file`) and TLS.

---

## Web Dashboard

The dashboard is served at `http://{host-ip}:8080` and auto-refreshes every 3 seconds.

### Client Status Grid

The top section shows a card for every registered client with:

- **Status dot** — colour-coded connection state:
  - Green `ONLINE` — heartbeats arriving on schedule
  - Yellow `STALE` — heartbeat overdue (>15 seconds)
  - Red `OFFLINE` — no heartbeat for >30 seconds
  - Grey `UNKNOWN` — never received a heartbeat
  - Orange blinking `REBOOTING...` — reboot command was issued; waiting for the client to come back online

- **Reboot button** — sends a reboot command to the client over SSH. The card immediately switches to `REBOOTING...` state. Once the client reconnects and its first heartbeat arrives, the state reverts to `ONLINE` automatically.

- **Auto-boot toggle** — checkbox that controls Docker's restart policy on the client machine via SSH (`unless-stopped` = on, `no` = off). State is read from the client on first load and refreshed every 60 seconds. Toggle changes take effect immediately — if the Pi loses power and restarts, the container will (or will not) start depending on this setting.

### Reboot

When you click **Reboot** on a client card:

1. The dashboard confirms via a browser dialog.
2. A `POST /api/remote/reboot/{pid}` request is sent to the host.
3. The host connects to the client Pi over SSH and runs `sudo reboot`.
4. The card **immediately** shows the orange `REBOOTING...` state — no waiting for the next poll.
5. The Reboot button is disabled while rebooting.
6. Once the client reconnects and the API confirms its state as `ONLINE`, the card reverts to normal.

### Auto-boot

The auto-boot toggle uses Docker's built-in restart policy (`docker update --restart=...`) to control whether the client container starts automatically when the Pi boots.

- **Enabled** (`unless-stopped`) — the container starts on boot and restarts after crashes.
- **Disabled** (`no`) — the container only runs when manually started.

The host reads the current policy by running `docker inspect` over SSH. Changes take effect on the Pi immediately and persist across reboots.

> **Requirement:** SSH credentials in `host.toml` must be valid, and Docker must be installed on the client Pi.

### Managing Clients

The **MANAGE CLIENTS** table at the bottom of the dashboard lets you add, edit, and remove clients without editing `host.toml` manually. All changes are saved to disk immediately.

#### Adding a client

1. Click **+ Add Client**.
2. Fill in **Client ID** (must match `pid` in the client's `client.toml`), **IP Address**, **Username**, and **Password**.
3. Click **Save**.

The host automatically derives the MQTT topic (`{prefix}/client/{pid}`) and container name (`{project_name}-{pid}`) — you do not enter these manually.

#### Editing a client

1. Click **Edit** on any row.
2. Update the SSH IP, username, or password.
3. Click **Save**.

The Client ID is read-only in edit mode — it is set by the client's own `client.toml` and cannot be changed from the host.

#### Deleting a client

1. Click **Delete** on any row.
2. Confirm the dialog.

The client is removed **immediately** from both the status grid and the manage table (optimistic UI). The host stops monitoring it and removes it from `host.toml`.

---

## REST API Reference

All endpoints are available at `http://{host-ip}:8080`. Interactive documentation is at `/docs`.

### System Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web dashboard HTML |
| `GET` | `/api/health` | Health check — returns `{"status": "ok"}` |
| `GET` | `/api/status` | Uptime and client registry summary |
| `GET` | `/docs` | Swagger / OpenAPI documentation |

### Remote Management

All remote endpoints require valid SSH credentials for the target client in `host.toml`.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/remote/reboot/{pid}` | Reboot the client machine via SSH |
| `POST` | `/api/remote/shutdown/{pid}` | Shut down the client machine via SSH |
| `POST` | `/api/remote/sync-clock/{pid}` | Force NTP time sync on the client via SSH |
| `GET` | `/api/remote/info/{pid}` | Get system info: CPU temp, CPU usage, memory usage, uptime |
| `POST` | `/api/remote/service-restart/{pid}/{service_name}` | Restart a named systemd service on the client |
| `GET` | `/api/remote/autoboot/{pid}` | Check whether the client's Docker container is set to auto-start |
| `POST` | `/api/remote/autoboot/{pid}` | Set auto-boot policy — body: `{"enabled": true}` or `{"enabled": false}` |

### Client Config CRUD

These endpoints manage the `[[clients]]` list in `host.toml` at runtime.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config/clients` | List all configured clients |
| `POST` | `/api/config/clients` | Add a new client — body: `{"pid": "12", "ssh": {"ip": "...", "user": "...", "password": "..."}}` |
| `PUT` | `/api/config/clients/{pid}` | Update a client's SSH credentials (PID is immutable) |
| `DELETE` | `/api/config/clients/{pid}` | Remove a client |

All changes are immediately written to `host.toml` on disk.

### Project Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/project/stats` | Database stats and full client status map |
| `POST` | `/api/project/command` | Send a command to a specific client — body: `{"pid": "11", "command": "my_cmd", "payload": {}}` |
| `POST` | `/api/project/command/broadcast` | Broadcast a command to all clients — body: `{"command": "my_cmd", "payload": {}}` |

---

## MQTT Communication

### Envelope Format

Every message published over MQTT is wrapped in a standard envelope:

```json
{
    "sender": "11",
    "msg_type": "heartbeat",
    "timestamp": "2026-04-07T10:00:00.000000+00:00",
    "payload": {
        "key": "value"
    }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `sender` | string | Who sent the message. Client PID (e.g. `"11"`) or `"host"`. |
| `msg_type` | string | Message category — one of the base types or a project-specific type. |
| `timestamp` | string | ISO 8601 UTC timestamp. |
| `payload` | object | The actual data. Structure depends on `msg_type`. |

### Topic Structure

All topics are built from `mqtt.topic_prefix` in the config. With the default prefix `"project"`:

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `project/client/{pid}/status` | Client → Host | Client heartbeats (every 5s) |
| `project/client/{pid}/data` | Client → Host | Project-specific data payloads |
| `project/client/{pid}/response` | Client → Host | Responses to commands |
| `project/host/status` | Host → All | Host heartbeats (every 5s) |
| `project/host/command` | Host → All | Broadcast command to all clients |
| `project/host/command/{pid}` | Host → One | Targeted command to a specific client |

**Wildcard subscriptions used by the host:**

| Pattern | Matches |
|---------|---------|
| `project/client/+/status` | All client heartbeats |
| `project/client/+/data` | All client data |
| `project/client/+/response` | All client responses |

### Message Flow

```
Client boot sequence:
  1. Connects to MQTT broker at mqtt.host:mqtt.port
  2. Subscribes to: project/host/status
                    project/host/command
                    project/host/command/{pid}
  3. Publishes heartbeat every 5s to: project/client/{pid}/status
  4. Publishes data to: project/client/{pid}/data

Host boot sequence:
  1. Starts Mosquitto broker (Docker Compose)
  2. Connects to broker at localhost:1883 (inside Docker: "mosquitto:1883")
  3. Subscribes to: project/client/+/status
                    project/client/+/data
                    project/client/+/response
  4. Publishes heartbeat every 5s to: project/host/status
  5. Publishes commands to: project/host/command or project/host/command/{pid}
```

### Message Types

**Base types (built-in):**

| Type | Direction | Purpose |
|------|-----------|---------|
| `heartbeat` | Both | Periodic liveness signal |
| `status` | Both | Detailed status report |
| `command` | Host → Client | Instruction to the client |
| `response` | Client → Host | Reply to a command |
| `data` | Client → Host | Data payload |
| `clock_sync` | Host → Client | Time synchronisation signal |
| `reboot` | Host → Client | Reboot instruction |
| `shutdown` | Host → Client | Shutdown instruction |

**Adding project types:**

Define your own types in `app/models/messages.py`:

```python
class ProjectMessageType:
    SENSOR_DATA = "sensor_data"
    SCAN_RESULT = "scan_result"
    START_SCAN  = "start_scan"
```

Handle them in `HostRuntime._on_client_data()` and `ClientRuntime._on_command()`.

---

## Heartbeat & State Machine

Both sides publish heartbeats every 5 seconds. Both sides monitor the other through the same state machine:

```
UNKNOWN ──(first heartbeat)──────────────────► ONLINE
ONLINE  ──(no heartbeat for 15s)─────────────► STALE
STALE   ──(no heartbeat for 30s)─────────────► OFFLINE
STALE   ──(heartbeat received)───────────────► ONLINE
OFFLINE ──(heartbeat received)───────────────► ONLINE
```

| State | Meaning |
|-------|---------|
| `UNKNOWN` | Initial state — no heartbeat ever received |
| `ONLINE` | Heartbeats arriving on schedule |
| `STALE` | Last heartbeat was more than 15 seconds ago |
| `OFFLINE` | No heartbeat for more than 30 seconds |

State change callbacks fire on every transition. Register them in your runtime:

```python
# Host side — called for each client
self._registry.on_state_change(self._on_client_state_change)

# Client side — called for the host
self._host_tracker.on_state_change(self._on_host_state_change)
```

The host's `PeerRegistry` tracks all clients simultaneously. The client's `HostTracker` tracks only the single host.

---

## Database System

SQLite with WAL mode (allows concurrent reads while writing). The base `Database` class handles connection management, table creation, upsert, and pruning. Your project defines its tables in `app/models/tables.py`.

**Defining tables:**

```python
# app/models/tables.py

SENSOR_READINGS = (
    "sensor_readings",
    """
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_pid  TEXT NOT NULL,
    value       REAL NOT NULL,
    unit        TEXT DEFAULT 'celsius',
    timestamp   TEXT NOT NULL
    """,
)

HOST_TABLES = [SENSOR_READINGS]
CLIENT_TABLES = []              # Define client-side tables here if needed
```

**Using the store:**

```python
# app/host/store.py

class HostStore:
    def __init__(self, db_config, storage_config):
        self._db = Database(db_config)
        self._storage = storage_config

    async def start(self):
        await self._db.connect()
        for name, schema in HOST_TABLES:
            await self._db.create_table(name, schema)

    async def insert_reading(self, pid: str, value: float, unit: str, ts: str):
        await self._db.insert("sensor_readings", {
            "client_pid": pid, "value": value, "unit": unit, "timestamp": ts
        })

    async def prune_all(self):
        await self._db.prune("sensor_readings", self._storage.max_records, "id")
```

**Key Database methods:**

| Method | Description |
|--------|-------------|
| `await connect()` | Open the database file, enable WAL mode, create parent directories. |
| `await close()` | Close the connection cleanly. |
| `await create_table(name, schema)` | Create a table if it doesn't exist. |
| `await insert(table, data_dict)` | Insert a row from a dict. |
| `await upsert(table, data_dict, conflict_col)` | Insert or update on conflict. |
| `await fetch_one(sql, params)` | Fetch a single row as a dict. |
| `await fetch_all(sql, params)` | Fetch all matching rows as a list of dicts. |
| `await count(table, where, params)` | Count rows with optional WHERE clause. |
| `await prune(table, max_rows, order_col)` | Delete oldest rows if count exceeds max. |
| `await size_mb()` | Database file size in MB. |
| `await execute(sql, params)` | Run arbitrary SQL. |

**Automatic pruning:** The `_maintenance_loop` in `HostRuntime` calls `store.prune_all()` every `storage.checkpoint_interval` seconds, keeping each table under `storage.max_records` rows. WAL files (`.db-shm`, `.db-wal`) are normal — they disappear on a clean shutdown.

**Disabling the database:** Set `database.enabled = false` in the config. The entire DB layer is skipped cleanly.

---

## SSH Remote Management

The host connects to each client Pi over SSH using the credentials in `host.toml`. A `RemoteClient` instance is created automatically for each registered client on startup.

**Available operations:**

| Method | Description |
|--------|-------------|
| `await reboot()` | Runs `sudo reboot` on the Pi |
| `await shutdown()` | Runs `sudo shutdown -h now` |
| `await sync_clock()` | Forces NTP sync with `sudo ntpdate -u pool.ntp.org` or `timedatectl` |
| `await get_system_info()` | Returns `{cpu_temp, cpu_usage, mem_usage, uptime}` |
| `await ping()` | SSH-level reachability check (no command run, just TCP connect) |
| `await service_restart(name)` | Runs `sudo systemctl restart {name}` |
| `await service_status(name)` | Returns `True` if the service is active |
| `await execute(command)` | Run any arbitrary command — returns `(exit_code, stdout, stderr)` |
| `await get_autoboot(container)` | Checks Docker restart policy for a container |
| `await set_autoboot(container, enabled)` | Sets Docker restart policy (`unless-stopped` or `no`) |

**Periodic SSH tasks run automatically:**

- **Clock sync** — every `sync.clock_sync_interval` seconds (default 60s), forces NTP sync on all online clients.
- **Health check** — every `sync.pi_check_interval` seconds (default 10s), fetches CPU temp, memory, and uptime from all online clients and attaches the data to their registry entry.

Both loops only run against clients currently in `ONLINE` state and skip gracefully on SSH errors.

---

## Service Management (systemd)

Both host and client can be installed as systemd services that start automatically on boot.

```bash
# Install (requires sudo)
sudo python run.py --mode host --install
sudo python run.py --mode client --install

# Uninstall
sudo python run.py --mode host --uninstall
sudo python run.py --mode client --uninstall
```

Or use the standalone CLI:

```bash
python scripts/service.py install   --mode host
python scripts/service.py uninstall --mode client
python scripts/service.py status    --mode host
python scripts/service.py generate  --mode client  # Preview unit file without installing
```

Once installed, manage with standard systemctl commands:

```bash
sudo systemctl start   project-host
sudo systemctl stop    project-host
sudo systemctl restart project-host
sudo systemctl status  project-host
sudo journalctl -u project-host -f    # Follow logs
```

Generated units auto-restart on crash (10-second delay). The host unit is fully sandboxed (`NoNewPrivileges=true`, `ProtectSystem=full`). The client unit allows hardware access if needed.

> **Note:** When deploying clients as Docker containers (the typical setup), auto-boot is managed through Docker's restart policy rather than systemd. Use the dashboard's **Auto-boot** toggle instead of `--install`.

---

## Building a New Project

`base/` is the framework — treat it as a library and **never modify it**. All project logic goes in `app/`.

### 1. Config Models

Extend the base config classes in `app/models/config.py`:

```python
from pydantic import BaseModel
from base.config import BaseClientConfig, BaseHostConfig

class SensorConfig(BaseModel):
    poll_interval: float = 5.0
    channels: list[str] = []

class ProjectClientConfig(BaseClientConfig):
    sensors: SensorConfig = SensorConfig()

class ProjectHostConfig(BaseHostConfig):
    storage: StorageConfig = StorageConfig()   # keep existing
    sync: SyncConfig = SyncConfig()            # keep existing
    # Add your fields:
    alert_threshold: float = 80.0
```

Add matching sections to `client.toml`:

```toml
[sensors]
poll_interval = 5.0
channels = ["gpio4", "i2c1"]
```

### 2. Database Tables

Define your tables in `app/models/tables.py`:

```python
MY_TABLE = (
    "readings",
    """
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_pid TEXT NOT NULL,
    value      REAL NOT NULL,
    timestamp  TEXT NOT NULL
    """,
)

HOST_TABLES = [MY_TABLE]
CLIENT_TABLES = []
```

### 3. Data Models

Define Pydantic models for your payloads in `app/models/messages.py`:

```python
from pydantic import BaseModel

class SensorReading(BaseModel):
    value: float
    unit: str = "celsius"
    timestamp: str
```

### 4. Client Runtime

Add your data-collection logic to `app/client/runtime.py`:

```python
async def run(self) -> None:
    await self._store.start()
    self._host_tracker.on_state_change(self._on_host_state_change)
    self._mqtt.on(self._topics.host_status(), self._on_host_heartbeat)
    self._mqtt.on(self._topics.host_command(), self._on_command)
    await self._mqtt.start()
    try:
        await asyncio.gather(
            self._heartbeat.run(),
            self._host_tracker.run(),
            self._sensor_loop(),       # your task
        )
    finally:
        ...

async def _sensor_loop(self) -> None:
    while True:
        value = read_sensor()
        envelope = build_envelope(
            sender=self.pid,
            msg_type="sensor_data",
            payload={"value": value, "timestamp": utcnow()},
        )
        await self._mqtt.publish(self._topics.client_data(self.pid), envelope)
        await asyncio.sleep(self._config.sensors.poll_interval)
```

### 5. Host Runtime

Handle incoming data in `app/host/runtime.py`:

```python
async def _on_client_data(self, topic: str, payload: dict) -> None:
    sender   = payload.get("sender", "unknown")
    msg_type = payload.get("msg_type", "unknown")
    data     = payload.get("payload", {})

    if msg_type == "sensor_data":
        reading = SensorReading(**data)
        await self._store.insert_reading(sender, reading)
```

Add periodic loops and extra tasks to the `tasks` list in `run()`:

```python
tasks.append(self._alert_loop())
```

### 6. Database Stores

Write typed database methods in `app/host/store.py`:

```python
class HostStore:
    async def insert_reading(self, pid: str, reading: SensorReading):
        await self._db.insert("readings", {
            "client_pid": pid,
            "value": reading.value,
            "timestamp": reading.timestamp,
        })

    async def get_recent(self, limit: int = 100) -> list[dict]:
        return await self._db.fetch_all(
            "SELECT * FROM readings ORDER BY id DESC LIMIT ?", (limit,)
        )
```

### 7. API Endpoints

Add your routes in `app/api/routes.py`:

```python
from fastapi import APIRouter
router = APIRouter(prefix="/api/project", tags=["project"])

_store = None

def init_project_routes(store, registry, mqtt, topics):
    global _store
    _store = store

@router.get("/readings")
async def get_readings():
    return await _store.get_recent(100)
```

Include the router in `HostRuntime._setup_api()` (already done by the template):

```python
init_project_routes(self._store, self._registry, self._mqtt, self._topics)
self._api.app.include_router(project_router)
```

### 8. Dashboard

The dashboard at `base/api/static/index.html` is a single self-contained HTML file (no build tools). Edit it directly or replace the `FileResponse` in `HostRuntime._setup_api()` to serve your own file.

Add stat cards, tables, and data fetches in the clearly marked `PROJECT-SPECIFIC` comment blocks within the HTML.

**Auto-refresh pattern:**

```javascript
async function refreshMyData() {
    const data = await api('/api/project/readings');
    document.getElementById('my-table').innerHTML =
        data.map(r => `<tr><td>${r.value}</td><td>${r.timestamp}</td></tr>`).join('');
}

// Add to the refresh loop:
async function refresh() {
    await Promise.all([refreshStats(), refreshStatus(), refreshMyData()]);
}
```

---

## Base Modules Reference

| Module | Key Export | Purpose |
|--------|-----------|---------|
| `base.config` | `load_config`, `save_config` | Load/save TOML configs into Pydantic models |
| `base.comms` | `MQTTClient`, `TopicManager`, `HeartbeatLoop`, `build_envelope` | All MQTT functionality |
| `base.host` | `PeerRegistry`, `PeerState` | Track multiple client connection states |
| `base.client` | `HostTracker` | Track single host connection state |
| `base.db` | `Database` | Async SQLite with WAL, upsert, prune |
| `base.api` | `APIServer`, `base_router`, `init_base_routes` | FastAPI + Uvicorn lifecycle |
| `base.service.remote` | `RemoteClient` | SSH management of remote Pis |
| `base.service.systemd` | `install_service`, `uninstall_service` | Systemd unit management |

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pydantic` | ≥2.0 | Config validation and data models |
| `paho-mqtt` | ≥2.0 | MQTT client |
| `aiosqlite` | ≥0.20 | Async SQLite |
| `fastapi` | ≥0.115 | Web API framework |
| `uvicorn[standard]` | ≥0.30 | ASGI server for FastAPI |
| `paramiko` | ≥3.0 | SSH client for remote Pi management |
| `tomli` | ≥2.0 | TOML parser (Python <3.11 only; built-in as `tomllib` on 3.11+) |
| `tomli-w` | ≥1.0 | TOML writer (for saving config changes to disk) |

Python ≥3.13 required. Dev dependencies (`pytest`, `pytest-asyncio`) installable with `pip install -e ".[dev]"`.
