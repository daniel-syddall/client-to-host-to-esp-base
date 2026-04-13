#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

OS="$(uname -s)"

# ── Docker install ────────────────────────────────────────────────────────── #

if ! command -v docker &>/dev/null; then
    echo "[build] Docker not found — installing..."

    case "$OS" in
        Linux*)
            curl -fsSL https://get.docker.com | sh
            systemctl enable --now docker
            if [ -n "$SUDO_USER" ] && ! groups "$SUDO_USER" | grep -q docker; then
                usermod -aG docker "$SUDO_USER"
                echo "[build] NOTE: Log out and back in (or run 'newgrp docker') before using Docker without sudo."
            fi
            ;;
        Darwin*)
            if command -v brew &>/dev/null; then
                brew install --cask docker
                echo "[build] Docker Desktop installed. Open it from Applications, wait for it to start, then re-run this script."
            else
                echo "[build] Please install Docker Desktop from https://www.docker.com/products/docker-desktop/"
            fi
            exit 0
            ;;
        MINGW*|CYGWIN*|MSYS*)
            echo "[build] Please install Docker Desktop for Windows from https://www.docker.com/products/docker-desktop/"
            echo "[build] Once installed and running, re-run this script."
            exit 0
            ;;
        *)
            echo "[build] Unsupported OS: $OS. Install Docker manually then re-run."
            exit 1
            ;;
    esac
else
    echo "[build] Docker already installed."
fi

# ── Ensure Docker daemon is reachable ────────────────────────────────────── #

if ! docker info &>/dev/null; then
    case "$OS" in
        Linux*)
            echo "[build] Starting Docker service..."
            systemctl start docker
            ;;
        Darwin*)
            echo "[build] Docker Desktop is not running. Open it, wait for it to start, then re-run this script."
            exit 1
            ;;
        *)
            echo "[build] Docker daemon not reachable. Start Docker Desktop then re-run this script."
            exit 1
            ;;
    esac
fi

# ── Pull base images ──────────────────────────────────────────────────────── #

echo "[build] Pulling base images..."
docker compose pull mosquitto

# ── Build project image ───────────────────────────────────────────────────── #

echo "[build] Building project image..."
if docker image inspect python:3.13-slim &>/dev/null; then
    echo "[build] Base image cached — building without pulling."
    docker compose build --pull=never
else
    docker compose build
fi

# ── ESP firmware build ────────────────────────────────────────────────────── #
#
# Looks for a single .c file in esp/ (e.g. main.c written by the project).
# Copies it into esp/main/main.c, then compiles via the official
# espressif/idf Docker image and copies the flat binaries back to esp/.
#
# Skip this section by setting SKIP_ESP=1:
#   SKIP_ESP=1 ./build.sh

if [ "${SKIP_ESP:-0}" != "1" ]; then
    ESP_DIR="$(pwd)/esp"

    # Locate exactly one project .c file in esp/ (not in subdirectories).
    C_FILES=("$ESP_DIR"/*.c)
    if [ "${#C_FILES[@]}" -eq 0 ] || [ ! -f "${C_FILES[0]}" ]; then
        echo "[build] No .c firmware file found in esp/ — skipping ESP build."
    else
        C_SRC="${C_FILES[0]}"
        echo "[build] ESP firmware source: $(basename "$C_SRC")"

        # Stage into esp/main/main.c (required by ESP-IDF component layout).
        cp "$C_SRC" "$ESP_DIR/main/main.c"

        # Pull the ESP-IDF image if not already cached.
        IDF_IMAGE="espressif/idf:latest"
        if ! docker image inspect "$IDF_IMAGE" &>/dev/null; then
            echo "[build] Pulling $IDF_IMAGE (first run, may take a few minutes)..."
            docker pull "$IDF_IMAGE"
        fi

        echo "[build] Compiling ESP firmware (target=esp32s3)..."
        docker run --rm \
            -v "$ESP_DIR":/project \
            -w /project \
            "$IDF_IMAGE" \
            bash -c "idf.py set-target esp32s3 && idf.py build"

        # Copy the flat binaries up to esp/ so flash.sh can find them.
        BUILD_DIR="$ESP_DIR/build"
        for BIN in firmware.bin bootloader/bootloader.bin \
                   partition_table/partition-table.bin; do
            SRC="$BUILD_DIR/$BIN"
            DST="$ESP_DIR/$(basename "$BIN")"
            if [ -f "$SRC" ]; then
                cp "$SRC" "$DST"
                echo "[build] Copied $(basename "$BIN") → esp/"
            fi
        done

        echo "[build] ESP firmware build complete."
    fi
else
    echo "[build] SKIP_ESP=1 — skipping ESP firmware build."
fi

echo ""
echo "[build] Done. Run ./host.sh or ./client.sh to start."
