#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

paths=(
  controllers/generic/pmm_mister.py
  controllers/generic/pmm_mister_loss_exit.py
  controllers/generic/pmm_mister_loss_exit.example.yml
  hummingbot/data_feed/market_data_provider.py
  hummingbot/connector/exchange/binance/binance_order_recovery.py
  hummingbot/cli/engine.py
  hummingbot/cli/commands/stop.py
  hummingbot/client/command/stop_command.py
  hummingbot/core/trading_core.py
  hummingbot/strategy/strategy_v2_base.py
  hummingbot/strategy_v2/controllers/order_budget.py
  hummingbot/strategy_v2/controllers/loss_exit_recovery.py
  hummingbot/strategy_v2/controllers/executor_recovery.py
  hummingbot/strategy_v2/controllers/recovery_coordinator.py
  hummingbot/strategy_v2/executors/executor_orchestrator.py
  hummingbot/strategy_v2/executors/position_executor/data_types.py
  hummingbot/strategy_v2/executors/position_executor/loss_exit.py
  hummingbot/strategy_v2/executors/position_executor/position_executor.py
  hummingbot/strategy_v2/executors/position_executor/recovery.py
  hummingbot/strategy_v2/models/executor_actions.py
  scripts/condor_recovery_check.py
  scripts/condor_bootstrap_recovery.py
)

for path in "${paths[@]}"; do
  if [[ ! -f "$path" ]]; then
    printf 'Missing required source file: %s\n' "$path" >&2
    exit 1
  fi
done

for path in install_loss_exit.sh README.md; do
  if [[ ! -f "$path" ]]; then
    printf 'Missing required release file: %s\n' "$path" >&2
    exit 1
  fi
done

work_dir="release/work"
rm -rf "$work_dir"
mkdir -p "$work_dir/home/hummingbot"

for path in "${paths[@]}"; do
  cp --parents "$path" "$work_dir/home/hummingbot/"
done
cp install_loss_exit.sh README.md "$work_dir/"

tar -czf release/pmm-loss-exit-overlay.tar.gz -C "$work_dir" home install_loss_exit.sh README.md
sha256sum release/pmm-loss-exit-overlay.tar.gz > release/pmm-loss-exit-overlay.tar.gz.sha256
rm -rf "$work_dir"

printf 'Created %s\n' "release/pmm-loss-exit-overlay.tar.gz"
