#!/bin/sh
set -eu

OPTIONS_FILE="/data/options.json"
DATA_DIR="/data/wealthfolio"
SECRET_FILE="/data/.wf_secret_key"

APP_DIR="/app"
SERVER="/usr/local/bin/wealthfolio-server"

WEALTHFOLIO_USER="wealthfolio"
WEALTHFOLIO_GROUP="wealthfolio"


log() {
    printf '%s\n' "[wealthfolio] $*"
}


fail() {
    printf '%s\n' "[wealthfolio] ERROR: $*" >&2
    exit 1
}


read_required_string() {
    key="$1"

    jq -er \
        --arg key "$key" \
        '.[$key] | select(type == "string" and length > 0)' \
        "$OPTIONS_FILE" 2>/dev/null
}


data_exists() {
    [ -d "$DATA_DIR" ] || return 1

    data_entries="$(ls -A "$DATA_DIR" 2>/dev/null)" \
        || fail "Unable to inspect the Wealthfolio data directory."

    [ -n "$data_entries" ]
}


generate_secret_key() {
    old_umask="$(umask)"
    umask 077

    # A power loss can leave a temporary key from an interrupted first boot.
    # No Wealthfolio data can have been created with it because the server is
    # started only after the final key has been persisted.
    rm -f "${SECRET_FILE}.tmp."* \
        || fail "Unable to remove stale temporary master-key files."

    secret_tmp="$(mktemp "${SECRET_FILE}.tmp.XXXXXX")" \
        || fail "Unable to create a temporary master-key file."

    cleanup_secret_tmp() {
        [ -n "${secret_tmp:-}" ] && rm -f "$secret_tmp"
    }

    trap cleanup_secret_tmp 0
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM

    if ! openssl rand -base64 32 > "$secret_tmp"; then
        fail "Unable to generate the Wealthfolio master key."
    fi

    [ -s "$secret_tmp" ] \
        || fail "Generated Wealthfolio master key is empty."

    generated_key="$(cat "$secret_tmp")"

    decoded_size="$(
        printf '%s' "$generated_key" \
            | openssl base64 -d -A 2>/dev/null \
            | wc -c
    )"

    [ "$decoded_size" -eq 32 ] \
        || fail "Generated Wealthfolio master key did not decode to 32 bytes."

    chown 0:0 "$secret_tmp" \
        || fail "Unable to set ownership of the Wealthfolio master key."

    chmod 0600 "$secret_tmp" \
        || fail "Unable to protect the Wealthfolio master key."

    mv "$secret_tmp" "$SECRET_FILE" \
        || fail "Unable to persist the Wealthfolio master key."

    secret_tmp=""
    trap - 0 HUP INT TERM

    umask "$old_umask"

    log "Generated a new Wealthfolio master key."
}


# ---------------------------------------------------------------------------
# Validate Home Assistant configuration
# ---------------------------------------------------------------------------

[ -f "$OPTIONS_FILE" ] \
    || fail "Home Assistant options file was not found."

[ -r "$OPTIONS_FILE" ] \
    || fail "Home Assistant options file is not readable."

jq -e 'type == "object"' "$OPTIONS_FILE" >/dev/null 2>&1 \
    || fail "Home Assistant options file is not valid JSON."

AUTH_PASSWORD_HASH="$(read_required_string auth_password_hash)" \
    || fail "auth_password_hash is required."

CORS_ALLOW_ORIGINS="$(read_required_string cors_allow_origins)" \
    || fail "cors_allow_origins is required."

AUTH_TOKEN_TTL_MINUTES="$(
    jq -r '.auth_token_ttl_minutes // empty' "$OPTIONS_FILE"
)"

case "$AUTH_TOKEN_TTL_MINUTES" in
    ''|*[!0-9]*)
        fail "auth_token_ttl_minutes must be a positive integer."
        ;;
esac

[ "$AUTH_TOKEN_TTL_MINUTES" -gt 0 ] \
    || fail "auth_token_ttl_minutes must be greater than zero."

case "$CORS_ALLOW_ORIGINS" in
    *'*'*)
        fail "cors_allow_origins cannot contain the wildcard '*'."
        ;;
esac


# ---------------------------------------------------------------------------
# Validate persistent paths before privileged operations
# ---------------------------------------------------------------------------

[ ! -L "$DATA_DIR" ] \
    || fail "$DATA_DIR must not be a symbolic link."

if [ -e "$DATA_DIR" ] && [ ! -d "$DATA_DIR" ]; then
    fail "$DATA_DIR exists but is not a directory."
fi

[ ! -L "$SECRET_FILE" ] \
    || fail "$SECRET_FILE must not be a symbolic link."

if [ -e "$SECRET_FILE" ] && [ ! -f "$SECRET_FILE" ]; then
    fail "$SECRET_FILE exists but is not a regular file."
fi


# ---------------------------------------------------------------------------
# Restore or bootstrap the Wealthfolio master key
# ---------------------------------------------------------------------------

if [ -f "$SECRET_FILE" ]; then
    SECRET_KEY="$(cat "$SECRET_FILE")"

    [ -n "$SECRET_KEY" ] \
        || fail "The stored Wealthfolio master key is empty."

    # Restore ownership first so chmod does not require CAP_FOWNER.
    chown 0:0 "$SECRET_FILE" \
        || fail "Unable to set ownership of the stored Wealthfolio master key."

    chmod 0600 "$SECRET_FILE" \
        || fail "Unable to protect the stored Wealthfolio master key."

    log "Using the existing Wealthfolio master key."
else
    if data_exists; then
        fail "Existing Wealthfolio data was found but the master key is missing. Restore $SECRET_FILE from backup instead of generating a new key."
    fi

    generate_secret_key

    SECRET_KEY="$(cat "$SECRET_FILE")"

    [ -n "$SECRET_KEY" ] \
        || fail "Unable to reload the generated Wealthfolio master key."
fi


# ---------------------------------------------------------------------------
# Prepare Wealthfolio persistent storage
# ---------------------------------------------------------------------------

mkdir -p "$DATA_DIR" \
    || fail "Unable to create the Wealthfolio data directory."

chown -R \
    "${WEALTHFOLIO_USER}:${WEALTHFOLIO_GROUP}" \
    "$DATA_DIR" \
    || fail "Unable to set Wealthfolio data ownership."


# ---------------------------------------------------------------------------
# Pass dynamic configuration to Wealthfolio
# ---------------------------------------------------------------------------

export WF_SECRET_KEY="$SECRET_KEY"
export WF_AUTH_PASSWORD_HASH="$AUTH_PASSWORD_HASH"
export WF_CORS_ALLOW_ORIGINS="$CORS_ALLOW_ORIGINS"
export WF_AUTH_TOKEN_TTL_MINUTES="$AUTH_TOKEN_TTL_MINUTES"

# Never print the values above.


# ---------------------------------------------------------------------------
# Validate the upstream image layout
# ---------------------------------------------------------------------------

[ -d "$APP_DIR" ] \
    || fail "Wealthfolio application directory is missing."

[ -d "$APP_DIR/dist" ] \
    || fail "Wealthfolio frontend assets are missing."

[ -x "$SERVER" ] \
    || fail "Wealthfolio server binary is missing or not executable."


# ---------------------------------------------------------------------------
# Start Wealthfolio as its upstream non-root user
# ---------------------------------------------------------------------------

cd "$APP_DIR"

log "Starting Wealthfolio as ${WEALTHFOLIO_USER}:${WEALTHFOLIO_GROUP}."

exec su-exec \
    "${WEALTHFOLIO_USER}:${WEALTHFOLIO_GROUP}" \
    "$SERVER"