#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bots/controllers/generic" "$TMP/bots/conf/controllers"
cat > "$TMP/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_DOCKER_LOG"
if [[ "$*" == *"CONTROLLER_PRESENT"* ]]; then
  printf 'CONTROLLER_PRESENT True\nCONFIG_PRESENT True\n'
fi
EOF
chmod +x "$TMP/docker"
export MOCK_DOCKER_LOG="$TMP/docker.log"
export PATH="$TMP:$PATH"
export CONDOR_BOTS_DIR="$TMP/bots"
export CONDOR_API_CONTAINER=hummingbot-api

output="$("$ROOT/scripts/setup_condor.sh")"
printf '%s\n' "$output"

test -f "$TMP/bots/controllers/generic/pmm_mister_loss_exit.py"
test -f "$TMP/bots/conf/controllers/pmm_mister_loss_exit_sample.yml"
test ! -e "$TMP/bots/controllers/generic/pmm_mister.py"
grep 'CONFIG_PRESENT True' <<< "$output" >/dev/null
grep 'CONTROLLER_PRESENT True' <<< "$output" >/dev/null
