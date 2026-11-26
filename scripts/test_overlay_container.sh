#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
CONTAINER="loss-exit-overlay-test-$$"
BACKUP_ROOT="$ROOT/.tmp-overlay-backups"
TEST_IMAGE="${TEST_IMAGE:-hummingbot/pmm-mister-loss-exit:v2.18.0}"
export STOP_TIMEOUT="${STOP_TIMEOUT:-5}"
SOURCE_FILE="controllers/generic/pmm_mister_loss_exit.py"
ORIGINAL="$ROOT/.tmp-original-loss-exit.py"

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  if [[ -f "$ORIGINAL" ]]; then
    cp "$ORIGINAL" "$SOURCE_FILE"
    rm -f "$ORIGINAL"
  fi
  rm -rf "$BACKUP_ROOT"
}
trap cleanup EXIT

rm -rf "$BACKUP_ROOT"
docker run -d --name "$CONTAINER" \
  --entrypoint /opt/conda/envs/hummingbot/bin/python \
  "$TEST_IMAGE" \
  -c 'import time; time.sleep(3600)' >/dev/null

[[ "$(docker inspect --format '{{.State.Running}}' "$CONTAINER")" == "true" ]]

BACKUP_ROOT="$BACKUP_ROOT" ./install_loss_exit.sh --container "$CONTAINER" --yes
BACKUP_ROOT="$BACKUP_ROOT" ./install_loss_exit.sh --container "$CONTAINER" --yes
docker exec "$CONTAINER" test -f /home/hummingbot/hummingbot/data_feed/market_data_provider.py
docker exec "$CONTAINER" test -f /home/hummingbot/hummingbot/strategy_v2/controllers/order_budget.py

cp "$SOURCE_FILE" "$ORIGINAL"
printf 'def invalid_python(:\n' > "$SOURCE_FILE"
if BACKUP_ROOT="$BACKUP_ROOT" ./install_loss_exit.sh --container "$CONTAINER" --yes >/dev/null 2>&1; then
  printf 'broken source unexpectedly installed successfully\n' >&2
  exit 1
fi

[[ "$(docker inspect --format '{{.State.Running}}' "$CONTAINER")" == "true" ]]
docker exec --workdir /home/hummingbot "$CONTAINER" \
  /opt/conda/envs/hummingbot/bin/python -c \
  'from controllers.generic.pmm_mister_loss_exit import PMMisterLossExit; print(PMMisterLossExit.__name__)' >/dev/null

printf 'real container overlay and rollback tests: PASS\n'
