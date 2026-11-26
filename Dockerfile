ARG HB_VERSION=version-2.17.0
FROM hummingbot/hummingbot:${HB_VERSION}

ARG HB_VERSION
ARG COMMIT=latest
LABEL branch=${HB_VERSION} commit=${COMMIT}

COPY controllers/generic/pmm_mister.py controllers/generic/pmm_mister.py
COPY controllers/generic/pmm_mister_loss_exit.py controllers/generic/pmm_mister_loss_exit.py
COPY controllers/generic/pmm_mister_loss_exit.example.yml controllers/generic/pmm_mister_loss_exit.example.yml
COPY hummingbot/strategy_v2/controllers/loss_exit_recovery.py hummingbot/strategy_v2/controllers/loss_exit_recovery.py
COPY hummingbot/strategy_v2/executors/executor_orchestrator.py hummingbot/strategy_v2/executors/executor_orchestrator.py
COPY hummingbot/strategy_v2/executors/position_executor/data_types.py hummingbot/strategy_v2/executors/position_executor/data_types.py
COPY hummingbot/strategy_v2/executors/position_executor/loss_exit.py hummingbot/strategy_v2/executors/position_executor/loss_exit.py
COPY hummingbot/strategy_v2/executors/position_executor/position_executor.py hummingbot/strategy_v2/executors/position_executor/position_executor.py
COPY hummingbot/strategy_v2/models/executor_actions.py hummingbot/strategy_v2/models/executor_actions.py

RUN /opt/conda/envs/hummingbot/bin/python -m py_compile \
    controllers/generic/pmm_mister.py \
    controllers/generic/pmm_mister_loss_exit.py \
    hummingbot/strategy_v2/controllers/loss_exit_recovery.py \
    hummingbot/strategy_v2/executors/executor_orchestrator.py \
    hummingbot/strategy_v2/executors/position_executor/data_types.py \
    hummingbot/strategy_v2/executors/position_executor/loss_exit.py \
    hummingbot/strategy_v2/executors/position_executor/position_executor.py \
    hummingbot/strategy_v2/models/executor_actions.py
