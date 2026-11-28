from decimal import Decimal
import unittest

from hummingbot.strategy_v2.controllers.executor_recovery import RecoveredOrderSnapshot
from hummingbot.strategy_v2.executors.position_executor.data_types import LossExitConfig
from hummingbot.strategy_v2.executors.position_executor.loss_exit import LossExitState, LossExitTracker
from hummingbot.strategy_v2.executors.position_executor.recovery import (
    ExecutorRuntimeRestorer,
    RecoveryBlocked,
)
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType
from order_budget_executor_regression import make_executor


def recovered_order(order_id, side, filled, status):
    original = Decimal("2")
    filled_decimal = Decimal(filled)
    return RecoveredOrderSnapshot(
        client_order_id=order_id,
        exchange_order_id=f"exchange-{order_id}",
        side=side,
        order_type="LIMIT",
        price=Decimal("100"),
        original_amount=original,
        filled_amount=filled_decimal,
        remaining_amount=original - filled_decimal,
        status=status,
        updated_at=100.0,
    )


def recovered_tp(filled="0.5", status="PARTIALLY_FILLED"):
    return recovered_order("tp-1", "SELL", filled, status)


def recovery_record_with_tp(filled="0.5", original="2", loss_exit=False):
    tp_record = {
        "client_order_id": "tp-1",
        "side": "SELL",
        "order_type": "LIMIT",
        "price": "100",
        "original_amount": original,
        "filled_amount": filled,
        "creation_timestamp": 99.0,
    }
    return {
        "executor_id": "executor-1",
        "executor_config": {"side": "BUY"},
        "open_order": {
            "client_order_id": "open-1",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": "100",
            "original_amount": original,
            "filled_amount": original,
            "creation_timestamp": 90.0,
        },
        "take_profit_order": tp_record,
        "close_order": None,
        "loss_exit_orders": [tp_record.copy()] if loss_exit else [],
        "terminal_order_ids": [],
        "loss_exit": {
            "state": "ACTIVE" if loss_exit else "WATCHING",
            "lock_held": loss_exit,
            "condition_since": 91.0,
            "eligible_since": 92.0,
            "requote_count": 0,
            "last_requote_at": 99.0,
            "reconciliation_required": False,
        },
    }


def snapshots(tp=None):
    return {
        "open-1": recovered_order("open-1", "BUY", "2", "FILLED"),
        "tp-1": tp or recovered_tp(),
    }


