#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER_NAME="${CONTAINER_NAME:-hummingbot}"
CONTAINER_HOME="${CONTAINER_HOME:-/home/hummingbot}"
STOP_TIMEOUT="${STOP_TIMEOUT:-60}"
ALLOW_VERSION_MISMATCH="${ALLOW_VERSION_MISMATCH:-0}"
BACKUP_ROOT="${BACKUP_ROOT:-$PWD/loss-exit-backups}"
CONFIRM=0

paths=(
  controllers/generic/pmm_mister.py
  controllers/generic/pmm_mister_loss_exit.py
  controllers/generic/pmm_mister_loss_exit.example.yml
  hummingbot/strategy_v2/controllers/loss_exit_recovery.py
  hummingbot/strategy_v2/executors/executor_orchestrator.py
  hummingbot/strategy_v2/executors/position_executor/data_types.py
  hummingbot/strategy_v2/executors/position_executor/loss_exit.py
  hummingbot/strategy_v2/executors/position_executor/position_executor.py
  hummingbot/strategy_v2/models/executor_actions.py
)

usage() {
  cat <<'EOF'
Usage: ./install_loss_exit.sh [--container NAME] [--dry-run] [--yes]

--container NAME  Container to update (default: hummingbot)
--dry-run         Validate and print the plan without changing the container
--yes             Stop, update, restart, and verify the original container

Environment: CONTAINER_HOME, STOP_TIMEOUT, BACKUP_ROOT, ALLOW_VERSION_MISMATCH=1
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --container)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      CONTAINER_NAME="$2"
      shift 2
      ;;
    --dry-run)
      CONFIRM=0
      shift
      ;;
    --yes)
      CONFIRM=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -d "$SCRIPT_DIR/home/hummingbot" ]]; then
  SOURCE_ROOT="$SCRIPT_DIR/home/hummingbot"
else
  SOURCE_ROOT="$SCRIPT_DIR"
fi

for path in "${paths[@]}"; do
  if [[ ! -f "$SOURCE_ROOT/$path" ]]; then
    printf 'Missing source file: %s\n' "$SOURCE_ROOT/$path" >&2
    exit 1
  fi
done

if ! command -v docker >/dev/null 2>&1; then
  printf 'Docker CLI is required.\n' >&2
  exit 1
fi

if ! running="$(docker inspect --format '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null)"; then
  printf 'Container not found or Docker is unavailable: %s\n' "$CONTAINER_NAME" >&2
  exit 1
fi
if [[ "$running" != "true" ]]; then
  printf 'Container is not running: %s\n' "$CONTAINER_NAME" >&2
  exit 1
fi

version="$(docker exec "$CONTAINER_NAME" cat "$CONTAINER_HOME/hummingbot/VERSION")"
version="${version//$'\r'/}"
if [[ "$version" != "2.17.0" && "$version" != "2.18.0" && "$ALLOW_VERSION_MISMATCH" != "1" ]]; then
  printf 'Unsupported Hummingbot version %s (expected 2.17.0 or 2.18.0).\n' "$version" >&2
  printf 'Set ALLOW_VERSION_MISMATCH=1 only after reviewing compatibility.\n' >&2
  exit 1
fi

printf 'Container: %s\nHummingbot: %s\nSource: %s\n' "$CONTAINER_NAME" "$version" "$SOURCE_ROOT"
printf 'Runtime files: %d\n' "${#paths[@]}"

if [[ "$CONFIRM" != "1" ]]; then
  printf 'Dry run only. Re-run with --yes to stop, update, restart, and verify.\n'
  exit 0
fi

backup_dir="$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$backup_dir/files"
docker inspect "$CONTAINER_NAME" > "$backup_dir/container-inspect.json"
: > "$backup_dir/added-files.txt"

for path in "${paths[@]}"; do
  if docker exec "$CONTAINER_NAME" test -f "$CONTAINER_HOME/$path"; then
    mkdir -p "$backup_dir/files/$(dirname "$path")"
    docker cp "$CONTAINER_NAME:$CONTAINER_HOME/$path" "$backup_dir/files/$path"
  else
    printf '%s\n' "$path" >> "$backup_dir/added-files.txt"
  fi
done
printf 'Backup: %s\n' "$backup_dir"

rollback() {
  status=$?
  trap - ERR
  set +e
  printf 'Update failed; restoring backup from %s\n' "$backup_dir" >&2
  docker stop --timeout "$STOP_TIMEOUT" "$CONTAINER_NAME" >/dev/null 2>&1
  for path in "${paths[@]}"; do
    if [[ -f "$backup_dir/files/$path" ]]; then
      docker cp "$backup_dir/files/$path" "$CONTAINER_NAME:$CONTAINER_HOME/$path" >/dev/null 2>&1
    fi
  done
  docker start "$CONTAINER_NAME" >/dev/null 2>&1
  while IFS= read -r path; do
    [[ -n "$path" ]] && docker exec "$CONTAINER_NAME" rm -f "$CONTAINER_HOME/$path" >/dev/null 2>&1
  done < "$backup_dir/added-files.txt"
  exit "$status"
}

trap rollback ERR

docker stop --timeout "$STOP_TIMEOUT" "$CONTAINER_NAME"
for path in "${paths[@]}"; do
  docker cp "$SOURCE_ROOT/$path" "$CONTAINER_NAME:$CONTAINER_HOME/$path"
done
docker start "$CONTAINER_NAME"

compile_files=()
for path in "${paths[@]}"; do
  [[ "$path" == *.py ]] && compile_files+=("$CONTAINER_HOME/$path")
done

docker exec "$CONTAINER_NAME" /opt/conda/envs/hummingbot/bin/python -m py_compile "${compile_files[@]}"
docker exec --workdir "$CONTAINER_HOME" "$CONTAINER_NAME" \
  /opt/conda/envs/hummingbot/bin/python -c \
  'from controllers.generic.pmm_mister_loss_exit import PMMisterLossExit, PMMisterLossExitConfig; print(PMMisterLossExit.__name__)'

trap - ERR
printf 'Update verified successfully. Backup retained at %s\n' "$backup_dir"
printf 'Next: configure and validate pmm_mister_loss_exit in paper trade before live use.\n'
