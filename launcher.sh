#!/bin/bash
#
# ComfyUI Launcher
#
# Description:
# This script installs, configures, and runs ComfyUI on your Linux system.
#
# Usage:
# chmod +x launcher.sh && ./launcher.sh
#
# GitHub: https://github.com/comfyanonymous/ComfyUI
# ----------------------------------------------------------

echo -e "\033]0;ComfyUI Launcher\007"

# ANSI Escape Code for Colors
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
comfyui_install_path="$launcher_root/ComfyUI"
venv_path="$comfyui_install_path/venv"
settings_dir="$launcher_root/bin/settings"
settings_file="$settings_dir/comfyui_settings.txt"
log_dir="$launcher_root/bin/logs"

# ─── Default settings ─────────────────────────────────────────────────────────

export comfyui_listen_trigger="false"
export comfyui_port_trigger="false"
export comfyui_port="8188"
export comfyui_cpu_trigger="false"
export comfyui_lowvram_trigger="false"
export comfyui_medvram_trigger="false"
export comfyui_highvram_trigger="false"
export comfyui_fp16_vae_trigger="false"
export comfyui_fp32_vae_trigger="false"
export comfyui_bf16_unet_trigger="false"
export comfyui_fp8_e4m3fn_unet_trigger="false"
export comfyui_preview_method="auto"
export comfyui_disable_xformers_trigger="false"
export comfyui_dont_upcast_attention_trigger="false"

# Load saved settings
if [ -f "$settings_file" ]; then
    while IFS='=' read -r key value; do
        export "$key"="$value"
    done < "$settings_file"
fi

# ─── Logging ──────────────────────────────────────────────────────────────────

log_message() {
    current_time=$(date +'%H:%M:%S')
    case "$1" in
        "INFO")  echo -e "${blue_bg}[$current_time]${reset} ${blue_fg_strong}[INFO]${reset} $2" ;;
        "WARN")  echo -e "${yellow_bg}[$current_time]${reset} ${yellow_fg_strong}[WARN]${reset} $2" ;;
        "ERROR") echo -e "${red_bg}[$current_time]${reset} ${red_fg_strong}[ERROR]${reset} $2" ;;
        "OK")    echo -e "${green_bg}[$current_time]${reset} ${green_fg_strong}[OK]${reset} $2" ;;
        *)       echo -e "${blue_bg}[$current_time]${reset} ${blue_fg_strong}[DEBUG]${reset} $2" ;;
    esac
}

# ─── Settings persistence ─────────────────────────────────────────────────────

save_settings() {
    mkdir -p "$settings_dir"
    {
        echo "comfyui_listen_trigger=$comfyui_listen_trigger"
        echo "comfyui_port_trigger=$comfyui_port_trigger"
        echo "comfyui_port=$comfyui_port"
        echo "comfyui_cpu_trigger=$comfyui_cpu_trigger"
        echo "comfyui_lowvram_trigger=$comfyui_lowvram_trigger"
        echo "comfyui_medvram_trigger=$comfyui_medvram_trigger"
        echo "comfyui_highvram_trigger=$comfyui_highvram_trigger"
        echo "comfyui_fp16_vae_trigger=$comfyui_fp16_vae_trigger"
        echo "comfyui_fp32_vae_trigger=$comfyui_fp32_vae_trigger"
        echo "comfyui_bf16_unet_trigger=$comfyui_bf16_unet_trigger"
        echo "comfyui_fp8_e4m3fn_unet_trigger=$comfyui_fp8_e4m3fn_unet_trigger"
        echo "comfyui_preview_method=$comfyui_preview_method"
        echo "comfyui_disable_xformers_trigger=$comfyui_disable_xformers_trigger"
        echo "comfyui_dont_upcast_attention_trigger=$comfyui_dont_upcast_attention_trigger"
    } > "$settings_file"
}

# ─── UI helpers ───────────────────────────────────────────────────────────────

