#!/usr/bin/bash

# PowerDeck Installation Script
# Automatically downloads and installs the latest PowerDeck release from GitHub

set -euo pipefail  # Exit on error, undefined vars, and pipe failures

# Configuration
readonly PACKAGE="PowerDeck"
readonly GITHUB_REPO="fewtarius/${PACKAGE}"
readonly GITHUB_API_URL="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"
readonly HOMEBREW_PLUGINS_DIR="${HOME}/homebrew/plugins"
readonly PLUGIN_DIR="${HOMEBREW_PLUGINS_DIR}/${PACKAGE}"

# Global state tracking
filesystem_was_unlocked=false

# Debug mode (set to true for verbose output)
DEBUG=false
if [[ "${1:-}" == "--debug" ]] || [[ "${DEBUG_INSTALL:-}" == "true" ]]; then
    DEBUG=true
    set -x  # Enable command tracing
fi

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

log_debug() {
    if [[ "$DEBUG" == true ]]; then
        echo -e "${BLUE}[DEBUG]${NC} $1" >&2
    fi
}

# Cleanup function
cleanup() {
    local temp_dir="$1"
    if [[ -n "${temp_dir:-}" && -d "$temp_dir" ]]; then
        log_info "Cleaning up temporary files..."
        rm -rf "$temp_dir"
    fi
    
    # Re-lock SteamOS filesystem if it was unlocked
    if [[ "${filesystem_was_unlocked:-}" == "true" ]]; then
        log_warning "Script interrupted, attempting to re-lock filesystem..."
        lock_filesystem
    fi
}

# Trap to ensure cleanup on exit
trap 'cleanup "${temp_dir:-}"' EXIT

# Validation functions
check_root() {
    if [[ "$EUID" -eq 0 ]]; then
        log_error "This script should not be run as root"
        log_error "Please run as a regular user (the script will use sudo when needed)"
        exit 1
    fi
}

# Check if we're running on SteamOS
check_steamos() {
    if [[ -f "/etc/os-release" ]]; then
        if grep -q "SteamOS" /etc/os-release; then
            log_debug "Detected SteamOS system"
            return 0
        fi
    fi
    log_debug "Not running on SteamOS, proceeding with standard installation"
    return 1
}

# Check if filesystem is read-only (SteamOS)
check_readonly_filesystem() {
    if mount | grep -q "on / type.*ro,"; then
        log_debug "Detected read-only root filesystem"
        return 0
    fi
    return 1
}

# Unlock SteamOS filesystem
unlock_filesystem() {
    log_info "Unlocking SteamOS read-only filesystem..."
    if ! sudo steamos-readonly disable; then
        log_error "Failed to disable read-only filesystem"
        return 1
    fi
    filesystem_was_unlocked=true
    log_success "Filesystem unlocked successfully"
    return 0
}

# Lock SteamOS filesystem
lock_filesystem() {
    log_info "Re-enabling SteamOS read-only filesystem protection..."
    if ! sudo steamos-readonly enable; then
        log_warning "Failed to re-enable read-only filesystem (this may be okay)"
        return 1
    else
        filesystem_was_unlocked=false
        log_success "Filesystem protection re-enabled"
        return 0
    fi
}

# Verify RyzenAdj installation
verify_ryzenadj_installation() {
    local target_path="$1"
    
    log_debug "Verifying RyzenAdj installation at: $target_path"
    
    if [[ ! -f "$target_path" ]]; then
        log_error "RyzenAdj binary not found at $target_path"
        return 1
    fi
    
    if [[ ! -x "$target_path" ]]; then
        log_error "RyzenAdj binary is not executable"
        return 1
    fi
    
    # Test binary execution
    if ! "$target_path" --help >/dev/null 2>&1; then
        log_error "RyzenAdj binary failed to execute"
        return 1
    fi
    
    log_debug "RyzenAdj installation verified successfully"
    
    # Show version info if available
    if "$target_path" --version >/dev/null 2>&1; then
        local version=$("$target_path" --version 2>/dev/null | head -1)
        log_info "RyzenAdj version: $version"
    fi
    
    return 0
}

check_dependencies() {
    local missing_deps=()
    
    for cmd in curl unzip rsync systemctl; do
        if ! command -v "$cmd" &> /dev/null; then
            missing_deps+=("$cmd")
        fi
    done
    
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_error "Missing required dependencies: ${missing_deps[*]}"
        exit 1
    fi
}

check_homebrew_dir() {
    if [[ ! -d "$HOMEBREW_PLUGINS_DIR" ]]; then
        log_error "Homebrew plugins directory not found: $HOMEBREW_PLUGINS_DIR"
        log_error "Please ensure Decky Loader is properly installed"
        exit 1
    fi
}