class PositionExecutorRecoveryTests(unittest.TestCase):
    def test_open_tp_is_restored_with_same_id_and_fills(self):
        executor = make_executor(amount=Decimal("2"))
        executor._loss_exit = LossExitTracker(LossExitConfig(
            trigger_pct=Decimal("0.005"), offset_pct=Decimal("0.001"),
            cooldown_seconds=60, activation_delay_seconds=60,
        ))
        ExecutorRuntimeRestorer.restore(
            executor, recovery_record_with_tp(), snapshots()
        )
        self.assertEqual(executor._take_profit_limit_order.order_id, "tp-1")
        self.assertEqual(
            executor._take_profit_limit_order.order.executed_amount_base,
            Decimal("0.5"),
        )
        self.assertEqual(executor._open_order.order_id, "open-1")

    def test_filled_tp_is_not_recreated(self):
        executor = make_executor(amount=Decimal("2"))
        executor._loss_exit = LossExitTracker(LossExitConfig(
            trigger_pct=Decimal("0.005"), offset_pct=Decimal("0.001"),
            cooldown_seconds=60, activation_delay_seconds=60,
        ))
        ExecutorRuntimeRestorer.restore(
            executor,
            recovery_record_with_tp(),
            snapshots(recovered_tp(filled="2", status="FILLED")),
        )
        self.assertIsNone(executor._take_profit_limit_order)
        self.assertEqual(executor.close_type, CloseType.TAKE_PROFIT)
        self.assertEqual(executor.status, RunnableStatus.SHUTTING_DOWN)

    def test_completed_exit_does_not_reacquire_lock_on_restore(self):
        executor = make_executor(amount=Decimal("2"))
        executor._loss_exit = LossExitTracker(LossExitConfig(
            trigger_pct=Decimal("0.005"), offset_pct=Decimal("0.001"),
            cooldown_seconds=60, activation_delay_seconds=60,
        ))
        record = recovery_record_with_tp(loss_exit=True)
        record["loss_exit"]["state"] = "COMPLETED"
        record["loss_exit"]["lock_held"] = False

        ExecutorRuntimeRestorer.restore(
            executor, record, snapshots(recovered_tp(filled="2", status="FILLED"))
        )

        self.assertEqual(executor._loss_exit.state, LossExitState.COMPLETED)
        self.assertFalse(executor.loss_exit_lock_held)
        self.assertFalse(executor.snapshot_recovery_state()["loss_exit"]["lock_held"])

    def test_completed_tp_snapshot_has_single_owner(self):
        from types import SimpleNamespace
        from hummingbot.strategy_v2.controllers.order_budget import OrderBudgetGuard

        OrderBudgetGuard.reset()
        executor = make_executor(amount=Decimal("2"))
        executor.place_take_profit_limit_order(amount=Decimal("1"), price=Decimal("100"))
        executor.process_order_completed_event(None, None, SimpleNamespace(
            order_id="tp-order",
            base_asset_amount=Decimal("1"),
            timestamp=101.0,
            exchange_order_id="exchange-tp-order",
        ))

        record = executor.snapshot_recovery_state()

        self.assertEqual(record["take_profit_order"]["client_order_id"], "tp-order")
        self.assertIsNone(record["close_order"])

    def test_unknown_tp_blocks_recovery(self):
        executor = make_executor(amount=Decimal("2"))
        executor._loss_exit = LossExitTracker(LossExitConfig(
            trigger_pct=Decimal("0.005"), offset_pct=Decimal("0.001"),
            cooldown_seconds=60, activation_delay_seconds=60,
        ))
        with self.assertRaises(RecoveryBlocked):
            ExecutorRuntimeRestorer.restore(
                executor,
                recovery_record_with_tp(),
                snapshots(recovered_tp(filled="0", status="UNKNOWN")),
            )

    def test_active_loss_exit_restores_single_lock_and_order(self):
        executor = make_executor(amount=Decimal("2"))
        executor._loss_exit = LossExitTracker(LossExitConfig(
            trigger_pct=Decimal("0.005"), offset_pct=Decimal("0.001"),
            cooldown_seconds=60, activation_delay_seconds=60,
        ))
        ExecutorRuntimeRestorer.restore(
            executor,
            recovery_record_with_tp(loss_exit=True),
            snapshots(),
        )
        self.assertEqual(executor._loss_exit.state, LossExitState.ACTIVE)
        self.assertTrue(executor.loss_exit_lock_held)
        self.assertEqual(list(executor._loss_exit_orders), ["tp-1"])

    def test_recovery_snapshot_contains_tracked_order_ids(self):
        executor = make_executor(amount=Decimal("2"))
        executor._loss_exit = LossExitTracker(LossExitConfig(
            trigger_pct=Decimal("0.005"), offset_pct=Decimal("0.001"),
            cooldown_seconds=60, activation_delay_seconds=60,
        ))
        ExecutorRuntimeRestorer.restore(
            executor,
            recovery_record_with_tp(loss_exit=True),
            snapshots(),
        )
        record = executor.snapshot_recovery_state()
        self.assertEqual(record["open_order"]["client_order_id"], "open-1")
        self.assertEqual(record["take_profit_order"]["client_order_id"], "tp-1")
        self.assertEqual(record["loss_exit_orders"][0]["client_order_id"], "tp-1")
        self.assertTrue(record["loss_exit"]["lock_held"])


if __name__ == "__main__":
    unittest.main()


class PositionOnlyRecoveryTests(unittest.TestCase):
    def test_executor_without_any_order_does_not_require_open_snapshot(self):
        executor = make_executor(amount=Decimal("2"))
        record = recovery_record_with_tp()
        record["open_order"] = None
        record["take_profit_order"] = None
        record["loss_exit_orders"] = []

        ExecutorRuntimeRestorer.restore(executor, record, {})

        self.assertIsNone(executor._open_order)
        self.assertIsNone(executor._take_profit_limit_order)
