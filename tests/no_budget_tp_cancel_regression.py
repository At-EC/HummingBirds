from decimal import Decimal
import unittest
from unittest.mock import MagicMock

from controllers.generic.pmm_mister_loss_exit import PMMisterLossExitConfig
from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.controllers.order_budget import OrderBudgetGuard
from hummingbot.strategy_v2.executors.executor_orchestrator import ExecutorOrchestrator
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType
from hummingbot.strategy_v2.models.executor_actions import CancelTakeProfitAction
from order_budget_controller_regression import make_config, make_controller
from order_budget_executor_regression import make_executor


def add_tp(controller, executor_id, entry_side, price, lock=False):
    controller.executors_info.append(type("ExecutorInfo", (), {
        "id": executor_id,
        "config": type("Config", (), {"side": entry_side})(),
        "is_active": True,
        "is_trading": True,
        "custom_info": {
            "take_profit_order_open": True,
            "take_profit_order_price": str(price),
            "loss_exit_lock_held": lock,
            "no_budget_tp_cancel_requested": False,
        },
    })())


class NoBudgetTpCancelTests(unittest.TestCase):
    def setUp(self):
        OrderBudgetGuard.reset()
        self.config = make_config(no_budget_tp_cancel_distance_pct="0.05")
        self.controller = make_controller(self.config)
        self.controller.market_data_provider.get_price_by_type.return_value = Decimal("100")
        OrderBudgetGuard.note_no_budget(self.config.id, 100.0, 30, "no budget")

    def test_disabled_by_default(self):
        config = PMMisterLossExitConfig(
            id="bot-a", controller_name="pmm_mister_loss_exit", controller_type="generic",
            connector_name="binance", trading_pair="ZEC-USDT",
        )
        self.assertEqual(config.no_budget_tp_cancel_distance_pct, Decimal("0"))
        controller = make_controller(config)
        add_tp(controller, "old", TradeType.SELL, Decimal("50"))
        self.assertIsNone(controller.get_no_budget_tp_cancel_action())

    def test_farthest_tp_is_selected_across_both_sides(self):
        add_tp(self.controller, "buy-near", TradeType.SELL, Decimal("90"))
        add_tp(self.controller, "buy-far", TradeType.SELL, Decimal("80"))
        add_tp(self.controller, "sell-far", TradeType.BUY, Decimal("120"))
        add_tp(self.controller, "buy-wrong-side", TradeType.SELL, Decimal("110"))
        add_tp(self.controller, "sell-wrong-side", TradeType.BUY, Decimal("90"))

        action = self.controller.get_no_budget_tp_cancel_action()

        self.assertEqual(action.executor_id, "sell-far")

    def test_sell_side_farthest_tp_is_selected(self):
        add_tp(self.controller, "sell-near", TradeType.BUY, Decimal("110"))
        add_tp(self.controller, "sell-far", TradeType.BUY, Decimal("120"))
        self.assertEqual(
            self.controller.get_no_budget_tp_cancel_action().executor_id,
            "sell-far",
        )

    def test_below_threshold_and_active_loss_exit_are_excluded(self):
        add_tp(self.controller, "near", TradeType.SELL, Decimal("96"))
        add_tp(self.controller, "exit-active", TradeType.SELL, Decimal("50"), lock=True)
        self.assertIsNone(self.controller.get_no_budget_tp_cancel_action())

    def test_only_one_cancel_per_budget_pause(self):
        add_tp(self.controller, "far", TradeType.SELL, Decimal("80"))
        action = self.controller.get_no_budget_tp_cancel_action()
        self.assertIsNotNone(action)
        self.assertIsNone(self.controller.get_no_budget_tp_cancel_action())

        self.controller.executors_info[0].custom_info["no_budget_tp_cancel_requested"] = True
        add_tp(self.controller, "next", TradeType.SELL, Decimal("75"))
        OrderBudgetGuard.note_no_budget(self.config.id, 131.0, 30, "no budget again")
        self.controller.market_data_provider.time.return_value = 131.0
        self.assertEqual(
            self.controller.get_no_budget_tp_cancel_action().executor_id,
            "next",
        )

    def test_executor_cancels_without_requote_and_holds_position(self):
        OrderBudgetGuard.reset()
        executor = make_executor()
        executor._status = RunnableStatus.RUNNING
        executor.place_take_profit_limit_order(amount=Decimal("1"), price=Decimal("100"))
        executor._take_profit_limit_order.order = MagicMock()
        executor._take_profit_limit_order.order.is_open = True
        executor._strategy.sell.reset_mock()

        assert executor.cancel_take_profit_for_no_budget()

        executor._strategy.cancel.assert_called_once_with(
            connector_name="binance_paper_trade",
            trading_pair="ETH-USDT",
            order_id="tp-order",
        )
        executor._strategy.sell.assert_not_called()
        self.assertEqual(executor.close_type, CloseType.POSITION_HOLD)
        self.assertEqual(executor.status, RunnableStatus.SHUTTING_DOWN)


class OrchestratorNoBudgetCancelTests(unittest.TestCase):
    def test_cancel_action_reaches_position_executor(self):
        executor = make_executor()
        executor.cancel_take_profit_for_no_budget = MagicMock(return_value=True)
        orchestrator = object.__new__(ExecutorOrchestrator)
        orchestrator._persist_recovery_snapshots = MagicMock()
        orchestrator.cached_performance = {"bot-a": MagicMock()}
        orchestrator.active_executors = {"bot-a": [executor]}
        orchestrator.positions_held = {"bot-a": []}
        orchestrator.logger = MagicMock(return_value=MagicMock())

        orchestrator.execute_action(CancelTakeProfitAction(
            controller_id="bot-a", executor_id="executor-1"
        ))

        executor.cancel_take_profit_for_no_budget.assert_called_once()


if __name__ == "__main__":
    unittest.main()
