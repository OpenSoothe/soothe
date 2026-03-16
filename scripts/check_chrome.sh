#!/usr/bin/env bash

# check_chrome.sh
# Check whether installed Google Chrome and chromedriver major versions match.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

CHROMEDRIVER_DIR="${CHROMEDRIVER_DIR:-$HOME/.local/bin}"

echo_info() {
  printf "%b[INFO]%b %s\n" "${YELLOW}" "${NC}" "$*"
}

echo_ok() {
  printf "%b[OK]%b   %s\n" "${GREEN}" "${NC}" "$*"
}

echo_err() {
  printf "%b[ERR]%b  %s\n" "${RED}" "${NC}" "$*"
}

extract_version_number() {
  # Extract the first version-like pattern (e.g. 123.0.6312.86) from a string.
  grep -Eo '[0-9]+(\.[0-9]+)+' | head -n 1
}

get_chrome_version() {
  # Try common Chrome and Chromium binaries on macOS and Linux.
  local chrome_cmd=""

  # macOS default paths - check both Chrome and Chromium
  if [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    chrome_cmd="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  elif [ -x "/Applications/Chromium.app/Contents/MacOS/Chromium" ]; then
    chrome_cmd="/Applications/Chromium.app/Contents/MacOS/Chromium"
  elif command -v google-chrome >/dev/null 2>&1; then
    chrome_cmd="google-chrome"
  elif command -v google-chrome-stable >/dev/null 2>&1; then
    chrome_cmd="google-chrome-stable"
  elif command -v chromium >/dev/null 2>&1; then
    chrome_cmd="chromium"
  elif command -v chromium-browser >/dev/null 2>&1; then
    chrome_cmd="chromium-browser"
  elif command -v chrome >/dev/null 2>&1; then
    chrome_cmd="chrome"
  fi

  if [ -z "${chrome_cmd}" ]; then
    echo_err "Neither Google Chrome nor Chromium found."
    return 1
  fi

  local raw
  if ! raw="$("${chrome_cmd}" --version 2>/dev/null)"; then
    echo_err "Failed to retrieve version using '${chrome_cmd} --version'."
    return 1
  fi

  local version
  version="$(printf "%s\n" "${raw}" | extract_version_number)"
  if [ -z "${version}" ]; then
    echo_err "Could not parse version from: ${raw}"
    return 1
  fi

  printf "%s\n" "${version}"
}

install_chrome() {
  echo_info "Checking for Homebrew..."
  if ! command -v brew >/dev/null 2>&1; then
    echo_err "Homebrew is required to install Google Chrome automatically."
    echo_err "Please install Homebrew from https://brew.sh or install Chrome manually."
    return 1
  fi

  echo_info "Installing Google Chrome via Homebrew..."
  if ! brew install --cask google-chrome; then
    echo_err "Failed to install Google Chrome via Homebrew."
    return 1
  fi

  echo_ok "Google Chrome installed successfully."
}

get_chromedriver_version() {
  local driver_cmd=""

  # Prefer a project-local chromedriver if present.
  if [ -x "${CHROMEDRIVER_DIR}/chromedriver" ]; then
    driver_cmd="${CHROMEDRIVER_DIR}/chromedriver"
  elif command -v chromedriver >/dev/null 2>&1; then
    driver_cmd="$(command -v chromedriver)"
  elif [ -x "/usr/local/bin/chromedriver" ]; then
    driver_cmd="/usr/local/bin/chromedriver"
  fi

  if [ -z "${driver_cmd}" ]; then
    echo_err "chromedriver not found in PATH. Please install it first."
    return 1
  fi

  local raw
  if ! raw="$("${driver_cmd}" --version 2>/dev/null)"; then
    echo_err "Failed to retrieve chromedriver version using '${driver_cmd} --version'."
    return 1
  fi

  local version
  version="$(printf "%s\n" "${raw}" | extract_version_number)"
  if [ -z "${version}" ]; then
    echo_err "Could not parse chromedriver version from: ${raw}"
    return 1
  fi

  printf "%s\n" "${version}"
}

ensure_download_tools() {
  if ! command -v curl >/dev/null 2>&1; then
    echo_err "curl is required to download chromedriver automatically."
    return 1
  fi
  if ! command -v unzip >/dev/null 2>&1; then
    echo_err "unzip is required to extract chromedriver archive."
    return 1
  fi
}

# Chrome for Testing public storage base URL.
CHROME_FOR_TESTING_BASE="https://storage.googleapis.com/chrome-for-testing-public"
KNOWN_GOOD_VERSIONS_JSON="https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"

get_chromedriver_platform() {
  local os arch platform
  os="$(uname -s)"
  arch="$(uname -m)"
  case "${os}" in
    Darwin)
      if [ "${arch}" = "arm64" ]; then
        platform="mac-arm64"
      else
        platform="mac-x64"
      fi
      ;;
    Linux)
      platform="linux64"
      ;;
    *)
      echo_err "Unsupported OS for chromedriver download (macOS and Linux only): ${os}"
      return 1
      ;;
  esac
  printf "%s\n" "${platform}"
}

