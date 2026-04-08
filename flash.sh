#!/usr/bin/env bash
# flash.sh — Identify, configure, and flash all connected ESP32 boards.
#
# Run on the Pi. Steps performed automatically:
#   1. Detect connected USB serial devices (ttyUSB* / ttyACM*)
#   2. Set up /dev/esp_port_N udev symlinks if not already present
#   3. Flash firmware to all boards (or specific ports if passed as arguments)
#
# Usage:
#   sudo ./flash.sh                     # detect, udev setup if needed, flash all
#   sudo ./flash.sh /dev/ttyUSB0        # flash a specific port directly
#
# Firmware binaries are read from ./esp/ (produced by build.sh):
#   esp/firmware.bin
#   esp/bootloader.bin        (optional)
#   esp/partition-table.bin   (optional)
#
# Baud rate override:  FLASH_BAUD=921600 sudo ./flash.sh

set -e
cd "$(dirname "$0")"

BAUD="${FLASH_BAUD:-460800}"
ESP_DIR="./esp"

# ════════════════════════════════════════════════════════════════════════════ #
#  STEP 1 — Identify connected boards
# ════════════════════════════════════════════════════════════════════════════ #

vid_name() {
    case "$1" in
        10c4) echo "Silicon Labs CP210x" ;;
        1a86) echo "QinHeng CH340" ;;
        0403) echo "FTDI" ;;
        303a) echo "Espressif native USB" ;;
        *)    echo "" ;;
    esac
}

echo ""
echo "[flash] ── Step 1: Identifying connected ESP boards ───────────────────"

# Collect all ttyUSB/ttyACM devices.
RAW_DEVS=()
for tty_path in /sys/class/tty/ttyUSB* /sys/class/tty/ttyACM*; do
    [ -e "$tty_path" ] || continue
    RAW_DEVS+=("$(basename "$tty_path")")
done

if [ "${#RAW_DEVS[@]}" -eq 0 ]; then
    echo "[flash] No USB serial devices found (/dev/ttyUSB* or /dev/ttyACM*)."
    echo "[flash] Check that boards are plugged in and the driver is loaded:"
    echo "[flash]   lsmod | grep -E 'cp210x|ch341|ftdi'"
    exit 1
fi

# Resolve VID for each device and collect ESP candidates.
ESP_DEVS=()   # raw device names of confirmed ESP boards

for tty_name in "${RAW_DEVS[@]}"; do
    tty_path="/sys/class/tty/$tty_name"
    vid=""
    product=""

    # Walk up sysfs tree to find idVendor.
    check_dir="$(readlink -f "$tty_path/device" 2>/dev/null)"
    for _ in 1 2 3 4 5; do
        [ -z "$check_dir" ] || [ "$check_dir" = "/" ] && break
        if [ -f "$check_dir/idVendor" ]; then
            vid="$(tr '[:upper:]' '[:lower:]' < "$check_dir/idVendor" | tr -d '[:space:]')"
            [ -f "$check_dir/product" ] && \
                product="$(cat "$check_dir/product" 2>/dev/null | tr -d '\n')"
            break
        fi
        check_dir="$(dirname "$check_dir")"
    done

    # Fall back to lsusb if sysfs walk came up empty.
    if [ -z "$vid" ] && command -v lsusb &>/dev/null; then
        sysfs_dir="$(readlink -f "$tty_path/device" 2>/dev/null)"
        busnum="" devnum=""
        [ -f "$sysfs_dir/../../uevent" ] && \
            busnum="$(grep -i busnum "$sysfs_dir/../../uevent" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')"
        [ -f "$sysfs_dir/../uevent" ] && \
            devnum="$(grep -i devnum "$sysfs_dir/../uevent" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')"
        if [ -n "$busnum" ] && [ -n "$devnum" ]; then
            lsusb_line="$(lsusb 2>/dev/null | awk -v b="$busnum" -v d="$devnum" \
                '{ gsub(/^0+/,"",$2); gsub(/^0+/,"",$4); sub(/:$/,"",$4);
                   if ($2==b && $4==d) print }')"
            if [ -n "$lsusb_line" ]; then
                vid="$(echo "$lsusb_line" | grep -oE '[0-9a-f]{4}:[0-9a-f]{4}' | cut -d: -f1)"
                product="$(echo "$lsusb_line" | sed 's/.*ID [^ ]* //')"
            fi
        fi
    fi

    chip="$(vid_name "$vid")"
    if [ -n "$chip" ]; then
        echo "[flash]   /dev/$tty_name — $chip (VID: $vid)${product:+, $product}"
        ESP_DEVS+=("$tty_name")
    else
        echo "[flash]   /dev/$tty_name — skipped (VID: ${vid:-unknown}, not a known ESP chip)"
    fi
