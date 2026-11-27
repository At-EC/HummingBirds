import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

from hummingbot.cli.commands.stop import stop
from hummingbot.cli.engine import _serve


def test_stop_defaults_to_sigterm():
    with patch("hummingbot.cli.commands.stop.bot") as bot, \
            patch("hummingbot.cli.commands.stop.os.kill") as kill, \
            patch("hummingbot.cli.commands.stop.time.time", side_effect=[0, 1]), \
            patch("hummingbot.cli.commands.stop.bot.pid_alive", return_value=False):
        bot.read_pid.return_value = 123
        bot.is_engine_pid.return_value = True
        stop(timeout=30.0, force=False, as_json=False, keep_open_orders=False)
        kill.assert_called_once_with(123, signal.SIGTERM)


def test_keep_open_orders_uses_sigusr2():
    with patch("hummingbot.cli.commands.stop.bot") as bot, \
            patch("hummingbot.cli.commands.stop.os.kill") as kill, \
            patch("hummingbot.cli.commands.stop.time.time", side_effect=[0, 1]), \
            patch("hummingbot.cli.commands.stop.bot.pid_alive", return_value=False):
        bot.read_pid.return_value = 123
        bot.is_engine_pid.return_value = True
        stop(timeout=30.0, force=False, as_json=False, keep_open_orders=True)
        kill.assert_called_once_with(123, signal.SIGUSR2)


def run_serve(trigger):
    loop = MagicMock()
    loop.add_signal_handler.side_effect = lambda sig, callback: callback() if sig == trigger else None
    hb = MagicMock()
    hb.stop_loop = AsyncMock()
    hb.trading_core.shutdown = AsyncMock()
    with patch("hummingbot.cli.engine.asyncio.get_event_loop", return_value=loop), \
            patch("hummingbot.cli.engine._write_snapshot", new=AsyncMock()), \
            patch("hummingbot.cli.engine.bot.clear_pid"):
        asyncio.run(asyncio.wait_for(_serve(hb, "demo"), timeout=1))
    return hb


def test_sigterm_still_cancels_orders():
    hb = run_serve(signal.SIGTERM)
    hb.stop_loop.assert_awaited_once_with(skip_order_cancellation=False)
    hb.trading_core.shutdown.assert_awaited_once_with(skip_order_cancellation=False)


def test_sigusr2_skips_order_cancellation():
    hb = run_serve(signal.SIGUSR2)
    hb.stop_loop.assert_awaited_once_with(skip_order_cancellation=True)
    hb.trading_core.shutdown.assert_awaited_once_with(skip_order_cancellation=True)


from hummingbot.strategy.strategy_v2_base import StrategyV2Base
from hummingbot.strategy_v2.executors.executor_orchestrator import ExecutorOrchestrator
from hummingbot.strategy_v2.models.base import RunnableStatus


def test_v2_strategy_forwards_keep_open_orders_to_orchestrator():
    async def run_test():
        orchestrator = MagicMock()
        orchestrator.stop = AsyncMock()
        factory = MagicMock(return_value=orchestrator)
        with patch(
            "hummingbot.strategy.strategy_v2_base._get_executor_orchestrator_class",
            return_value=factory,
        ):
            strategy = StrategyV2Base(connectors={})
        strategy.controllers = {}
        strategy.listen_to_executor_actions_task = None
        strategy.max_executors_close_attempts = 3
        strategy.executor_orchestrator = orchestrator
        strategy.market_data_provider = MagicMock()
        strategy.mqtt_enabled = False

        await strategy.on_stop(skip_order_cancellation=True)

        strategy.executor_orchestrator.stop.assert_awaited_once_with(
            3, skip_order_cancellation=True
        )

    asyncio.run(run_test())


def test_orchestrator_keep_open_orders_stops_without_early_stop():
    controller = MagicMock()
    executor = MagicMock()
    executor.is_closed = False
    executor.status = RunnableStatus.RUNNING
    orchestrator = object.__new__(ExecutorOrchestrator)
    orchestrator.active_executors = {"bot-a": [executor]}
    orchestrator.strategy = MagicMock()
    orchestrator.strategy.controllers = {"bot-a": controller}
    orchestrator.store_all_positions = MagicMock()
    orchestrator.store_all_executors = MagicMock()
    orchestrator.logger = MagicMock(return_value=MagicMock())

    asyncio.run(orchestrator.stop(skip_order_cancellation=True))

    executor.early_stop.assert_not_called()
    executor.stop.assert_called_once()
    controller.persist_recovery_snapshots.assert_called_once()
