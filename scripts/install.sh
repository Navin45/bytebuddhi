#!/usr/bin/env bash
# ByteBuddhi CLI Installer — Unix (bash/zsh)
#
# Install:  curl -fsSL https://github.com/Navin45/bytebuddhi/releases/latest/download/install.sh | bash
# Options:  BYTEBUDDHI_VERSION=0.1.4  — pin a specific release
#           BYTEBUDDHI_HOME=~/.local/bytebuddhi — custom install root

set -euo pipefail

OWNER="Navin45"
REPO="bytebuddhi"
BASE_URL="https://github.com/${OWNER}/${REPO}/releases"
INSTALL_DIR="${BYTEBUDDHI_HOME:-$HOME/.bytebuddhi}"
BIN_DIR="${INSTALL_DIR}/bin"
MIN_PYTHON="3.13"

# ── Helpers ────────────────────────────────────────────────────────────

info()  { printf "\033[1;34m%s\033[0m\n" "$*"; }
ok()    { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }
fail()  { printf "  \033[1;31m✗\033[0m %s\n" "$*" >&2; exit 1; }

need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        fail "Required command not found: $1"
    fi
}

# ── Prerequisites ──────────────────────────────────────────────────────

need_cmd curl

sha256_check() {
    local file="$1" expected="$2"
    local actual
    if command -v sha256sum >/dev/null 2>&1; then
        actual=$(sha256sum "$file" | awk '{print $1}')
    elif command -v shasum >/dev/null 2>&1; then
        actual=$(shasum -a 256 "$file" | awk '{print $1}')
    elif command -v openssl >/dev/null 2>&1; then
        actual=$(openssl dgst -sha256 "$file" | awk '{print $NF}')
    else
        fail "No sha256 tool found (need sha256sum, shasum, or openssl)"
    fi
    if [ "$actual" != "$expected" ]; then
        fail "SHA-256 mismatch for $(basename "$file"): expected ${expected}, got ${actual}"
    fi
}

get_managed_runtime() {
    local runtime_dir="${INSTALL_DIR}/runtime"
    local uv_bin="${runtime_dir}/uv"
    if [ -x "$uv_bin" ]; then
        echo "uv:${uv_bin}"
        return
    fi
    if command -v uv >/dev/null 2>&1; then
        echo "uv:$(command -v uv)"
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        if python3 -c "import sys; exit(0 if sys.version_info >= (3, 13) else 1)" 2>/dev/null; then
            echo "python:$(command -v python3)"
            return
        fi
    fi

    info "Bootstrapping self-contained runtime manager (no system Python required) …"
    mkdir -p "$runtime_dir"
    local os arch target_url
    os="$(uname -s)"
    arch="$(uname -m)"

    if [ "$os" = "Darwin" ]; then
        if [ "$arch" = "arm64" ]; then
            target_url="https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-apple-darwin.tar.gz"
        else
            target_url="https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-apple-darwin.tar.gz"
        fi
    elif [ "$os" = "Linux" ]; then
        if [ "$arch" = "x86_64" ]; then
            target_url="https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz"
        elif [ "$arch" = "aarch64" ]; then
            target_url="https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-unknown-linux-gnu.tar.gz"
        else
            fail "Unsupported Linux architecture: $arch"
        fi
    else
        fail "Unsupported operating system: $os"
    fi

    local tmp_tar="${TMPDIR}/uv.tar.gz"
    curl -fsSL -o "$tmp_tar" "$target_url" || fail "Failed to download self-contained runtime manager"
    tar -xzf "$tmp_tar" -C "$runtime_dir" --strip-components=1 2>/dev/null || tar -xzf "$tmp_tar" -C "$runtime_dir"
    if [ ! -x "$uv_bin" ]; then
        local found
        found="$(find "$runtime_dir" -name uv -type f -perm +111 2>/dev/null | head -n 1)"
        if [ -n "$found" ]; then
            mv "$found" "$uv_bin"
        fi
    fi
    chmod +x "$uv_bin" 2>/dev/null || true
    if [ ! -x "$uv_bin" ]; then
        fail "Could not initialize self-contained runtime manager."
    fi
    ok "Provisioned self-contained runtime manager"
    echo "uv:${uv_bin}"
}

# ── Resolve version ───────────────────────────────────────────────────

VERSION="${BYTEBUDDHI_VERSION:-}"

