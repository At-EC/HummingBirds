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
COPY hummingbot/strategy_v2/controllers/order_budget.py hummingbot/strategy_v2/controllers/order_budget.py
COPY hummingbot/strategy_v2/controllers/loss_exit_recovery.py hummingbot/strategy_v2/controllers/loss_exit_recovery.py
COPY hummingbot/strategy_v2/executors/executor_orchestrator.py hummingbot/strategy_v2/executors/executor_orchestrator.py
COPY hummingbot/strategy_v2/executors/position_executor/data_types.py hummingbot/strategy_v2/executors/position_executor/data_types.py
COPY hummingbot/strategy_v2/executors/position_executor/loss_exit.py hummingbot/strategy_v2/executors/position_executor/loss_exit.py
COPY hummingbot/strategy_v2/executors/position_executor/position_executor.py hummingbot/strategy_v2/executors/position_executor/position_executor.py
COPY hummingbot/strategy_v2/models/executor_actions.py hummingbot/strategy_v2/models/executor_actions.py

RUN /opt/conda/envs/hummingbot/bin/python -m py_compile \
    controllers/generic/pmm_mister.py \
    controllers/generic/pmm_mister_loss_exit.py \
    hummingbot/data_feed/market_data_provider.py \
    hummingbot/strategy_v2/controllers/order_budget.py \
    hummingbot/strategy_v2/controllers/loss_exit_recovery.py \
    hummingbot/strategy_v2/executors/executor_orchestrator.py \
    hummingbot/strategy_v2/executors/position_executor/data_types.py \
    hummingbot/strategy_v2/executors/position_executor/loss_exit.py \
    hummingbot/strategy_v2/executors/position_executor/position_executor.py \
    hummingbot/strategy_v2/models/executor_actions.py
