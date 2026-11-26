#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
rm -rf release

./package_release.sh

test -s release/pmm-loss-exit-overlay.tar.gz
test -s release/pmm-loss-exit-overlay.tar.gz.sha256

paths=(
  controllers/generic/pmm_mister.py
  controllers/generic/pmm_mister_loss_exit.py
  controllers/generic/pmm_mister_loss_exit.example.yml
  hummingbot/data_feed/market_data_provider.py
  hummingbot/strategy_v2/controllers/loss_exit_recovery.py
  hummingbot/strategy_v2/executors/executor_orchestrator.py
  hummingbot/strategy_v2/executors/position_executor/data_types.py
  hummingbot/strategy_v2/executors/position_executor/loss_exit.py
  hummingbot/strategy_v2/executors/position_executor/position_executor.py
  hummingbot/strategy_v2/models/executor_actions.py
)

for path in "${paths[@]}"; do
  tar -tzf release/pmm-loss-exit-overlay.tar.gz | grep -Fx "home/hummingbot/$path" >/dev/null
done

tar -tzf release/pmm-loss-exit-overlay.tar.gz | grep -Fx "install_loss_exit.sh" >/dev/null
tar -tzf release/pmm-loss-exit-overlay.tar.gz | grep -Fx "README.md" >/dev/null

printf 'release package tests: PASS\n'

# Installer tests with a mocked Docker CLI.
mock_root="$ROOT/.tmp-installer-test"
rm -rf "$mock_root"
mkdir -p "$mock_root/bin" "$mock_root/backups"
mock_log="$mock_root/docker.log"
: > "$mock_log"

cat > "$mock_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$MOCK_DOCKER_LOG"
command_name="$1"
shift
case "$command_name" in
  inspect)
    if [[ "${MOCK_CONTAINER_EXISTS:-1}" != "1" ]]; then
      exit 1
    fi
    if [[ "${1:-}" == "--format" ]]; then
      printf 'true\n'
    else
      printf '{"name":"mock"}\n'
    fi
    ;;
  exec)
    if [[ "$*" == *"/hummingbot/VERSION"* ]]; then
      printf '%s\n' "${MOCK_VERSION:-2.18.0}"
    elif [[ "$*" == *"py_compile"* ]]; then
      exit "${MOCK_IMPORT_STATUS:-0}"
    else
      exit 0
    fi
    ;;
  stop|cp|start)
    exit "${MOCK_DOCKER_ACTION_STATUS:-0}"
    ;;
  *)
    exit 1
    ;;
esac
EOF
chmod +x "$mock_root/bin/docker"

export MOCK_DOCKER_LOG="$mock_log"
export PATH="$mock_root/bin:$PATH"
export BACKUP_ROOT="$mock_root/backups"

# No --yes and explicit dry-run must not stop, copy, or start.
./install_loss_exit.sh --container hummingbot >/dev/null
./install_loss_exit.sh --container hummingbot --dry-run >/dev/null
if grep -E '^(stop|cp|start) ' "$mock_log" >/dev/null; then
  printf 'dry-run changed the container\n' >&2
  exit 1
fi

# Missing containers must be rejected before stop.
: > "$mock_log"
if MOCK_CONTAINER_EXISTS=0 ./install_loss_exit.sh --container missing --yes >/dev/null 2>&1; then
  printf 'missing container was accepted\n' >&2
  exit 1
fi
if grep -E '^(stop|cp|start) ' "$mock_log" >/dev/null; then
  printf 'missing container was stopped\n' >&2
  exit 1
fi

# Version mismatch must be rejected before stop.
: > "$mock_log"
if MOCK_VERSION=2.16.0 ./install_loss_exit.sh --container old-version --yes >/dev/null 2>&1; then
  printf 'old version was accepted\n' >&2
  exit 1
fi
if grep -E '^(stop|cp|start) ' "$mock_log" >/dev/null; then
  printf 'old version container was stopped\n' >&2
  exit 1
fi

# Hummingbot 2.17.0 is accepted for update, copy, start, and backup.
: > "$mock_log"
MOCK_VERSION=2.17.0 ./install_loss_exit.sh --container hummingbot --yes >/dev/null
grep '^stop ' "$mock_log" >/dev/null
grep '^cp ' "$mock_log" >/dev/null
grep '^start ' "$mock_log" >/dev/null
find "$BACKUP_ROOT" -name container-inspect.json | grep . >/dev/null

# Import failure triggers a second stop/start pair for rollback.
: > "$mock_log"
if MOCK_IMPORT_STATUS=1 ./install_loss_exit.sh --container hummingbot --yes >/dev/null 2>&1; then
  printf 'import failure was reported as success\n' >&2
  exit 1
fi
[[ "$(grep -c '^stop ' "$mock_log")" -eq 2 ]]
[[ "$(grep -c '^start ' "$mock_log")" -eq 2 ]]

rm -rf "$mock_root"
printf 'installer mock tests: PASS\n'
