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
