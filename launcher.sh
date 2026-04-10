#!/bin/bash
#
# ComfyUI Launcher
#
# Usage: chmod +x launcher.sh && ./launcher.sh
#

echo -e "\033]0;ComfyUI Launcher\007"

# ─── Colors ───────────────────────────────────────────────────────────────────

reset="\033[0m"
red_fg_strong="\033[91m"
green_fg_strong="\033[92m"
yellow_fg_strong="\033[93m"
blue_fg_strong="\033[94m"
cyan_fg_strong="\033[96m"
red_bg="\033[41m"
blue_bg="\033[44m"
yellow_bg="\033[43m"
green_bg="\033[42m"

# ─── Paths ────────────────────────────────────────────────────────────────────

launcher_root="$(dirname "$(realpath "$0")")"
comfyui_path="$launcher_root/ComfyUI"
venv_path="$comfyui_path/venv"
settings_dir="$launcher_root/bin/settings"
settings_file="$settings_dir/comfyui_settings.txt"

# ─── Default settings ─────────────────────────────────────────────────────────

export listen_trigger="false"
export port_trigger="false"
export port="8188"
export cpu_trigger="false"
export lowvram_trigger="false"
export medvram_trigger="false"
export highvram_trigger="false"
export fp16_vae_trigger="false"
export fp32_vae_trigger="false"
export bf16_unet_trigger="false"
export fp8_unet_trigger="false"
export preview_method="auto"

if [ -f "$settings_file" ]; then
    while IFS='=' read -r key value; do
        export "$key"="$value"
    done < "$settings_file"
fi

# ─── Helpers ──────────────────────────────────────────────────────────────────

log_message() {
    local time
    time=$(date +'%H:%M:%S')
    case "$1" in
        "INFO")  echo -e "${blue_bg}[$time]${reset} ${blue_fg_strong}[INFO]${reset} $2" ;;
        "WARN")  echo -e "${yellow_bg}[$time]${reset} ${yellow_fg_strong}[WARN]${reset} $2" ;;
        "ERROR") echo -e "${red_bg}[$time]${reset} ${red_fg_strong}[ERROR]${reset} $2" ;;
        "OK")    echo -e "${green_bg}[$time]${reset} ${green_fg_strong}[OK]${reset} $2" ;;
    esac
}

save_settings() {
    mkdir -p "$settings_dir"
    {
        echo "listen_trigger=$listen_trigger"
        echo "port_trigger=$port_trigger"
        echo "port=$port"
        echo "cpu_trigger=$cpu_trigger"
        echo "lowvram_trigger=$lowvram_trigger"
        echo "medvram_trigger=$medvram_trigger"
        echo "highvram_trigger=$highvram_trigger"
        echo "fp16_vae_trigger=$fp16_vae_trigger"
        echo "fp32_vae_trigger=$fp32_vae_trigger"
        echo "bf16_unet_trigger=$bf16_unet_trigger"
        echo "fp8_unet_trigger=$fp8_unet_trigger"
        echo "preview_method=$preview_method"
    } > "$settings_file"
}

toggle() {
    [ "$1" == "true" ] && echo "false" || echo "true"
}

printOption() {
    if [ "$2" == "true" ]; then
        echo -e "    ${green_fg_strong}$1 [Enabled]${reset}"
    else
        echo -e "    ${red_fg_strong}$1 [Disabled]${reset}"
    fi
}

build_cmd() {
    local cmd="python main.py"
    [ "$listen_trigger"   == "true" ] && cmd+=" --listen"
    [ "$port_trigger"     == "true" ] && cmd+=" --port $port"
    [ "$cpu_trigger"      == "true" ] && cmd+=" --cpu"
    [ "$lowvram_trigger"  == "true" ] && cmd+=" --lowvram"
    [ "$medvram_trigger"  == "true" ] && cmd+=" --medvram"
    [ "$highvram_trigger" == "true" ] && cmd+=" --highvram"
    [ "$fp16_vae_trigger" == "true" ] && cmd+=" --fp16-vae"
    [ "$fp32_vae_trigger" == "true" ] && cmd+=" --fp32-vae"
    [ "$bf16_unet_trigger" == "true" ] && cmd+=" --bf16-unet"
    [ "$fp8_unet_trigger" == "true"  ] && cmd+=" --fp8_e4m3fn-unet"
    [ "$preview_method"   != "auto"  ] && cmd+=" --preview-method $preview_method"
    echo "$cmd"
}

########################################################################################
#####################################  HOME  ###########################################
########################################################################################