# Print a toggle option in green (enabled) or red (disabled)
printOption() {
    if [ "$2" == "true" ]; then
        echo -e "    ${green_fg_strong}$1 [Enabled]${reset}"
    else
        echo -e "    ${red_fg_strong}$1 [Disabled]${reset}"
    fi
}

# ─── Prerequisite checks ──────────────────────────────────────────────────────

check_git() {
    if ! command -v git &>/dev/null; then
        log_message "ERROR" "${red_fg_strong}Git is not installed. Install git and re-run.${reset}"
        read -p "Press Enter to continue..."
        home
    fi
}

check_python() {
    if ! command -v python3 &>/dev/null; then
        log_message "ERROR" "${red_fg_strong}Python 3 is not installed or not in PATH.${reset}"
        read -p "Press Enter to continue..."
        home
    fi
    local minor
    minor=$(python3 -c "import sys; print(sys.version_info.minor)")
    if [ "$minor" -lt 10 ]; then
        log_message "WARN" "${yellow_fg_strong}Python 3.$minor detected — ComfyUI recommends Python 3.10+.${reset}"
        read -p "Press Enter to continue anyway..."
    fi
}

# ─── Build launch command from current settings ───────────────────────────────

build_launch_cmd() {
    local cmd="python main.py"
    [ "$comfyui_listen_trigger"              == "true" ] && cmd+=" --listen"
    [ "$comfyui_port_trigger"               == "true" ] && cmd+=" --port $comfyui_port"
    [ "$comfyui_cpu_trigger"                == "true" ] && cmd+=" --cpu"
    [ "$comfyui_lowvram_trigger"            == "true" ] && cmd+=" --lowvram"
    [ "$comfyui_medvram_trigger"            == "true" ] && cmd+=" --medvram"
    [ "$comfyui_highvram_trigger"           == "true" ] && cmd+=" --highvram"
    [ "$comfyui_fp16_vae_trigger"           == "true" ] && cmd+=" --fp16-vae"
    [ "$comfyui_fp32_vae_trigger"           == "true" ] && cmd+=" --fp32-vae"
    [ "$comfyui_bf16_unet_trigger"          == "true" ] && cmd+=" --bf16-unet"
    [ "$comfyui_fp8_e4m3fn_unet_trigger"    == "true" ] && cmd+=" --fp8_e4m3fn-unet"
    [ "$comfyui_disable_xformers_trigger"   == "true" ] && cmd+=" --disable-xformers"
    [ "$comfyui_dont_upcast_attention_trigger" == "true" ] && cmd+=" --dont-upcast-attention"
    [ "$comfyui_preview_method"             != "auto" ] && cmd+=" --preview-method $comfyui_preview_method"
    echo "$cmd"
}

########################################################################################
#############################  INSTALLATION  ###########################################
########################################################################################

