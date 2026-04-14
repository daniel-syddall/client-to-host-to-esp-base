/**
 * ESP32 Firmware Template
 *
 * Implements the Pi↔ESP serial protocol:
 *   - Binary frames: [0xAA][0x55][length:uint16LE][payload]
 *   - JSON lines:    newline-terminated JSON for control messages
 *
 * Boot sequence (Pi-initiated):
 *   1. Pi sends: {"type":"init","board_id":<n>}\n
 *   2. ESP replies: {"type":"ack","board_id":<n>}\n
 *   3. Pi sends: {"type":"start"}\n
 *   4. ESP enters the main run loop.
 *
 * PROJECT-SPECIFIC: Implement your data acquisition in data_task().
 * The helper send_data_frame() sends a binary payload to the Pi.
 * Use read_ccount() for nanosecond-precision timestamps.
 */

#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "sdkconfig.h"

/* ── Configuration ────────────────────────────────────────────────────────── */

#define UART_PORT       UART_NUM_1      /* UART1, routed to GPIO43/44 via GPIO matrix    */
#define UART_TX_PIN     43              /* GPIO43 = physical CH340 RX line (board TX)    */
#define UART_RX_PIN     44              /* GPIO44 = physical CH340 TX line (board RX)    */
/* Why UART1 and not UART0?
 * The ESP-IDF console subsystem installs its own driver on UART0 before
 * app_main() runs.  Calling uart_driver_install(UART_NUM_0) then panics
 * with ESP_ERR_INVALID_STATE.  UART1 is unused by IDF, so the install
 * succeeds cleanly.  gpio_func_sel() in uart_set_pin() switches GPIO43/44
 * from the UART0 IOMUX path to the GPIO-matrix path for UART1, giving
 * UART1 exclusive ownership of the physical lines. */
#define UART_BAUD       921600          /* Must match ESPPortConfig.baud_rate  */
#define UART_BUF_SIZE   4096

#define FRAME_MAGIC_1   0xAA
#define FRAME_MAGIC_2   0x55

#define JSON_BUF_SIZE   256
#define DATA_BUF_SIZE   1024

/* LED1 — green status LED on GPIO38.
 * Circuit: 3.3V → R13 → Anode → LED → Cathode → GPIO38  (active-low).
 * Pull GPIO38 LOW to turn the LED on; HIGH to turn it off.
 *
 * State machine (driven by led_task):
 *   LED_STATE_BLINK — 1 Hz blink while connecting, reconnecting, or running.
 *   LED_STATE_OFF   — solid off when disconnected, crashed, or stopped.       */
#define LED_GPIO              38
#define LED_ON                0               /* active-low: sink cathode to GND  */
#define LED_OFF               1
#define DISCONNECT_TIMEOUT_MS 15000           /* watchdog: LED off after 15 s with no Pi command */

static const char *TAG = "esp_fw";

/* ── Board identity (filled in by handshake) ─────────────────────────────── */

static int           g_board_id = -1;
static volatile bool g_running  = false;  /* written by app_main/Core 0, read by data_task/Core 1 */

/* ── LED state machine globals ────────────────────────────────────────────── */

typedef enum { LED_STATE_OFF, LED_STATE_BLINK } led_state_t;

static volatile led_state_t g_led_state     = LED_STATE_BLINK; /* blink from boot (connecting) */
static volatile TickType_t  g_last_cmd_tick = 0;               /* updated on every Pi command  */

/* ── Nanosecond timer ─────────────────────────────────────────────────────── */

/**
 * read_ccount - Read the Xtensa CCOUNT register.
 *
 * CCOUNT increments at the CPU clock frequency (typically 240 MHz on ESP32).
 * Divide by CPU_FREQ_HZ to convert to seconds, or multiply the result of
 * (ccount / CPU_FREQ_HZ) * 1e9 to get nanoseconds.
 *
 * For nanosecond-resolution timestamps, the Pi sends its current time_ns in
 * the clock_sync command; you then add the local elapsed CCOUNT ticks to
 * that base to derive an absolute nanosecond timestamp for every capture.
 *
 * PROJECT-SPECIFIC: Store t_sync_ns and ccount_at_sync when you receive
 * clock_sync, then use:
 *     ts_ns = t_sync_ns + (uint64_t)((read_ccount() - ccount_at_sync)
 *             * (1e9 / CPU_FREQ_HZ));
 */
static inline uint32_t read_ccount(void) {
    uint32_t ccount;
    asm volatile("rsr %0, ccount" : "=r"(ccount));
    return ccount;
}

/* ── Frame builders ────────────────────────────────────────────────────────── */