home() {
    echo -e "\033]0;ComfyUI Launcher\007"
    clear

    local status
    if [ -d "$comfyui_path" ]; then
        status="${green_fg_strong}Installed${reset}"
    else
        status="${red_fg_strong}Not installed${reset}"
    fi

    echo -e "${blue_fg_strong} ==============================================================${reset}"
    echo -e "${blue_fg_strong}                    ComfyUI Launcher                           ${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"
    echo -e "  Status:  $status"
    echo -e "  Command: ${yellow_fg_strong}$(build_cmd)${reset}"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| What would you like to do?                                   |${reset}"
    echo "    1. Run"
    echo "    2. Config"
    echo "    3. Install / Reinstall"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Menu Options:                                                |${reset}"
    echo "    0. Exit"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}|                                                              |${reset}"
    read -p "  Choose Your Destiny: " choice

    case $choice in
        1) run_comfyui ;;
        2) config ;;
        3) install_comfyui ;;
        0) echo -e "${blue_fg_strong}Goodbye.${reset}"; exit 0 ;;
        *) echo -e "${yellow_fg_strong}WARNING: Invalid number. Please insert a valid number.${reset}"
           read -p "Press Enter to continue..."
           home ;;
    esac
}

########################################################################################
######################################  RUN  ###########################################
########################################################################################

run_comfyui() {
    echo -e "\033]0;ComfyUI Launcher [RUNNING]\007"
    clear
    echo -e "${blue_fg_strong}| > / Home / Run                                               |${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"

    if [ ! -d "$comfyui_path" ]; then
        log_message "ERROR" "${red_fg_strong}ComfyUI is not installed. Run Install first.${reset}"
        read -p "Press Enter to continue..."
        home
        return
    fi

    if [ ! -d "$venv_path" ]; then
        log_message "ERROR" "${red_fg_strong}Virtual environment missing. Try reinstalling.${reset}"
        read -p "Press Enter to continue..."
        home
        return
    fi

    local cmd
    cmd=$(build_cmd)
    log_message "INFO" "Launching: ${cyan_fg_strong}$cmd${reset}"
    log_message "INFO" "URL: ${green_fg_strong}http://127.0.0.1:${port}/${reset}"
    echo ""
    echo -e "  ${yellow_fg_strong}Press Ctrl+C to stop ComfyUI.${reset}"
    echo ""

    cd "$comfyui_path" || { log_message "ERROR" "Cannot cd to $comfyui_path"; read -p "Press Enter to continue..."; home; return; }
    source "$venv_path/bin/activate"
    $cmd
    deactivate

    echo ""
    log_message "INFO" "ComfyUI has exited."
    read -p "Press Enter to return to menu..."
    home
}

########################################################################################
####################################  CONFIG  ##########################################
########################################################################################

