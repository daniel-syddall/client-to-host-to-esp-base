"""Project database table definitions.

Each table is defined as a (name, schema_string) tuple. These are
passed to Database.create_table() during startup. Keeping them here
makes it easy to see the full data model at a glance.

Example:
    SENSOR_READINGS = (
        "sensor_readings",
        \"""
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sensor_id   TEXT NOT NULL,
        value       REAL NOT NULL,
        unit        TEXT DEFAULT 'celsius',
        timestamp   TEXT NOT NULL
        \""",
    )
"""

# ======================== Host Tables ======================== #

# PROJECT-SPECIFIC: Define your host-side tables here.
# Example:
# MY_TABLE = (
#     "my_table",
#     """
#     id          INTEGER PRIMARY KEY AUTOINCREMENT,
#     name        TEXT NOT NULL,
#     value       REAL DEFAULT 0,
#     timestamp   TEXT NOT NULL
#     """,
# )

# List all host tables here. Used by HostStore.start() to auto-create them.
HOST_TABLES = []


# ======================== Client Tables ======================== #

# PROJECT-SPECIFIC: Define your client-side tables here (if needed).
# Client DB is optional and disabled by default.

CLIENT_TABLES = []
