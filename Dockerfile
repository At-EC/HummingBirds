# Docker Hub's version-2.17.0 tag currently contains dev-2.18.0.
# Pin the verified Hummingbot 2.17.0 image instead of a mutable tag.
ARG HB_IMAGE=hummingbot/hummingbot@sha256:b676cb7279ca147b76a510777abf515a0d2f1b17e45a70da4831bb03a587c8e1
FROM ${HB_IMAGE}

ARG HB_VERSION=2.17.0
ARG COMMIT=latest
LABEL branch=${HB_VERSION} commit=${COMMIT}

COPY controllers/generic/pmm_mister.py controllers/generic/pmm_mister.py
COPY controllers/generic/pmm_mister_loss_exit.py controllers/generic/pmm_mister_loss_exit.py
COPY controllers/generic/pmm_mister_loss_exit.example.yml controllers/generic/pmm_mister_loss_exit.example.yml
COPY hummingbot/data_feed/market_data_provider.py hummingbot/data_feed/market_data_provider.py
COPY hummingbot/connector/exchange/binance/binance_order_recovery.py hummingbot/connector/exchange/binance/binance_order_recovery.py
COPY hummingbot/cli/engine.py hummingbot/cli/engine.py
COPY hummingbot/cli/commands/stop.py hummingbot/cli/commands/stop.py
COPY hummingbot/client/command/stop_command.py hummingbot/client/command/stop_command.py
COPY hummingbot/core/trading_core.py hummingbot/core/trading_core.py
COPY hummingbot/strategy/strategy_v2_base.py hummingbot/strategy/strategy_v2_base.py
COPY hummingbot/strategy_v2/controllers/order_budget.py hummingbot/strategy_v2/controllers/order_budget.py
COPY hummingbot/strategy_v2/controllers/loss_exit_recovery.py hummingbot/strategy_v2/controllers/loss_exit_recovery.py
COPY hummingbot/strategy_v2/controllers/executor_recovery.py hummingbot/strategy_v2/controllers/executor_recovery.py
COPY hummingbot/strategy_v2/controllers/recovery_coordinator.py hummingbot/strategy_v2/controllers/recovery_coordinator.py
COPY hummingbot/strategy_v2/executors/executor_orchestrator.py hummingbot/strategy_v2/executors/executor_orchestrator.py
COPY hummingbot/strategy_v2/executors/position_executor/data_types.py hummingbot/strategy_v2/executors/position_executor/data_types.py
COPY hummingbot/strategy_v2/executors/position_executor/loss_exit.py hummingbot/strategy_v2/executors/position_executor/loss_exit.py
COPY hummingbot/strategy_v2/executors/position_executor/position_executor.py hummingbot/strategy_v2/executors/position_executor/position_executor.py
COPY hummingbot/strategy_v2/executors/position_executor/recovery.py hummingbot/strategy_v2/executors/position_executor/recovery.py
COPY hummingbot/strategy_v2/models/executor_actions.py hummingbot/strategy_v2/models/executor_actions.py
COPY scripts/condor_recovery_check.py scripts/condor_recovery_check.py

RUN /opt/conda/envs/hummingbot/bin/python -m py_compile \
    controllers/generic/pmm_mister.py \
    controllers/generic/pmm_mister_loss_exit.py \
    hummingbot/data_feed/market_data_provider.py \
    hummingbot/connector/exchange/binance/binance_order_recovery.py \
    hummingbot/cli/engine.py \
    hummingbot/cli/commands/stop.py \
    hummingbot/client/command/stop_command.py \
    hummingbot/core/trading_core.py \
    hummingbot/strategy/strategy_v2_base.py \
    hummingbot/strategy_v2/controllers/order_budget.py \
    hummingbot/strategy_v2/controllers/loss_exit_recovery.py \
    hummingbot/strategy_v2/controllers/executor_recovery.py \
    hummingbot/strategy_v2/controllers/recovery_coordinator.py \
    hummingbot/strategy_v2/executors/executor_orchestrator.py \
    hummingbot/strategy_v2/executors/position_executor/data_types.py \
    hummingbot/strategy_v2/executors/position_executor/loss_exit.py \
    hummingbot/strategy_v2/executors/position_executor/position_executor.py \
    hummingbot/strategy_v2/executors/position_executor/recovery.py \
    hummingbot/strategy_v2/models/executor_actions.py \
    scripts/condor_recovery_check.py