config() {
    echo -e "\033]0;ComfyUI Launcher [CONFIG]\007"
    clear
    echo -e "${blue_fg_strong}| > / Home / Config                                            |${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Toggle options — enter numbers separated by spaces           |${reset}"
    echo -e "${cyan_fg_strong}| e.g. \"1 4\" toggles Listen and Low VRAM                     |${reset}"
    echo ""

    echo -e "  ${cyan_fg_strong}── Networking ──────────────────────────────────────────────${reset}"
    printOption "1.  Listen on all interfaces  (--listen)" "$listen_trigger"
    if [ "$port_trigger" == "true" ]; then
        echo -e "    ${green_fg_strong}2.  Port [Enabled: $port]${reset}"
    else
        echo -e "    ${red_fg_strong}2.  Port [Disabled — default: 8188]${reset}"
    fi

    echo ""
    echo -e "  ${cyan_fg_strong}── VRAM ─────────────────────────────────────────────────────${reset}"
    printOption "3.  CPU only    (--cpu)"     "$cpu_trigger"
    printOption "4.  Low VRAM    (--lowvram)" "$lowvram_trigger"
    printOption "5.  Medium VRAM (--medvram)" "$medvram_trigger"
    printOption "6.  High VRAM   (--highvram)" "$highvram_trigger"

    echo ""
    echo -e "  ${cyan_fg_strong}── Precision ───────────────────────────────────────────────${reset}"
    printOption "7.  FP16 VAE         (--fp16-vae)"         "$fp16_vae_trigger"
    printOption "8.  FP32 VAE         (--fp32-vae)"         "$fp32_vae_trigger"
    printOption "9.  BF16 UNet        (--bf16-unet)"        "$bf16_unet_trigger"
    printOption "10. FP8 UNet         (--fp8_e4m3fn-unet)"  "$fp8_unet_trigger"

    echo ""
    echo -e "  ${cyan_fg_strong}── Preview ─────────────────────────────────────────────────${reset}"
    echo -e "    ${cyan_fg_strong}11. Preview method [current: $preview_method]${reset}  (auto / latent2rgb / taesd / none)"

    echo ""
    echo -e "  ${cyan_fg_strong}── Model Paths ─────────────────────────────────────────────${reset}"
    echo    "    12. Edit extra_model_paths.yaml"

    echo ""
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Launch command preview:                                      |${reset}"
    echo -e "  ${yellow_fg_strong}$(build_cmd)${reset}"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Menu Options:                                                |${reset}"
    echo "    0. Back"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}|                                                              |${reset}"
    read -p "  Choose options to toggle: " choices

    for i in $choices; do
        case $i in
            0)  save_settings; home; return ;;

            1)  listen_trigger=$(toggle "$listen_trigger") ;;

            2)  if [ "$port_trigger" == "true" ]; then
                    port_trigger="false"; port="8188"
                else
                    read -p "    Port (1024-65535): " new_port
                    if [[ "$new_port" =~ ^[0-9]+$ ]] && [ "$new_port" -ge 1024 ] && [ "$new_port" -le 65535 ]; then
                        port="$new_port"; port_trigger="true"
                    else
                        log_message "WARN" "Invalid port — must be 1024–65535."
                    fi
                fi ;;

            3)  cpu_trigger=$(toggle "$cpu_trigger") ;;

            4)  if [ "$lowvram_trigger" == "true" ]; then lowvram_trigger="false"
                else lowvram_trigger="true"; medvram_trigger="false"; highvram_trigger="false"; fi ;;

            5)  if [ "$medvram_trigger" == "true" ]; then medvram_trigger="false"
                else medvram_trigger="true"; lowvram_trigger="false"; highvram_trigger="false"; fi ;;

            6)  if [ "$highvram_trigger" == "true" ]; then highvram_trigger="false"
                else highvram_trigger="true"; lowvram_trigger="false"; medvram_trigger="false"; fi ;;

            7)  if [ "$fp16_vae_trigger" == "true" ]; then fp16_vae_trigger="false"
                else fp16_vae_trigger="true"; fp32_vae_trigger="false"; fi ;;

            8)  if [ "$fp32_vae_trigger" == "true" ]; then fp32_vae_trigger="false"
                else fp32_vae_trigger="true"; fp16_vae_trigger="false"; fi ;;

            9)  if [ "$bf16_unet_trigger" == "true" ]; then bf16_unet_trigger="false"
                else bf16_unet_trigger="true"; fp8_unet_trigger="false"; fi ;;

            10) if [ "$fp8_unet_trigger" == "true" ]; then fp8_unet_trigger="false"
                else fp8_unet_trigger="true"; bf16_unet_trigger="false"; fi ;;

            11) echo "    Options: auto  latent2rgb  taesd  none"
                read -p "    Preview method: " new_preview
                case "$new_preview" in
                    auto|latent2rgb|taesd|none) preview_method="$new_preview" ;;
                    *) log_message "WARN" "Invalid — choose: auto, latent2rgb, taesd, none" ;;
                esac ;;

            12) config_model_paths; return ;;

            *) echo -e "${yellow_fg_strong}WARNING: '$i' is not a valid option.${reset}" ;;
        esac
    done

    save_settings
    config
}

config_model_paths() {
    echo -e "\033]0;ComfyUI Launcher [MODEL PATHS]\007"
    clear
    echo -e "${blue_fg_strong}| > / Home / Config / Model Paths                              |${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"

    if [ ! -d "$comfyui_path" ]; then
        log_message "ERROR" "${red_fg_strong}ComfyUI is not installed.${reset}"
        read -p "Press Enter to continue..."
        config
        return
    fi

    local yaml="$comfyui_path/extra_model_paths.yaml"
    local example="$comfyui_path/extra_model_paths.yaml.example"

    if [ ! -f "$yaml" ]; then
        if [ -f "$example" ]; then
            cp "$example" "$yaml"
            log_message "INFO" "Created extra_model_paths.yaml from example."
        else
            cat > "$yaml" <<'EOF'
# ComfyUI extra model paths
# Point ComfyUI at models stored outside the ComfyUI folder.
#
# comfyui:
#     base_path: /path/to/stable-diffusion-webui/
#     checkpoints: models/Stable-diffusion
#     vae: models/VAE
#     loras: models/Lora
#     upscale_models: models/ESRGAN
#     embeddings: embeddings
#     controlnet: models/ControlNet
EOF
            log_message "INFO" "Created blank extra_model_paths.yaml."
        fi
    fi

    if ! command -v nano &>/dev/null; then
        log_message "ERROR" "${red_fg_strong}nano is not installed. Install nano to edit files.${reset}"
        read -p "Press Enter to continue..."
        config
        return
    fi

    nano "$yaml"
    config
}

