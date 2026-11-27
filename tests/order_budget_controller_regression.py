from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from controllers.generic.pmm_mister_loss_exit import PMMisterLossExit, PMMisterLossExitConfig
from hummingbot.core.data_type.common import OrderType, TradeType
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
    controller.recovery_state = "DISABLED"
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


def add_open_tp(controller, entry_side, price):
    controller.executors_info.append(SimpleNamespace(
        config=SimpleNamespace(side=entry_side),
        custom_info={
            "take_profit_order_open": True,
            "take_profit_order_price": str(price),
        },
    ))


def test_expected_tp_conflicts_only_with_same_direction_open_tps():
    OrderBudgetGuard.reset()
    config = make_config(
        tp_order_distance_tolerance_pct="0.001",
        take_profit="0.01",
    )
    controller = make_controller(config)

    # BUY at 100 creates a SELL TP at 101. The existing SELL TP at 100.95
    # is outside the entry-price tolerance but inside the expected-TP tolerance.
    add_open_tp(controller, TradeType.BUY, Decimal("100.95"))
    assert controller.get_executor_config("buy_0", Decimal("100"), Decimal("1")) is None

    controller.executors_info = []
    add_open_tp(controller, TradeType.SELL, Decimal("99.05"))
    assert controller.get_executor_config("sell_0", Decimal("100"), Decimal("1")) is None


def test_expected_tp_ignores_opposite_direction_open_tps():
    OrderBudgetGuard.reset()
    controller = make_controller(make_config(
        tp_order_distance_tolerance_pct="0.001",
        take_profit="0.01",
    ))
    add_open_tp(controller, TradeType.SELL, Decimal("100.95"))

    assert controller.get_executor_config("buy_0", Decimal("100"), Decimal("1")) is not None


def test_entry_tp_distance_boundary_and_disable_behavior():
    OrderBudgetGuard.reset()
    controller = make_controller(make_config(
        tp_order_distance_tolerance_pct="0.001",
        take_profit="0.01",
    ))
    add_open_tp(controller, TradeType.BUY, Decimal("100.05"))
    assert controller.get_executor_config("buy_0", Decimal("100"), Decimal("1")) is None

    controller.executors_info = []
    add_open_tp(controller, TradeType.BUY, Decimal("1000"))
    assert not controller._is_tp_distance_conflict(Decimal("1001"), TradeType.SELL)

    controller.config.tp_order_distance_tolerance_pct = Decimal("0")
    add_open_tp(controller, TradeType.BUY, Decimal("100"))
    assert controller.get_executor_config("buy_0", Decimal("100"), Decimal("1")) is not None


def test_market_take_profit_skips_expected_tp_distance_check():
    OrderBudgetGuard.reset()
    controller = make_controller(make_config(
        tp_order_distance_tolerance_pct="0.001",
        take_profit="0.01",
        take_profit_order_type=OrderType.MARKET,
    ))
    add_open_tp(controller, TradeType.BUY, Decimal("100.95"))

    assert controller.get_executor_config("buy_0", Decimal("100"), Decimal("1")) is not None