# Main installation functions
prepare_plugin_directory() {
    log_info "Preparing plugin directory: $PLUGIN_DIR"
    
    # Set permissions on plugins directory
    if ! sudo chmod -R +w "$HOMEBREW_PLUGINS_DIR" 2>/dev/null; then
        log_error "Failed to set permissions on plugins directory"
        exit 1
    fi
    
    # Create plugin directory
    if ! sudo mkdir -p "$PLUGIN_DIR"; then
        log_error "Failed to create plugin directory: $PLUGIN_DIR"
        exit 1
    fi
}

fetch_release_info() {
    log_info "Fetching latest release information from GitHub..." >&2
    log_debug "API URL: $GITHUB_API_URL" >&2
    
    local release_data http_code
    
    # Fetch with HTTP status code
    if ! release_data=$(curl -s -w "%{http_code}" "$GITHUB_API_URL"); then
        log_error "Failed to fetch release information from GitHub API"
        exit 1
    fi
    
    # Extract HTTP status code (last 3 characters)
    http_code="${release_data: -3}"
    release_data="${release_data%???}"  # Remove last 3 characters (status code)
    
    log_debug "HTTP Status: $http_code" >&2
    log_debug "Response length: ${#release_data} characters" >&2
    log_debug "Response preview: ${release_data:0:100}..." >&2
    
    # Check HTTP status
    if [[ "$http_code" != "200" ]]; then
        log_error "GitHub API returned HTTP status: $http_code"
        if [[ "$http_code" == "403" ]]; then
            log_error "Rate limit exceeded. Please try again later."
        elif [[ "$http_code" == "404" ]]; then
            log_error "Repository or release not found: $GITHUB_REPO"
        else
            log_error "HTTP response body: $release_data"
        fi
        exit 1
    fi
    
    # Validate JSON format
    if [[ -z "$release_data" ]] || [[ "${release_data:0:1}" != "{" ]]; then
        log_error "Invalid JSON response from GitHub API"
        log_error "Response: $release_data"
        exit 1
    fi
    
    echo "$release_data"
}

parse_release_data() {
    local release_data="$1"
    local use_jq=false
    
    # Check if jq is available for better JSON parsing
    if command -v jq &> /dev/null; then
        use_jq=true
        log_info "Using jq for JSON parsing" >&2
    else
        log_warning "jq not found, using basic text parsing (consider installing jq for more reliable parsing)"
    fi
    
    local message release_version release_url
    
    if [[ "$use_jq" == true ]]; then
        # Test if jq can parse the JSON first
        if ! echo "$release_data" | jq . >/dev/null 2>&1; then
            log_error "Invalid JSON format received from GitHub API"
            log_error "Raw response: $release_data"
            exit 1
        fi
        
        message=$(echo "$release_data" | jq -r '.message // "null"' 2>/dev/null || echo "null")
        release_version=$(echo "$release_data" | jq -r '.tag_name // empty' 2>/dev/null || echo "")
        release_url=$(echo "$release_data" | jq -r '.assets[0].browser_download_url // empty' 2>/dev/null || echo "")
        
        # If jq parsing fails, fall back to text parsing
        if [[ -z "$release_version" && -z "$release_url" ]]; then
            log_warning "jq parsing failed, falling back to text parsing"
            use_jq=false
        fi
    fi
    
    if [[ "$use_jq" == false ]]; then
        # More robust text parsing with error handling
        message=$(echo "$release_data" | grep -o '"message"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"message"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' 2>/dev/null || echo "null")
        release_version=$(echo "$release_data" | grep -o '"tag_name"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' 2>/dev/null || echo "")
        release_url=$(echo "$release_data" | grep -o '"browser_download_url"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"browser_download_url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' 2>/dev/null || echo "")
    fi
    
    # Check for API errors
    if [[ "$message" != "null" && -n "$message" && "$message" != "" ]]; then
        log_error "GitHub API returned an error: $message"
        exit 1
    fi
    
    # Validate required fields
    if [[ -z "$release_version" ]]; then
        log_error "Failed to parse release version from GitHub API response"
        log_error "This could indicate the repository has no releases or an API format change"
        exit 1
    fi
    
    if [[ -z "$release_url" ]]; then
        log_error "Failed to parse download URL from GitHub API response"
        log_error "This could indicate no downloadable assets or an API format change"
        exit 1
    fi
    
    log_info "Found release: $release_version" >&2
    echo "$release_version|$release_url"
}