done

if [ "${#ESP_DEVS[@]}" -eq 0 ]; then
    echo "[flash] No recognised ESP32 boards found. Check VIDs or force a port:"
    echo "[flash]   sudo ./flash.sh /dev/ttyUSB0"
    exit 1
fi

echo "[flash] ${#ESP_DEVS[@]} ESP board(s) detected."

# ════════════════════════════════════════════════════════════════════════════ #
#  STEP 2 — Ensure udev symlinks exist
# ════════════════════════════════════════════════════════════════════════════ #

echo ""
echo "[flash] ── Step 2: Checking udev symlinks ─────────────────────────────"

UDEV_RULE="/etc/udev/rules.d/99-esp-boards.rules"
NEEDS_UDEV=false

for tty_name in "${ESP_DEVS[@]}"; do
    dev_node="/dev/$tty_name"
    symlink_found=false
    for link in /dev/esp_port_*; do
        [ -e "$link" ] || continue
        if [ "$(readlink -f "$link" 2>/dev/null)" = "$dev_node" ]; then
            symlink_found=true
            echo "[flash]   $dev_node → $(basename "$link") (already set)"
            break
        fi
    done
    $symlink_found || NEEDS_UDEV=true
done

if $NEEDS_UDEV; then
    echo "[flash] One or more boards lack esp_port symlinks — writing udev rules..."

    UDEV_RULE_FILE="/etc/udev/rules.d/99-esp-boards.rules"
    rule_lines=(
        "# ESP32 board stable port naming."
        "# Generated by flash.sh — do not edit manually."
        "# Reload with: sudo udevadm control --reload-rules && sudo udevadm trigger"
        ""
    )

    idx=0
    for tty_name in "${ESP_DEVS[@]}"; do
        # Resolve the full sysfs path and extract the unique USB interface
        # component (e.g. "1-1.2:1.0"). This is stable per physical socket
        # and unique even when multiple boards share the same hub devpath.
        sysfs_full="$(readlink -f "/sys/class/tty/$tty_name" 2>/dev/null)"
        kernels="$(echo "$sysfs_full" | grep -oE '[0-9]+-[0-9.]+(:[0-9]+\.[0-9]+)?' | tail -1)"

        if [ -z "$kernels" ]; then
            echo "[flash] WARNING: could not determine sysfs path for /dev/$tty_name — skipping rule."
            idx=$(( idx + 1 ))
            continue
        fi

        symlink="esp_port_$idx"
        rule_lines+=("SUBSYSTEM==\"tty\", KERNELS==\"$kernels\", SYMLINK+=\"$symlink\"")
        rule_lines+=("# KERNELS path: $kernels  →  /dev/$symlink  (/dev/$tty_name)")
        rule_lines+=("")
        echo "[flash]   /dev/$tty_name (KERNELS: $kernels) → /dev/$symlink"
        idx=$(( idx + 1 ))
    done

    # Write the rules file.
    printf '%s\n' "${rule_lines[@]}" > "$UDEV_RULE_FILE"

    # Reload udev and trigger so symlinks appear immediately.
    udevadm control --reload-rules
    udevadm trigger
    sleep 1   # give udev a moment to create the symlinks

    echo "[flash] udev rules installed and reloaded."
else
    echo "[flash] All symlinks already in place."
fi

# ════════════════════════════════════════════════════════════════════════════ #
#  STEP 3 — Flash firmware
# ════════════════════════════════════════════════════════════════════════════ #

echo ""
echo "[flash] ── Step 3: Flashing firmware ─────────────────────────────────"

# Locate firmware binaries.
FW="$ESP_DIR/firmware.bin"
BL="$ESP_DIR/bootloader.bin"
PT="$ESP_DIR/partition-table.bin"