/**
 * send_data_frame - Send a binary data frame to the Pi.
 *
 * Frame layout:  [0xAA][0x55][len_lo][len_hi][payload...]
 *
 * @param payload  Pointer to the binary payload bytes.
 * @param length   Number of payload bytes.
 */
static void send_data_frame(const uint8_t *payload, size_t length) {
    uint8_t header[4];
    header[0] = FRAME_MAGIC_1;
    header[1] = FRAME_MAGIC_2;
    header[2] = (uint8_t)(length & 0xFF);
    header[3] = (uint8_t)((length >> 8) & 0xFF);
    uart_write_bytes(UART_PORT, (const char *)header, 4);
    uart_write_bytes(UART_PORT, (const char *)payload, length);
}

/**
 * send_json - Send a JSON control line to the Pi.
 *
 * @param json  Null-terminated JSON string (no trailing newline needed).
 */
static void send_json(const char *json) {
    uart_write_bytes(UART_PORT, json, strlen(json));
    uart_write_bytes(UART_PORT, "\n", 1);
}

/* ── JSON line reader ─────────────────────────────────────────────────────── */

/**
 * read_json_line - Block until a complete '\n'-terminated line is received.
 *
 * @param buf   Output buffer.
 * @param size  Size of buf (including space for the null terminator).
 * @return      Number of bytes read (not including '\n'), or -1 on overflow.
 */
static int read_json_line(char *buf, size_t size) {
    size_t pos = 0;
    while (pos < size - 1) {
        uint8_t b;
        int n = uart_read_bytes(UART_PORT, &b, 1, portMAX_DELAY);
        if (n <= 0) continue;
        if (b == '\n') {
            buf[pos] = '\0';
            return (int)pos;
        }
        buf[pos++] = (char)b;
    }
    buf[size - 1] = '\0';
    return -1;  /* overflow */
}

/* ── Handshake ────────────────────────────────────────────────────────────── */

/**
 * run_handshake - Wait for the Pi INIT, reply ACK, wait for START.
 *
 * Blocks indefinitely until the full handshake completes.
 * Sets g_board_id on success.
 */
static void run_handshake(void) {
    char line[JSON_BUF_SIZE];
    int  board_id = -1;

    ESP_LOGI(TAG, "Waiting for INIT from Pi...");

    /* Step 1 — wait for {"type":"init","board_id":<n>} */
    while (true) {
        if (read_json_line(line, sizeof(line)) < 0) continue;
        ESP_LOGD(TAG, "RX: %s", line);

        /* Minimal parse — look for "init" and extract id.
         * Pi sends: {"type":"init","id":<n>}               */
        if (strstr(line, "\"init\"") == NULL) continue;

        char *p = strstr(line, "\"id\"");
        if (!p) continue;
        p = strchr(p, ':');
        if (!p) continue;
        board_id = (int)strtol(p + 1, NULL, 10);
        break;
    }

    g_board_id = board_id;
    ESP_LOGI(TAG, "INIT received — board_id=%d", g_board_id);

    /* Step 2 — reply ACK — field name "id" matches what Pi expects */
    char ack[JSON_BUF_SIZE];
    snprintf(ack, sizeof(ack), "{\"type\":\"ack\",\"id\":%d}", g_board_id);
    send_json(ack);
    ESP_LOGI(TAG, "ACK sent");

    /* Step 3 — wait for {"type":"start"} */
    while (true) {
        if (read_json_line(line, sizeof(line)) < 0) continue;
        ESP_LOGD(TAG, "RX: %s", line);
        if (strstr(line, "\"start\"") != NULL) break;
    }

    ESP_LOGI(TAG, "START received — entering run loop");
    g_last_cmd_tick = xTaskGetTickCount();  /* seed watchdog so data_task doesn't immediately time out */
    g_running = true;
}

/* ── Command handler ──────────────────────────────────────────────────────── */

/* Clock sync state — populated by handle_command() when a clock_sync arrives.
 * Use these to compute nanosecond-accurate timestamps in data_task().       */
static uint64_t g_sync_ts_ns  = 0;          /* Pi's time_ns at last sync     */
static uint32_t g_sync_ccount = 0;          /* CCOUNT value at last sync     */
static uint32_t g_cpu_freq_hz = 240000000;  /* 240 MHz default for ESP32     */

/**
 * handle_command - Process a JSON control line received while running.
 *
 * @param line  Null-terminated JSON string.
 */
