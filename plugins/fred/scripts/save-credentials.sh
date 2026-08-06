#!/usr/bin/env bash
# Store a FRED API key at ~/.fred-mcp/credentials.json. Backs the /fred:auth command.
#
# The key is read by this script, never by the agent. That is the whole reason this
# exists rather than the command simply asking for the key in chat: a key pasted into a
# conversation is in the transcript, in the context window, and in whatever the client
# persists, none of which the user can rotate away. Here it goes from an OS password
# prompt straight into a 0600 file, and nothing this script writes to stdout contains
# it.
#
# Re-running always overwrites, which is the rotation path.
#
#   save-credentials.sh              prompt, verify against FRED, write
#   save-credentials.sh --selftest   check the validator, touching nothing
set -euo pipefail

CRED_DIR="${FRED_CRED_DIR:-$HOME/.fred-mcp}"
CRED_FILE="$CRED_DIR/credentials.json"
SIGNUP="https://fredaccount.stlouisfed.org/apikeys"

# Same rule as src/client.py. Checked here so a bad paste is caught at the prompt
# rather than surfacing later as a FRED error about "variable api_key".
valid_key() {
    [[ "$1" =~ ^[a-z0-9]{32}$ ]]
}

if [ "${1:-}" = "--selftest" ]; then
    fail=0
    check() {
        if [ "$1" = yes ]; then valid_key "$2" || { echo "FAIL: should accept $3"; fail=1; }
        else valid_key "$2" && { echo "FAIL: should reject $3"; fail=1; } || true
        fi
    }
    check yes "0123456789abcdef0123456789abcdef" "a well-formed key"
    check no  "0123456789ABCDEF0123456789abcdef" "capitals"
    check no  "0123456789abcdef0123456789abcde"  "31 characters"
    check no  "0123456789abcdef0123456789abcdef0" "33 characters"
    check no  " 123456789abcdef0123456789abcdef" "a leading space"
    check no  "0123456789abcdef-123456789abcdef" "a hyphen"
    check no  ""                                 "an empty string"
    [ "$fail" -eq 0 ] && echo "save-credentials selftest ok"
    exit "$fail"
fi

PROMPT="Paste your FRED API key.

It is written only to $CRED_FILE on this computer.
Nothing is uploaded, and it is not shared with the agent.

Free key: $SIGNUP"

# Ask the OS, not the chat. Each branch returns the key on stdout and nothing else.
read_key() {
    if [ -n "${FRED_API_KEY_STDIN:-}" ]; then
        # Escape hatch for scripted setup; not used by the slash command.
        cat
    elif command -v osascript > /dev/null 2>&1; then
        # `with hidden answer` masks the field, so the key is not left on screen
        # either. A cancelled dialog exits non-zero and is handled below.
        osascript \
            -e "set r to display dialog \"$PROMPT\" default answer \"\" with hidden answer with title \"FRED API key\"" \
            -e 'return text returned of r' 2> /dev/null
    elif command -v zenity > /dev/null 2>&1; then
        zenity --password --title="FRED API key" 2> /dev/null
    elif command -v kdialog > /dev/null 2>&1; then
        kdialog --password "$PROMPT" 2> /dev/null
    elif [ -r /dev/tty ]; then
        # No GUI. Works when the script is run from a terminal directly; -s keeps the
        # key off the screen.
        printf '%s\n' "$PROMPT" > /dev/tty
        local typed
        IFS= read -r -s typed < /dev/tty
        printf '\n' > /dev/tty
        printf '%s' "$typed"
    else
        return 3
    fi
}

if ! key="$(read_key)"; then
    case "$?" in
        3) echo "error: no way to prompt for the key here (no osascript, zenity, kdialog, or terminal)." >&2
           echo "  Write it yourself: mkdir -p $CRED_DIR && echo '{\"api_key\": \"<key>\"}' > $CRED_FILE" >&2 ;;
        *) echo "cancelled: no key was entered, and $CRED_FILE was not changed." >&2 ;;
    esac
    exit 1
fi

key="$(printf '%s' "$key" | tr -d '[:space:]')"

if [ -z "$key" ]; then
    echo "cancelled: no key was entered, and $CRED_FILE was not changed." >&2
    exit 1
fi

if ! valid_key "$key"; then
    # Never echo the key or any part of it, not even a prefix.
    echo "error: that is not the shape of a FRED API key (32 lowercase alphanumeric characters)." >&2
    echo "  Check for stray whitespace, quotes, or capitals, and re-copy it from $SIGNUP." >&2
    echo "  $CRED_FILE was not changed." >&2
    exit 1
fi

# Verify before writing, so a bad paste cannot overwrite a working key during a
# rotation. stderr is discarded because curl's error text can echo the URL, and the
# key is a query parameter in it.
verified="unverified"
if command -v curl > /dev/null 2>&1; then
    status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -G \
        --data-urlencode "series_id=UNRATE" \
        --data-urlencode "api_key=$key" \
        --data-urlencode "file_type=json" \
        "https://api.stlouisfed.org/fred/series" 2> /dev/null || true)"
    case "$status" in
        200) verified="verified against FRED" ;;
        400) echo "error: FRED rejected that key. It may be mistyped or revoked." >&2
             echo "  Check it at $SIGNUP. $CRED_FILE was not changed." >&2
             exit 1 ;;
        *)   verified="written but not verified (no answer from FRED; status ${status:-none})" ;;
    esac
fi

umask 077
mkdir -p "$CRED_DIR"
printf '{"api_key": "%s"}\n' "$key" > "$CRED_FILE"
chmod 600 "$CRED_FILE"

echo "Saved to $CRED_FILE ($verified)."
echo "Permissions are 0600, owner-only. Re-run /fred:auth any time to replace it."