if [ ! -f "$FW" ]; then
    echo "[flash] ERROR: $FW not found. Run ./build.sh first."
    exit 1
fi

# Resolve flash addresses from flasher_args.json or use ESP32-S3 defaults.
# ESP32-S3 bootloader lives at 0x0 (not 0x1000 like classic ESP32).
FLASHER_ARGS="$ESP_DIR/build/flasher_args.json"
if [ -f "$FLASHER_ARGS" ] && command -v python3 &>/dev/null; then
    ADDR_BL=$(python3 -c "
import json, sys
d = json.load(open('$FLASHER_ARGS'))
[print(a) or sys.exit(0) for a,p in d.get('flash_files',{}).items() if 'bootloader' in p]
print('0x0')")
    ADDR_PT=$(python3 -c "
import json, sys
d = json.load(open('$FLASHER_ARGS'))
[print(a) or sys.exit(0) for a,p in d.get('flash_files',{}).items() if 'partition' in p]
print('0x8000')")
    ADDR_FW=$(python3 -c "
import json, sys
d = json.load(open('$FLASHER_ARGS'))
[print(a) or sys.exit(0) for a,p in d.get('flash_files',{}).items()
 if p.endswith('.bin') and 'bootloader' not in p and 'partition' not in p]
print('0x10000')")
else
    ADDR_BL="0x0"
    ADDR_PT="0x8000"
    ADDR_FW="0x10000"
fi

# ── Resolve esptool command ── #
# Try esptool.py, then python3 -m esptool, then install and retry.
ESPTOOL=""
if command -v esptool.py &>/dev/null; then
    ESPTOOL="esptool.py"
elif python3 -m esptool version &>/dev/null 2>&1; then
    ESPTOOL="python3 -m esptool"
else
    echo "[flash] esptool not found — installing via pip..."
    pip3 install esptool --break-system-packages 2>/dev/null || pip3 install esptool
    if command -v esptool.py &>/dev/null; then
        ESPTOOL="esptool.py"
    elif python3 -m esptool version &>/dev/null 2>&1; then
        ESPTOOL="python3 -m esptool"
    else
        echo "[flash] ERROR: could not install esptool. Install manually:"
        echo "[flash]   pip3 install esptool"
        exit 1
    fi
fi
echo "[flash] Using: $ESPTOOL"

echo "[flash] Addresses: bootloader=$ADDR_BL  partition-table=$ADDR_PT  firmware=$ADDR_FW"
echo "[flash] Baud: $BAUD"

# Resolve ports: use arguments if given, otherwise resolve esp_port symlinks.
if [ "$#" -gt 0 ]; then
    PORTS=("$@")
else
    PORTS=()
    for p in /dev/esp_port_*; do
        [ -e "$p" ] && PORTS+=("$p")
    done
    # Fall back to raw ttyUSB/ACM devices if symlinks still aren't present.
    if [ "${#PORTS[@]}" -eq 0 ]; then
        for tty_name in "${ESP_DEVS[@]}"; do
            PORTS+=("/dev/$tty_name")
        done
    fi
fi

echo "[flash] Flashing ${#PORTS[@]} board(s): ${PORTS[*]}"

FAILED=()
for PORT in "${PORTS[@]}"; do
    echo ""
    echo "[flash] ── $PORT ──────────────────────────────────────────────────"

    FLASH_CMD=(
        $ESPTOOL
        --chip  auto
        --port  "$PORT"
        --baud  "$BAUD"
        write-flash
        --flash-mode  dio
        --flash-freq  40m
        --flash-size  detect
    )
    [ -f "$BL" ] && FLASH_CMD+=("$ADDR_BL" "$BL")
    [ -f "$PT" ] && FLASH_CMD+=("$ADDR_PT" "$PT")
    FLASH_CMD+=("$ADDR_FW" "$FW")

    if "${FLASH_CMD[@]}"; then
        echo "[flash] $PORT — OK"
    else
        echo "[flash] $PORT — FAILED"
        FAILED+=("$PORT")
    fi
done

echo ""
if [ "${#FAILED[@]}" -gt 0 ]; then
    echo "[flash] FAILED: ${FAILED[*]}"
    exit 1
else
    echo "[flash] All boards flashed successfully."
fi