static void handle_command(const char *line) {
    ESP_LOGD(TAG, "CMD: %s", line);

    /* Any message from the Pi means the connection is alive — refresh watchdog. */
    g_last_cmd_tick = xTaskGetTickCount();

    if (strstr(line, "\"init\"") != NULL) {
        /* Pi reconnected without a hardware reset — re-run the handshake in-place.
         *
         * This happens when the client process restarts but the board was not
         * power-cycled.  The board is still in the control_task/data_task loop,
         * so run_handshake() is never called again by app_main().  We handle it
         * here instead:
         *   1. Pause data_task by clearing g_running.
         *   2. Set LED to blink (reconnecting state).
         *   3. Reply ACK so the Pi knows we received the INIT.
         *   4. Wait for START from within this same task context (control_task is
         *      the sole UART reader, so calling read_json_line here is safe).
         *   5. Resume data_task by setting g_running.                            */
        g_running   = false;            /* data_task sees this within one 100ms tick  */
        g_led_state = LED_STATE_BLINK;  /* blink while reconnecting                  */

        char *p = strstr(line, "\"id\"");
        if (p) {
            p = strchr(p, ':');
            if (p) g_board_id = (int)strtol(p + 1, NULL, 10);
        }

        ESP_LOGI(TAG, "Re-handshake: INIT received (id=%d)", g_board_id);
        char ack[JSON_BUF_SIZE];
        snprintf(ack, sizeof(ack), "{\"type\":\"ack\",\"id\":%d}", g_board_id);
        send_json(ack);
        ESP_LOGI(TAG, "Re-handshake: ACK sent");

        char buf[JSON_BUF_SIZE];
        while (true) {
            if (read_json_line(buf, sizeof(buf)) < 0) continue;
            if (strstr(buf, "\"start\"") != NULL) break;
            /* Pi timed out waiting for ACK and re-sent INIT.
             * Re-ACK so the Pi can proceed to START.          */
            if (strstr(buf, "\"init\"") != NULL) {
                char *p2 = strstr(buf, "\"id\"");
                if (p2) { p2 = strchr(p2, ':'); if (p2) g_board_id = (int)strtol(p2 + 1, NULL, 10); }
                snprintf(ack, sizeof(ack), "{\"type\":\"ack\",\"id\":%d}", g_board_id);
                send_json(ack);
                ESP_LOGI(TAG, "Re-handshake: re-ACK sent (second INIT received)");
            }
        }

        g_last_cmd_tick = xTaskGetTickCount();  /* seed watchdog for fresh session */
        g_running = true;
        ESP_LOGI(TAG, "Re-handshake: START received — resuming");

    } else if (strstr(line, "\"status\"") != NULL) {
        /* Pi is polling for a status report. */
        char resp[JSON_BUF_SIZE];
        snprintf(resp, sizeof(resp),
                 "{\"type\":\"status\",\"id\":%d,\"running\":true}",
                 g_board_id);
        send_json(resp);

    } else if (strstr(line, "\"clock_sync\"") != NULL) {
        /* Pi is syncing its nanosecond clock to this board.
         * Extract "ts" field (uint64 as a JSON number).          */
        char *p = strstr(line, "\"ts\"");
        if (p) {
            p = strchr(p, ':');
            if (p) {
                g_sync_ts_ns  = (uint64_t)strtoull(p + 1, NULL, 10);
                g_sync_ccount = read_ccount();
                ESP_LOGI(TAG, "Clock sync: ts_ns=%llu", (unsigned long long)g_sync_ts_ns);
            }
        }

    }

    /* PROJECT-SPECIFIC: Add your own command handlers here, e.g.:
     *
     *   else if (strstr(line, "\"start_scan\"") != NULL) {
     *       g_scanning = true;
     *   }
     */
}

/* ── Control task ─────────────────────────────────────────────────────────── */

/**
 * control_task - Reads JSON lines from the Pi and dispatches to handle_command.
 *
 * Runs as a FreeRTOS task on Core 0.
 */
static void control_task(void *arg) {
    char line[JSON_BUF_SIZE];
    while (true) {
        int n = read_json_line(line, sizeof(line));
        if (n > 0) {
            handle_command(line);
        }
    }
}

/* ── Data task ────────────────────────────────────────────────────────────── */