install_comfyui() {
    echo -e "\033]0;ComfyUI Launcher [INSTALL]\007"
    clear
    echo -e "${blue_fg_strong}| > / Home / Install ComfyUI                                   |${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"

    check_git
    check_python

    if [ -d "$comfyui_install_path" ]; then
        log_message "WARN" "${yellow_fg_strong}ComfyUI is already installed at:${reset}"
        log_message "WARN" "${yellow_fg_strong}  $comfyui_install_path${reset}"
        echo ""
        read -p "  Reinstall? This will delete the existing installation. [Y/N]: " confirm
        confirm=$(echo "$confirm" | tr '[:upper:]' '[:lower:]')
        if [ "$confirm" != "y" ]; then
            home
            return
        fi
        log_message "INFO" "Removing existing installation..."
        rm -rf "$comfyui_install_path"
    fi

    # Clone ComfyUI
    log_message "INFO" "Cloning ComfyUI from GitHub..."
    git clone https://github.com/comfyanonymous/ComfyUI.git "$comfyui_install_path"
    if [ $? -ne 0 ]; then
        log_message "ERROR" "${red_fg_strong}Clone failed. Check your internet connection.${reset}"
        read -p "Press Enter to continue..."
        home
        return
    fi

    # Create virtual environment
    log_message "INFO" "Creating Python virtual environment..."
    python3 -m venv "$venv_path"
    if [ $? -ne 0 ]; then
        log_message "ERROR" "${red_fg_strong}Failed to create virtual environment.${reset}"
        read -p "Press Enter to continue..."
        home
        return
    fi

    source "$venv_path/bin/activate"
    log_message "INFO" "Upgrading pip..."
    pip install --upgrade pip --quiet

    # GPU backend selection
    echo ""
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Select your GPU / compute backend:                           |${reset}"
    echo "    1. NVIDIA GPU — CUDA 12.1  (Recommended for most NVIDIA cards)"
    echo "    2. NVIDIA GPU — CUDA 11.8  (Older NVIDIA cards)"
    echo "    3. AMD GPU   — ROCm 6.0   (Linux only)"
    echo "    4. CPU only               (No GPU — slow, for testing)"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}|                                                              |${reset}"
    read -p "  Choose Your Destiny: " gpu_choice

    case $gpu_choice in
        1)
            log_message "INFO" "Installing PyTorch with CUDA 12.1..."
            pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu121
            ;;
        2)
            log_message "INFO" "Installing PyTorch with CUDA 11.8..."
            pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu118
            ;;
        3)
            log_message "INFO" "Installing PyTorch with ROCm 6.0..."
            pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/rocm6.0
            ;;
        4)
            log_message "INFO" "Installing PyTorch (CPU only)..."
            pip install torch torchvision torchaudio
            comfyui_cpu_trigger="true"
            save_settings
            ;;
        *)
            log_message "WARN" "Invalid choice — defaulting to CPU-only PyTorch."
            pip install torch torchvision torchaudio
            comfyui_cpu_trigger="true"
            save_settings
            ;;
    esac

    if [ $? -ne 0 ]; then
        log_message "ERROR" "${red_fg_strong}PyTorch installation failed.${reset}"
        deactivate
        read -p "Press Enter to continue..."
        home
        return
    fi

    log_message "INFO" "Installing ComfyUI requirements..."
    pip install -r "$comfyui_install_path/requirements.txt"
    if [ $? -ne 0 ]; then
        log_message "ERROR" "${red_fg_strong}Failed to install ComfyUI requirements.${reset}"
        deactivate
        read -p "Press Enter to continue..."
        home
        return
    fi

    deactivate
    log_message "OK" "${green_fg_strong}ComfyUI installed successfully.${reset}"

    # Offer ComfyUI-Manager
    echo ""
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Optional: Install ComfyUI-Manager?                          |${reset}"
    echo "    Adds a UI to install, update, and manage custom nodes."
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    read -p "  Install ComfyUI-Manager? [Y/N]: " manager_choice
    manager_choice=$(echo "$manager_choice" | tr '[:upper:]' '[:lower:]')
    if [ "$manager_choice" == "y" ]; then
        log_message "INFO" "Cloning ComfyUI-Manager..."
        git clone https://github.com/ltdrdata/ComfyUI-Manager.git \
            "$comfyui_install_path/custom_nodes/ComfyUI-Manager"
        if [ $? -eq 0 ]; then
            log_message "OK" "${green_fg_strong}ComfyUI-Manager installed.${reset}"
        else
            log_message "WARN" "${yellow_fg_strong}ComfyUI-Manager install failed — you can add it manually later.${reset}"
        fi
    fi

    echo ""
    log_message "OK" "${green_fg_strong}Installation complete. Place your models in:${reset}"
    log_message "OK" "${green_fg_strong}  $comfyui_install_path/models/${reset}"
    read -p "Press Enter to continue..."
    home
}

########################################################################################
##############################  UPDATE  ################################################
########################################################################################

