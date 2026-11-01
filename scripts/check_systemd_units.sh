#!/usr/bin/env bash
#
# Verify systemd unit files under systemd/ for syntax-level errors.
#
# Only unknown keys/sections/lvalues and malformed lines fail the check.
# Other systemd-analyze findings (missing ExecStart binaries, %h paths,
# unknown dependency units) are ignored because they reference host paths.
#
# Usage:
#   bash scripts/check_systemd_units.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PATTERN="Unknown key|Unknown section|Unknown lvalue|Invalid section|Missing '='"

if ! command -v systemd-analyze >/dev/null 2>&1; then
    echo "SKIP: systemd-analyze not found on PATH"
    exit 0
fi

shopt -s nullglob
units=("$PROJECT_DIR"/systemd/*.service)
shopt -u nullglob

failed=0
for unit in "${units[@]}"; do
    name="$(basename "$unit")"
    output="$(systemd-analyze verify "$unit" 2>&1 || true)"
    matches="$(grep -E "$PATTERN" <<<"$output" || true)"
    if [[ -n "$matches" ]]; then
        while IFS= read -r line; do
            echo "$name: $line"
        done <<<"$matches"
        failed=1
    fi
done

if (( failed )); then
    exit 1
fi

echo "OK: ${#units[@]} unit files checked"