########################################################################################
###################################  INSTALL  ##########################################
########################################################################################

install_comfyui() {
    echo -e "\033]0;ComfyUI Launcher [INSTALL]\007"
    clear
    echo -e "${blue_fg_strong}| > / Home / Install / Reinstall                               |${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"

    # Check prerequisites
    if ! command -v git &>/dev/null; then
        log_message "ERROR" "${red_fg_strong}Git is not installed. Install git and re-run.${reset}"
        read -p "Press Enter to continue..."
        home; return
    fi
    if ! command -v python3 &>/dev/null; then
        log_message "ERROR" "${red_fg_strong}Python 3 is not installed or not in PATH.${reset}"
        read -p "Press Enter to continue..."
        home; return
    fi

    if [ -d "$comfyui_path" ]; then
        log_message "WARN" "${yellow_fg_strong}ComfyUI is already installed at $comfyui_path${reset}"
        read -p "  Reinstall? This will delete the existing installation. [Y/N]: " confirm
        [ "$(echo "$confirm" | tr '[:upper:]' '[:lower:]')" != "y" ] && home && return
        log_message "INFO" "Removing existing installation..."
        rm -rf "$comfyui_path"
    fi

    # Clone
    log_message "INFO" "Cloning ComfyUI..."
    git clone https://github.com/comfyanonymous/ComfyUI.git "$comfyui_path"
    if [ $? -ne 0 ]; then
        log_message "ERROR" "${red_fg_strong}Clone failed. Check your internet connection.${reset}"
        read -p "Press Enter to continue..."
        home; return
    fi

    # Virtual environment
    log_message "INFO" "Creating Python virtual environment..."
    python3 -m venv "$venv_path"
    if [ $? -ne 0 ]; then
        log_message "ERROR" "${red_fg_strong}Failed to create virtual environment.${reset}"
        read -p "Press Enter to continue..."
        home; return
    fi

    source "$venv_path/bin/activate"
    pip install --upgrade pip --quiet

    # GPU backend
    echo ""
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Select your GPU / compute backend:                           |${reset}"
    echo "    1. NVIDIA — CUDA 12.1  (Recommended)"
    echo "    2. NVIDIA — CUDA 11.8  (Older cards)"
    echo "    3. AMD   — ROCm 6.0   (Linux only)"
    echo "    4. CPU only            (No GPU)"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}|                                                              |${reset}"
    read -p "  Choose Your Destiny: " gpu_choice

    case $gpu_choice in
        1) log_message "INFO" "Installing PyTorch CUDA 12.1..."
           pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu121 ;;
        2) log_message "INFO" "Installing PyTorch CUDA 11.8..."
           pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu118 ;;
        3) log_message "INFO" "Installing PyTorch ROCm 6.0..."
           pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/rocm6.0 ;;
        *) log_message "INFO" "Installing PyTorch CPU only..."
           pip install torch torchvision torchaudio
           cpu_trigger="true"; save_settings ;;
    esac

    if [ $? -ne 0 ]; then
        log_message "ERROR" "${red_fg_strong}PyTorch installation failed.${reset}"
        deactivate; read -p "Press Enter to continue..."; home; return
    fi

    log_message "INFO" "Installing ComfyUI requirements..."
    pip install -r "$comfyui_path/requirements.txt"
    if [ $? -ne 0 ]; then
        log_message "ERROR" "${red_fg_strong}Requirements installation failed.${reset}"
        deactivate; read -p "Press Enter to continue..."; home; return
    fi

    deactivate
    log_message "OK" "${green_fg_strong}ComfyUI installed successfully.${reset}"

    # Optional: ComfyUI-Manager
    echo ""
    read -p "  Install ComfyUI-Manager (node manager UI)? [Y/N]: " mgr
    if [ "$(echo "$mgr" | tr '[:upper:]' '[:lower:]')" == "y" ]; then
        git clone https://github.com/ltdrdata/ComfyUI-Manager.git \
            "$comfyui_path/custom_nodes/ComfyUI-Manager"
        [ $? -eq 0 ] \
            && log_message "OK" "${green_fg_strong}ComfyUI-Manager installed.${reset}" \
            || log_message "WARN" "${yellow_fg_strong}ComfyUI-Manager failed — install it manually later.${reset}"
    fi

    echo ""
    log_message "OK" "${green_fg_strong}Done. Place your models in $comfyui_path/models/${reset}"
    read -p "Press Enter to continue..."
    home
}

# ─── Entry point ──────────────────────────────────────────────────────────────

mkdir -p "$settings_dir"
home