update_comfyui() {
    echo -e "\033]0;ComfyUI Launcher [UPDATE]\007"
    clear
    echo -e "${blue_fg_strong}| > / Home / Update ComfyUI                                    |${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"

    if [ ! -d "$comfyui_install_path" ]; then
        log_message "ERROR" "${red_fg_strong}ComfyUI is not installed. Please install it first.${reset}"
        read -p "Press Enter to continue..."
        home
        return
    fi

    log_message "INFO" "Pulling latest ComfyUI changes..."
    git -C "$comfyui_install_path" pull --rebase --autostash
    if [ $? -ne 0 ]; then
        log_message "ERROR" "${red_fg_strong}Git pull failed. Your local changes may have conflicts.${reset}"
        read -p "Press Enter to continue..."
        home
        return
    fi

    log_message "INFO" "Updating Python dependencies..."
    source "$venv_path/bin/activate"
    pip install -r "$comfyui_install_path/requirements.txt" --upgrade --quiet
    deactivate

    log_message "OK" "${green_fg_strong}ComfyUI updated successfully.${reset}"
    read -p "Press Enter to continue..."
    home
}

########################################################################################
############################  CONFIGURATION  ###########################################
########################################################################################

configure_comfyui() {
    echo -e "\033]0;ComfyUI Launcher [CONFIGURE]\007"
    clear
    echo -e "${blue_fg_strong}| > / Home / Configure ComfyUI                                 |${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| What would you like to configure?                            |${reset}"
    echo "    1. Launch Arguments"
    echo "    2. Model Paths  (extra_model_paths.yaml)"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Menu Options:                                                |${reset}"
    echo "    0. Back"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}|                                                              |${reset}"
    read -p "  Choose Your Destiny: " configure_choice

    case $configure_choice in
        1) configure_launch_args ;;
        2) configure_model_paths ;;
        0) home ;;
        *) echo -e "${yellow_fg_strong}WARNING: Invalid number. Please insert a valid number.${reset}"
           read -p "Press Enter to continue..."
           configure_comfyui ;;
    esac
}

############################################################
############ LAUNCH ARGS - FRONTEND ########################
############################################################

configure_launch_args() {
    echo -e "\033]0;ComfyUI Launcher [LAUNCH ARGS]\007"
    clear
    echo -e "${blue_fg_strong}| > / Home / Configure / Launch Arguments                      |${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Toggle options — enter numbers separated by spaces           |${reset}"
    echo -e "${cyan_fg_strong}| e.g. \"1 4\" enables Listen and Low VRAM mode                 |${reset}"
    echo ""

    # Networking
    echo -e "  ${cyan_fg_strong}── Networking ──────────────────────────────────────────────${reset}"
    printOption "1.  Listen on all interfaces  (--listen)" "$comfyui_listen_trigger"
    if [ "$comfyui_port_trigger" == "true" ]; then
        echo -e "    ${green_fg_strong}2.  Custom port [Enabled: $comfyui_port]${reset}"
    else
        echo -e "    ${red_fg_strong}2.  Custom port [Disabled — default: 8188]${reset}"
    fi

    # VRAM management
    echo ""
    echo -e "  ${cyan_fg_strong}── VRAM Management ─────────────────────────────────────────${reset}"
    printOption "3.  CPU only      (--cpu)"     "$comfyui_cpu_trigger"
    printOption "4.  Low VRAM      (--lowvram)" "$comfyui_lowvram_trigger"
    printOption "5.  Medium VRAM   (--medvram)" "$comfyui_medvram_trigger"
    printOption "6.  High VRAM     (--highvram)" "$comfyui_highvram_trigger"

    # Precision
    echo ""
    echo -e "  ${cyan_fg_strong}── Precision ───────────────────────────────────────────────${reset}"
    printOption "7.  FP16 VAE         (--fp16-vae)"          "$comfyui_fp16_vae_trigger"
    printOption "8.  FP32 VAE         (--fp32-vae)"          "$comfyui_fp32_vae_trigger"
    printOption "9.  BF16 UNet        (--bf16-unet)"         "$comfyui_bf16_unet_trigger"
    printOption "10. FP8 E4M3FN UNet  (--fp8_e4m3fn-unet)"  "$comfyui_fp8_e4m3fn_unet_trigger"

    # Performance
    echo ""
    echo -e "  ${cyan_fg_strong}── Performance ─────────────────────────────────────────────${reset}"
    printOption "11. Disable xformers           (--disable-xformers)"       "$comfyui_disable_xformers_trigger"
    printOption "12. Don't upcast attention     (--dont-upcast-attention)"  "$comfyui_dont_upcast_attention_trigger"
    echo ""
    echo -e "    ${cyan_fg_strong}Preview method: $comfyui_preview_method${reset}"
    echo "    13. Set preview method  (auto / latent2rgb / taesd / none)"

    echo ""
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Preview of launch command:                                   |${reset}"
    echo -e "  ${yellow_fg_strong}$(build_launch_cmd)${reset}"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Menu Options:                                                |${reset}"
    echo "    0. Back"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}|                                                              |${reset}"
    read -p "  Toggle options: " arg_choices