/**
 * data_task - Acquires data and sends binary frames to the Pi.
 *
 * Runs as a FreeRTOS task on Core 1.
 *
 * Baseplate test behaviour: sends a monotonically-incrementing 4-byte
 * sequence number every 100 ms so you can verify the full Pi↔ESP pipeline
 * (handshake, data flow, on_data callback) before writing project logic.
 *
 * On the Pi side, ESPManager.on_data() will receive:
 *   board_id  — session ID assigned during handshake
 *   payload   — 4 bytes, big-endian uint32 sequence number
 *
 * Verify with:
 *   seq = int.from_bytes(payload[:4], "big")
 *   print(f"board {board_id} seq={seq}")
 *
 * PROJECT-SPECIFIC: Replace the placeholder block below with your own
 * data acquisition logic.  Use send_data_frame() to push bytes to the Pi.
 *
 * Nanosecond timestamp example (after clock_sync has been received):
 *
 *   uint64_t ts_ns = g_sync_ts_ns + (uint64_t)(
 *       (read_ccount() - g_sync_ccount) * (1e9 / (double)g_cpu_freq_hz));
 *   uint16_t channel = 6;
 *   int16_t  rssi    = -70;
 *
 *   uint8_t buf[12];
 *   memcpy(buf + 0,  &ts_ns,   8);   // little-endian uint64
 *   memcpy(buf + 8,  &channel, 2);   // little-endian uint16
 *   memcpy(buf + 10, &rssi,    2);   // little-endian int16
 *   send_data_frame(buf, sizeof(buf));
 */
static void data_task(void *arg) {
    uint8_t buf[DATA_BUF_SIZE];
    uint32_t seq = 0;

    while (true) {
        /* Block until the handshake completes and the Pi sends START. */
        if (!g_running) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        /* Watchdog: if no Pi command has arrived for DISCONNECT_TIMEOUT_MS the
         * connection is considered lost — turn the LED off.  Commands arriving
         * via handle_command() refresh g_last_cmd_tick, which re-enables the LED. */
        TickType_t now = xTaskGetTickCount();
        if ((now - g_last_cmd_tick) > pdMS_TO_TICKS(DISCONNECT_TIMEOUT_MS)) {
            g_led_state = LED_STATE_OFF;
        } else {
            g_led_state = LED_STATE_BLINK;
        }

        /* ── Baseplate test: 4-byte big-endian sequence counter ── */
        seq++;
        buf[0] = (seq >> 24) & 0xFF;
        buf[1] = (seq >> 16) & 0xFF;
        buf[2] = (seq >>  8) & 0xFF;
        buf[3] = (seq >>  0) & 0xFF;
        send_data_frame(buf, 4);
        /* ── PROJECT-SPECIFIC: replace the four lines above ───── */

        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

/* ── LED init & task ──────────────────────────────────────────────────────── */

static void led_init(void) {
    gpio_reset_pin(LED_GPIO);
    gpio_set_direction(LED_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level(LED_GPIO, LED_OFF);
    ESP_LOGI(TAG, "LED1 initialised on GPIO%d (active-low)", LED_GPIO);
}

/**
 * led_task - Drives LED1 according to g_led_state.
 *
 * LED_STATE_BLINK: toggles every 500 ms (1 Hz blink).
 * LED_STATE_OFF:   holds LED off.
 *
 * Runs on Core 0 at lower priority than control/data tasks so it never
 * starves protocol handling.
 */
static void led_task(void *arg) {
    bool led_on = false;
    while (true) {
        if (g_led_state == LED_STATE_BLINK) {
            led_on = !led_on;
            gpio_set_level(LED_GPIO, led_on ? LED_ON : LED_OFF);
        } else {
            led_on = false;
            gpio_set_level(LED_GPIO, LED_OFF);
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

/* ── UART init ────────────────────────────────────────────────────────────── */

static void uart_init(void) {
    uart_config_t cfg = {
        .baud_rate  = UART_BAUD,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
    };
    ESP_ERROR_CHECK(uart_param_config(UART_PORT, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(UART_PORT, UART_TX_PIN, UART_RX_PIN,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_driver_install(UART_PORT, UART_BUF_SIZE, UART_BUF_SIZE,
                                        0, NULL, 0));
    ESP_LOGI(TAG, "UART%d initialised at %d baud (TX=%d RX=%d)",
             UART_PORT, UART_BAUD, UART_TX_PIN, UART_RX_PIN);
}

/* ── Entry point ─────────────────────────────────────────────────────────── */

void app_main(void) {
    ESP_LOGI(TAG, "Firmware starting...");
    led_init();
    uart_init();

    /* LED task must start before run_handshake() so it blinks during the
     * initial connection wait (Core 0, priority 3 — below control/data). */
    xTaskCreatePinnedToCore(led_task,     "led",  1024, NULL, 3, NULL, 0);

    /* Block here until the Pi completes the handshake. */
    run_handshake();

    /* Start the control reader on Core 0. */
    xTaskCreatePinnedToCore(control_task, "ctrl", 4096, NULL, 5, NULL, 0);

    /* Start the data producer on Core 1. */
    xTaskCreatePinnedToCore(data_task,    "data", 4096, NULL, 5, NULL, 1);

    /* app_main returns — the scheduler keeps the tasks alive. */
}