download_and_install() {
    local release_version="$1"
    local release_url="$2"
    local temp_dir="$3"
    
    local temp_file="${temp_dir}/${PACKAGE}.zip"
    
    log_info "Downloading ${PACKAGE} ${release_version}..."
    log_info "Download URL: $release_url"
    
    if ! curl -L "$release_url" -o "$temp_file"; then
        log_error "Failed to download release archive"
        exit 1
    fi
    
    log_info "Extracting archive to temporary directory..."
    if ! unzip -q "$temp_file" -d "$temp_dir"; then
        log_error "Failed to extract release archive"
        exit 1
    fi
    
    log_info "Installing ${PACKAGE} to ${PLUGIN_DIR}..."
    if ! sudo rsync -av "${temp_dir}/${PACKAGE}/" "$PLUGIN_DIR" --delete; then
        log_error "Failed to install plugin files"
        exit 1
    fi
    
    # Set proper ownership
    if ! sudo chown -R "$(whoami):$(whoami)" "$PLUGIN_DIR"; then
        log_warning "Failed to set ownership of plugin directory (this may be okay)"
    fi
    
    # Install RyzenAdj if available in the package
    install_ryzenadj_if_available "$temp_dir"
}

install_ryzenadj_if_available() {
    local temp_dir="$1"
    local ryzenadj_source="${temp_dir}/RyzenAdj/build/ryzenadj"
    
    log_info "Checking for RyzenAdj binary in package..."
    log_debug "Looking for RyzenAdj at: $ryzenadj_source"
    
    # Check if RyzenAdj is already installed system-wide
    if command -v ryzenadj &> /dev/null; then
        local existing_path=$(command -v ryzenadj)
        log_success "RyzenAdj already installed at: $existing_path"
        return 0
    fi
    
    # Check if RyzenAdj binary is in the package
    if [[ ! -f "$ryzenadj_source" ]]; then
        log_warning "RyzenAdj binary not found in package"
        log_warning "TDP control features may be limited without RyzenAdj"
        return 0
    fi
    
    log_info "Installing RyzenAdj binary for TDP control..."
    
    # Create /opt/ryzenadj/bin directory
    local target_dir="/opt/ryzenadj/bin"
    local target_path="$target_dir/ryzenadj"
    
    # Check if we're on SteamOS and need to unlock filesystem
    if check_steamos && check_readonly_filesystem; then
        unlock_filesystem
    fi
    
    if ! sudo mkdir -p "$target_dir"; then
        log_error "Failed to create RyzenAdj directory: $target_dir"
        return 1
    fi
    
    # Copy RyzenAdj binary
    if ! sudo cp "$ryzenadj_source" "$target_path"; then
        log_error "Failed to copy RyzenAdj binary to $target_path"
        return 1
    fi
    
    # Set execute permissions
    if ! sudo chmod +x "$target_path"; then
        log_error "Failed to set execute permissions on RyzenAdj binary"
        return 1
    fi

    # Note: No symlink to /usr/bin on SteamOS as filesystem is immutable
    log_debug "RyzenAdj installed at $target_path (accessible via PowerDeck)"
    
    # Re-lock filesystem if we unlocked it
    if [[ "$filesystem_was_unlocked" == true ]]; then
        lock_filesystem
    fi
    
    # Verify installation
    if ! verify_ryzenadj_installation "$target_path"; then
        log_warning "RyzenAdj binary installed but verification failed"
        return 1
    fi
    
    log_success "RyzenAdj installed successfully at: $target_path"
    log_info "TDP control features are now available"
    
    return 0
}

restart_plugin_loader() {
    log_info "Restarting plugin loader service..."
    if ! sudo systemctl restart plugin_loader.service; then
        log_error "Failed to restart plugin_loader.service"
        log_warning "You may need to restart it manually: sudo systemctl restart plugin_loader.service"
        exit 1
    fi
    
    # Wait a moment for the service to start
    sleep 2
    
    # Check if the service is running
    if sudo systemctl is-active --quiet plugin_loader.service; then
        log_success "Plugin loader service restarted successfully"
    else
        log_warning "Plugin loader service may not be running properly"
        log_info "Check status with: sudo systemctl status plugin_loader.service"
    fi
}

# Main execution
main() {
    log_info "Starting ${PACKAGE} installation..."
    
    # Perform validation checks
    check_root
    check_dependencies
    check_homebrew_dir
    
    # Create temporary directory
    local temp_dir
    temp_dir=$(mktemp -d)
    
    # Prepare installation environment
    prepare_plugin_directory
    
    # Fetch and parse release information
    local release_data
    release_data=$(fetch_release_info)
    
    local release_info
    release_info=$(parse_release_data "$release_data")
    
    local release_version release_url
    IFS='|' read -r release_version release_url <<< "$release_info"
    
    # Download and install
    download_and_install "$release_version" "$release_url" "$temp_dir"
    
    # Restart plugin loader
    restart_plugin_loader
    
    log_success "${PACKAGE} ${release_version} has been successfully installed!"
    log_info "The plugin should now be available in your Decky Loader menu"
}

# Execute main function
main "$@"