############## LAUNCH ARGS - BACKEND ######################

    for i in $arg_choices; do
        case $i in
            0)  save_settings; configure_comfyui; return ;;

            1)  [ "$comfyui_listen_trigger" == "true" ] \
                    && comfyui_listen_trigger="false" \
                    || comfyui_listen_trigger="true"
                ;;

            2)  if [ "$comfyui_port_trigger" == "true" ]; then
                    comfyui_port_trigger="false"
                    comfyui_port="8188"
                else
                    read -p "    Enter port number (1024-65535): " new_port
                    if [[ "$new_port" =~ ^[0-9]+$ ]] \
                        && [ "$new_port" -ge 1024 ] \
                        && [ "$new_port" -le 65535 ]; then
                        comfyui_port="$new_port"
                        comfyui_port_trigger="true"
                    else
                        log_message "WARN" "Invalid port — must be 1024–65535."
                    fi
                fi
                ;;

            3)  [ "$comfyui_cpu_trigger" == "true" ] \
                    && comfyui_cpu_trigger="false" \
                    || comfyui_cpu_trigger="true"
                ;;

            # VRAM options are mutually exclusive
            4)  if [ "$comfyui_lowvram_trigger" == "true" ]; then
                    comfyui_lowvram_trigger="false"
                else
                    comfyui_lowvram_trigger="true"
                    comfyui_medvram_trigger="false"
                    comfyui_highvram_trigger="false"
                fi ;;

            5)  if [ "$comfyui_medvram_trigger" == "true" ]; then
                    comfyui_medvram_trigger="false"
                else
                    comfyui_medvram_trigger="true"
                    comfyui_lowvram_trigger="false"
                    comfyui_highvram_trigger="false"
                fi ;;

            6)  if [ "$comfyui_highvram_trigger" == "true" ]; then
                    comfyui_highvram_trigger="false"
                else
                    comfyui_highvram_trigger="true"
                    comfyui_lowvram_trigger="false"
                    comfyui_medvram_trigger="false"
                fi ;;

            # VAE precision options are mutually exclusive
            7)  if [ "$comfyui_fp16_vae_trigger" == "true" ]; then
                    comfyui_fp16_vae_trigger="false"
                else
                    comfyui_fp16_vae_trigger="true"
                    comfyui_fp32_vae_trigger="false"
                fi ;;

            8)  if [ "$comfyui_fp32_vae_trigger" == "true" ]; then
                    comfyui_fp32_vae_trigger="false"
                else
                    comfyui_fp32_vae_trigger="true"
                    comfyui_fp16_vae_trigger="false"
                fi ;;

            # UNet precision options are mutually exclusive
            9)  if [ "$comfyui_bf16_unet_trigger" == "true" ]; then
                    comfyui_bf16_unet_trigger="false"
                else
                    comfyui_bf16_unet_trigger="true"
                    comfyui_fp8_e4m3fn_unet_trigger="false"
                fi ;;

            10) if [ "$comfyui_fp8_e4m3fn_unet_trigger" == "true" ]; then
                    comfyui_fp8_e4m3fn_unet_trigger="false"
                else
                    comfyui_fp8_e4m3fn_unet_trigger="true"
                    comfyui_bf16_unet_trigger="false"
                fi ;;

            11) [ "$comfyui_disable_xformers_trigger" == "true" ] \
                    && comfyui_disable_xformers_trigger="false" \
                    || comfyui_disable_xformers_trigger="true"
                ;;

            12) [ "$comfyui_dont_upcast_attention_trigger" == "true" ] \
                    && comfyui_dont_upcast_attention_trigger="false" \
                    || comfyui_dont_upcast_attention_trigger="true"
                ;;

            13) echo "    Preview methods: auto  latent2rgb  taesd  none"
                read -p "    Enter preview method: " new_preview
                case "$new_preview" in
                    auto|latent2rgb|taesd|none)
                        comfyui_preview_method="$new_preview" ;;
                    *)
                        log_message "WARN" "Invalid — choose: auto, latent2rgb, taesd, none" ;;
                esac
                ;;

            *) echo -e "${yellow_fg_strong}WARNING: '$i' is not a valid option.${reset}" ;;
        esac
    done

    save_settings
    configure_launch_args
}