# Resolve chromedriver version: try exact Chrome version first, then latest for same major from known-good-versions.
resolve_chromedriver_version() {
  local chrome_version="$1"
  local chrome_major="$2"
  local platform="$3"
  local version="${chrome_version}"

  local url="${CHROME_FOR_TESTING_BASE}/${version}/${platform}/chromedriver-${platform}.zip"
  local code
  code="$(curl -sI -o /dev/null -w "%{http_code}" "${url}" 2>/dev/null)" || true
  if [ "${code}" = "200" ]; then
    printf "%s\n" "${version}"
    return 0
  fi

  echo_info "Exact version ${chrome_version} not found; resolving latest for major ${chrome_major}..."
  local json
  json="$(curl -fsSL "${KNOWN_GOOD_VERSIONS_JSON}" 2>/dev/null)" || true
  if [ -z "${json}" ]; then
    echo_err "Could not fetch known-good-versions JSON."
    return 1
  fi
  local resolved
  resolved="$(printf "%s\n" "${json}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
major = sys.argv[1]
platform_key = sys.argv[2]
best = None
for entry in data.get('versions', []):
    v = entry.get('version', '')
    if not v.startswith(major + '.'):
        continue
    downloads = entry.get('downloads', {})
    cd = downloads.get('chromedriver', [])
    for d in cd:
        if d.get('platform') == platform_key:
            best = v
            break
    if best:
        break
if best:
    print(best)
else:
    sys.exit(1)
" "${chrome_major}" "${platform}" 2>/dev/null)" || true
  if [ -z "${resolved}" ]; then
    echo_err "No chromedriver build found for Chrome major ${chrome_major} on ${platform}."
    return 1
  fi
  printf "%s\n" "${resolved}"
}

