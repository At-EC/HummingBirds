from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from controllers.generic.pmm_mister_loss_exit import PMMisterLossExit, PMMisterLossExitConfig
from hummingbot.strategy_v2.controllers.order_budget import OrderBudgetGuard
from hummingbot.strategy_v2.executors.position_executor.loss_exit import LossExitState


def make_config(**overrides):
    values = {
        "id": "bot-a",
        "controller_name": "pmm_mister_loss_exit",
        "controller_type": "generic",
        "connector_name": "binance_paper_trade",
        "trading_pair": "BTC-USDT",
    }
    values.update(overrides)
    return PMMisterLossExitConfig(**values)


def make_controller(config):
    controller = object.__new__(PMMisterLossExit)
    controller.config = config
    controller.market_data_provider = MagicMock()
    controller.market_data_provider.time.return_value = 100.0
    controller.executors_info = []
    controller._global_close_phase = None
    controller._loss_exit_runtime_owns_record = False
    return controller


def add_eligible_candidate(controller):
    controller.executors_info = [SimpleNamespace(
        id="executor-1",
        is_active=True,
        is_trading=True,
        custom_info={
            "loss_exit_state": LossExitState.ELIGIBLE.value,
            "take_profit_order_open": True,
            "loss_exit_lock_held": False,
            "loss_pct": "0.01",
            "eligible_since": 90.0,
            "last_successful_observation_at": 100.0,
        },
    )]


def test_budget_pause_blocks_new_executor_but_not_loss_exit_activation():
    OrderBudgetGuard.reset()
    config = make_config(min_order_amount_quote="10", no_budget_retry_seconds=300)
    controller = make_controller(config)
    add_eligible_candidate(controller)
    assert controller.get_executor_config("buy_0", Decimal("10"), Decimal("1")) is not None
    assert controller.get_executor_config("sell_0", Decimal("10"), Decimal("0.5")) is None
    assert controller.get_loss_exit_activation_action() is not None
    OrderBudgetGuard.note_no_budget(config.id, 100.0, 300, "no budget")
    assert controller.get_executor_config("buy_0", Decimal("10"), Decimal("1")) is None
    assert controller.get_loss_exit_activation_action() is not None


def test_config_is_forwarded_to_executor_config():
    OrderBudgetGuard.reset()
    controller = make_controller(make_config(min_order_amount_quote="12.5", no_budget_retry_seconds=45))
    executor_config = controller.get_executor_config("buy_0", Decimal("100"), Decimal("1"))
    assert executor_config.min_order_amount_quote == Decimal("12.5")
    assert executor_config.no_budget_retry_seconds == 45
    assert executor_config.controller_id == "bot-a"