############################################################
############ MODEL PATHS - FRONTEND ########################
############################################################

configure_model_paths() {
    echo -e "\033]0;ComfyUI Launcher [MODEL PATHS]\007"
    clear
    echo -e "${blue_fg_strong}| > / Home / Configure / Model Paths                           |${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"

    if [ ! -d "$comfyui_install_path" ]; then
        log_message "ERROR" "${red_fg_strong}ComfyUI is not installed.${reset}"
        read -p "Press Enter to continue..."
        configure_comfyui
        return
    fi

    local yaml_path="$comfyui_install_path/extra_model_paths.yaml"
    local example_path="$comfyui_install_path/extra_model_paths.yaml.example"

    # Show current status
    if [ -f "$yaml_path" ]; then
        echo -e "  Status: ${green_fg_strong}extra_model_paths.yaml exists${reset}"
    else
        echo -e "  Status: ${yellow_fg_strong}extra_model_paths.yaml not yet created${reset}"
    fi
    echo ""
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| What would you like to do?                                   |${reset}"
    echo "    1. Edit extra_model_paths.yaml in nano"
    echo "    2. Show current extra_model_paths.yaml"
    echo "    3. Reset to example (copy from .yaml.example)"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Menu Options:                                                |${reset}"
    echo "    0. Back"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}|                                                              |${reset}"
    read -p "  Choose Your Destiny: " paths_choice

############### MODEL PATHS - BACKEND ######################

    case $paths_choice in
        1)
            if ! command -v nano &>/dev/null; then
                log_message "ERROR" "${red_fg_strong}nano is not installed. Install nano to edit files.${reset}"
                read -p "Press Enter to continue..."
                configure_model_paths
                return
            fi
            if [ ! -f "$yaml_path" ]; then
                if [ -f "$example_path" ]; then
                    log_message "INFO" "Copying from example..."
                    cp "$example_path" "$yaml_path"
                else
                    log_message "INFO" "Creating blank extra_model_paths.yaml..."
                    cat > "$yaml_path" <<'EOF'
# ComfyUI extra model paths
# Uncomment and edit paths to point ComfyUI at existing model directories.
#
# Example:
# comfyui:
#     base_path: /path/to/stable-diffusion-webui/
#     checkpoints: models/Stable-diffusion
#     vae: models/VAE
#     loras: |
#          models/Lora
#          models/LyCORIS
#     upscale_models: models/ESRGAN
#     embeddings: embeddings
#     hypernetworks: models/hypernetworks
#     controlnet: models/ControlNet
EOF
                fi
            fi
            nano "$yaml_path"
            configure_model_paths
            ;;

        2)
            echo ""
            if [ -f "$yaml_path" ]; then
                echo -e "${cyan_fg_strong}── $yaml_path ──${reset}"
                cat "$yaml_path"
            else
                log_message "WARN" "No extra_model_paths.yaml found."
            fi
            echo ""
            read -p "Press Enter to continue..."
            configure_model_paths
            ;;

        3)
            if [ -f "$example_path" ]; then
                cp "$example_path" "$yaml_path"
                log_message "OK" "${green_fg_strong}Reset to example configuration.${reset}"
            else
                log_message "WARN" "${yellow_fg_strong}No .yaml.example found to restore from.${reset}"
            fi
            read -p "Press Enter to continue..."
            configure_model_paths
            ;;

        0) configure_comfyui ;;

        *)
            echo -e "${yellow_fg_strong}WARNING: Invalid number. Please insert a valid number.${reset}"
            read -p "Press Enter to continue..."
            configure_model_paths
            ;;
    esac
}