if [ -z "$VERSION" ]; then
    info "Resolving latest stable release …"
    RELEASE_URL="${BASE_URL}/latest/download/release.json"
    MANIFEST=$(curl -fsSL "$RELEASE_URL") || fail "Could not fetch release manifest"
    VERSION=$(echo "$MANIFEST" | grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
    if [ -z "$VERSION" ]; then
        fail "Could not extract version from release manifest"
    fi
fi

info "ByteBuddhi Installer"
echo ""
echo "  Version:  ${VERSION}"
echo "  Platform: $(uname -s) $(uname -m)"
echo "  Target:   ${INSTALL_DIR}"
echo ""

# ── Download wheel ────────────────────────────────────────────────────

# PEP 440 drops the hyphen in pre-releases: 0.1.4-rc.1 -> 0.1.4rc1.
WHEEL_VERSION=$(printf '%s' "$VERSION" | sed -E 's/-rc\./rc/; s/-a\./a/; s/-b\./b/')
WHEEL_NAME="bytebuddhi-${WHEEL_VERSION}-py3-none-any.whl"
CHECKSUMS_URL="${BASE_URL}/download/v${VERSION}/SHA256SUMS"
WHEEL_URL="${BASE_URL}/download/v${VERSION}/${WHEEL_NAME}"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

info "Downloading release …"
curl -fsSL -o "${TMPDIR}/${WHEEL_NAME}" "$WHEEL_URL" || fail "Download failed"
ok "Downloaded ${WHEEL_NAME}"

info "Verifying integrity …"
curl -fsSL -o "${TMPDIR}/SHA256SUMS" "$CHECKSUMS_URL" || fail "Could not fetch checksums"
EXPECTED=$(grep "${WHEEL_NAME}" "${TMPDIR}/SHA256SUMS" | awk '{print $1}')
if [ -z "$EXPECTED" ]; then
    fail "Wheel not found in SHA256SUMS"
fi
sha256_check "${TMPDIR}/${WHEEL_NAME}" "$EXPECTED"
ok "Verified SHA-256"

# ── Install into versioned venv ───────────────────────────────────────

VENV_DIR="${INSTALL_DIR}/installs/${VERSION}"

info "Installing into ${VENV_DIR} …"
mkdir -p "${VENV_DIR}"

RUNTIME_INFO=$(get_managed_runtime)
RUNTIME_MODE="${RUNTIME_INFO%%:*}"
RUNTIME_EXE="${RUNTIME_INFO#*:}"

if [ "$RUNTIME_MODE" = "uv" ]; then
    "$RUNTIME_EXE" venv "${VENV_DIR}" --python 3.13
    "$RUNTIME_EXE" pip install --python "${VENV_DIR}" --quiet "${TMPDIR}/${WHEEL_NAME}"
else
    "$RUNTIME_EXE" -m venv "${VENV_DIR}"
    "${VENV_DIR}/bin/pip" install --quiet "${TMPDIR}/${WHEEL_NAME}"
fi
ok "Installed"

# ── Activate + launcher ──────────────────────────────────────────────

mkdir -p "${BIN_DIR}"
echo "${VERSION}" > "${INSTALL_DIR}/current"

cat > "${BIN_DIR}/bytebuddhi" << 'SHIM'
#!/bin/sh
set -e
BASE_DIR="$(dirname "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")")"
VERSION=$(cat "$BASE_DIR/current" | tr -d '\n')
exec "$BASE_DIR/installs/$VERSION/bin/bytebuddhi" "$@"
SHIM
chmod +x "${BIN_DIR}/bytebuddhi"
ok "Created launcher"

# ── Verify ────────────────────────────────────────────────────────────

INSTALLED_VERSION=$("${BIN_DIR}/bytebuddhi" --version 2>/dev/null | awk '{print $NF}') || true
if [ "$INSTALLED_VERSION" = "$VERSION" ]; then
    ok "Verified bytebuddhi --version"
else
    fail "Version verification failed: expected ${VERSION}, got ${INSTALLED_VERSION:-<empty>}"
fi

# ── PATH guidance ─────────────────────────────────────────────────────

echo ""
info "ByteBuddhi ${VERSION} is ready."
echo ""

if ! echo "$PATH" | tr ':' '\n' | grep -qxF "$BIN_DIR"; then
    echo "  Add this to your shell profile:"
    echo ""
    echo "    export PATH=\"${BIN_DIR}:\$PATH\""
    echo ""
fi
