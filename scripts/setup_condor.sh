#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOTS="${CONDOR_BOTS_DIR:-/root/hummingbot-api/bots}"
API="${CONDOR_API_CONTAINER:-hummingbot-api}"
CONTROLLER_SRC="$ROOT/controllers/generic/pmm_mister_loss_exit.py"
CONFIG_SRC="$ROOT/agents/_shared/skills/pmm_mister_loss_exit/pmm_mister_loss_exit.sample.yml"
CONTROLLER_DST="$BOTS/controllers/generic/pmm_mister_loss_exit.py"
CONFIG_DST="$BOTS/conf/controllers/pmm_mister_loss_exit_sample.yml"

mkdir -p "$(dirname "$CONTROLLER_DST")" "$(dirname "$CONFIG_DST")"
cp "$CONTROLLER_SRC" "$CONTROLLER_DST"
cp "$CONFIG_SRC" "$CONFIG_DST"

docker exec "$API" python -c \
  'from utils.file_system import fs_util; c=[f for f in fs_util.list_files("controllers/generic") if f.endswith(".py")]; y=[f for f in fs_util.list_files("conf/controllers") if f.endswith(".yml")]; print("CONTROLLER_PRESENT", "pmm_mister_loss_exit.py" in c); print("CONFIG_PRESENT", "pmm_mister_loss_exit_sample.yml" in y); config=fs_util.read_yaml_file("conf/controllers/pmm_mister_loss_exit_sample.yml"); print("CONTROLLER", config.get("controller_name")); print("CONNECTOR", config.get("connector_name")); print("ORDER_TYPES", config.get("open_order_type"), config.get("take_profit_order_type"))'
printf 'IMAGE=hummingbot/pmm-mister-loss-exit:v2.17.0\n'