download_matching_chromedriver() {
  local chrome_version="$1"
  local chrome_major="$2"

  if ! ensure_download_tools; then
    return 1
  fi

  local platform
  platform="$(get_chromedriver_platform)" || return 1
  local zip_name="chromedriver-${platform}.zip"

  local version
  version="$(resolve_chromedriver_version "${chrome_version}" "${chrome_major}" "${platform}")" || return 1

  echo_info "Downloading chromedriver ${version} (${platform})..."
  mkdir -p "${CHROMEDRIVER_DIR}"

  local base="${CHROME_FOR_TESTING_BASE}"
  local url="${base}/${version}/${platform}/${zip_name}"
  local tmp_zip
  tmp_zip="$(mktemp "/tmp/chromedriver_${version}_XXXX.zip")"

  if ! curl -# -fSL "${url}" -o "${tmp_zip}"; then
    echo_err "Failed to download chromedriver from ${url}."
    rm -f "${tmp_zip}"
    return 1
  fi

  local tmp_dir
  tmp_dir="$(mktemp -d "/tmp/chromedriver_${version}_XXXX")"

  if ! unzip -q "${tmp_zip}" -d "${tmp_dir}"; then
    echo_err "Failed to unzip chromedriver archive."
    rm -f "${tmp_zip}"
    rm -rf "${tmp_dir}"
    return 1
  fi

  local driver_dir="${tmp_dir}/chromedriver-${platform}"
  if [ ! -x "${driver_dir}/chromedriver" ]; then
    echo_err "Could not locate chromedriver binary in downloaded archive."
    rm -f "${tmp_zip}"
    rm -rf "${tmp_dir}"
    return 1
  fi

  mv "${driver_dir}/chromedriver" "${CHROMEDRIVER_DIR}/chromedriver"
  chmod +x "${CHROMEDRIVER_DIR}/chromedriver"

  rm -f "${tmp_zip}"
  rm -rf "${tmp_dir}"

  echo_ok "Installed chromedriver to ${CHROMEDRIVER_DIR}/chromedriver"
}

usage() {
  cat <<EOF
Usage: $0

Checks whether the installed Google Chrome and chromedriver major versions match.
If they do not match (or chromedriver is missing), attempts to download a
compatible chromedriver into:

  ${CHROMEDRIVER_DIR}/chromedriver

Exit codes:
  0 - Versions match (possibly after auto-download)
  1 - Chrome not found or version cannot be determined
  2 - chromedriver not found or version cannot be determined even after download
  3 - Versions do not match and automatic download failed
EOF
}

if [ "${1-}" = "-h" ] || [ "${1-}" = "--help" ]; then
  usage
  exit 0
fi

echo_info "Detecting Google Chrome or Chromium version..."
if ! chrome_version="$(get_chrome_version)"; then
  echo_info "Neither Chrome nor Chromium found; will attempt to install Google Chrome."
  if ! install_chrome; then
    echo_err "Could not install Google Chrome automatically."
    exit 1
  fi

  echo_info "Re-checking Chrome version after installation..."
  if ! chrome_version="$(get_chrome_version)"; then
    echo_err "Installed Chrome but still cannot determine its version."
    exit 1
  fi
fi
chrome_major="${chrome_version%%.*}"
echo_ok "Chrome/Chromium version: ${chrome_version} (major ${chrome_major})"

echo_info "Detecting chromedriver version..."
had_chromedriver=true
if ! chromedriver_version="$(get_chromedriver_version)"; then
  had_chromedriver=false
  echo_info "chromedriver not found or version cannot be determined; will attempt to download a matching version."
else
  chromedriver_major="${chromedriver_version%%.*}"
  echo_ok "chromedriver version: ${chromedriver_version} (major ${chromedriver_major})"

  if [ "${chrome_major}" = "${chromedriver_major}" ]; then
    echo_ok "Chrome and chromedriver major versions already match."
    exit 0
  fi

  echo_err "Version mismatch: Chrome major=${chrome_major}, chromedriver major=${chromedriver_major}."
fi

echo_info "Attempting to download chromedriver compatible with Chrome ${chrome_version}..."
if ! download_matching_chromedriver "${chrome_version}" "${chrome_major}"; then
  echo_err "Automatic download of matching chromedriver failed."
  exit 3
fi

echo_info "Re-checking chromedriver version after download..."
if ! chromedriver_version="$(get_chromedriver_version)"; then
  echo_err "Downloaded chromedriver but still cannot determine its version."
  exit 2
fi
chromedriver_major="${chromedriver_version%%.*}"
echo_ok "chromedriver version after download: ${chromedriver_version} (major ${chromedriver_major})"

if [ "${chrome_major}" = "${chromedriver_major}" ]; then
  echo_ok "Chrome and chromedriver major versions match after download."
  exit 0
else
  echo_err "Downloaded chromedriver (major ${chromedriver_major}) still does not match Chrome (major ${chrome_major})."
  exit 3
fi