########################################################################################
################################  LAUNCH  ##############################################
########################################################################################

launch_comfyui() {
    echo -e "\033]0;ComfyUI Launcher [RUNNING]\007"
    clear
    echo -e "${blue_fg_strong}| > / Home / Launch ComfyUI                                    |${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"

    if [ ! -d "$comfyui_install_path" ]; then
        log_message "ERROR" "${red_fg_strong}ComfyUI is not installed. Run Install first.${reset}"
        read -p "Press Enter to continue..."
        home
        return
    fi

    if [ ! -d "$venv_path" ]; then
        log_message "ERROR" "${red_fg_strong}Virtual environment not found at:${reset}"
        log_message "ERROR" "${red_fg_strong}  $venv_path${reset}"
        log_message "INFO" "Try reinstalling ComfyUI."
        read -p "Press Enter to continue..."
        home
        return
    fi

    local cmd
    cmd=$(build_launch_cmd)

    echo ""
    log_message "INFO" "Launching: ${cyan_fg_strong}$cmd${reset}"
    log_message "INFO" "ComfyUI will be available at: ${green_fg_strong}http://127.0.0.1:${comfyui_port}/${reset}"
    echo ""
    echo -e "${yellow_fg_strong}  Press Ctrl+C to stop ComfyUI and return to the menu.${reset}"
    echo ""

    cd "$comfyui_install_path" || {
        log_message "ERROR" "Cannot cd to $comfyui_install_path"
        read -p "Press Enter to continue..."
        home
        return
    }

    source "$venv_path/bin/activate"
    $cmd
    deactivate

    echo ""
    log_message "INFO" "ComfyUI has exited."
    read -p "Press Enter to return to the menu..."
    home
}

########################################################################################
###################################  HOME  #############################################
########################################################################################

home() {
    echo -e "\033]0;ComfyUI Launcher\007"
    clear

    # Installation status indicator
    local install_status
    if [ -d "$comfyui_install_path" ]; then
        install_status="${green_fg_strong}Installed${reset}"
    else
        install_status="${red_fg_strong}Not installed${reset}"
    fi

    echo -e "${blue_fg_strong} ==============================================================${reset}"
    echo -e "${blue_fg_strong}                    ComfyUI Launcher                           ${reset}"
    echo -e "${blue_fg_strong} ==============================================================${reset}"
    echo -e "  Status:  $install_status"
    echo -e "  Path:    ${cyan_fg_strong}$comfyui_install_path${reset}"
    echo -e "  Command: ${yellow_fg_strong}$(build_launch_cmd)${reset}"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| What would you like to do?                                   |${reset}"
    echo "    1. Launch ComfyUI"
    echo "    2. Install ComfyUI"
    echo "    3. Update ComfyUI"
    echo "    4. Configure"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}| Menu Options:                                                |${reset}"
    echo "    0. Exit"
    echo -e "${cyan_fg_strong} ______________________________________________________________${reset}"
    echo -e "${cyan_fg_strong}|                                                              |${reset}"
    read -p "  Choose Your Destiny: " home_choice

    case $home_choice in
        1) launch_comfyui ;;
        2) install_comfyui ;;
        3) update_comfyui ;;
        4) configure_comfyui ;;
        0) echo -e "${blue_fg_strong}Goodbye.${reset}"; exit 0 ;;
        *)
            echo -e "${yellow_fg_strong}WARNING: Invalid number. Please insert a valid number.${reset}"
            read -p "Press Enter to continue..."
            home
            ;;
    esac
}

# ─── Entry point ──────────────────────────────────────────────────────────────

mkdir -p "$log_dir" "$settings_dir"
home
