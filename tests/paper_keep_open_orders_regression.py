import asyncio
import copy
from decimal import Decimal
import unittest
from unittest.mock import AsyncMock, MagicMock

from hummingbot.strategy_v2.controllers.recovery_coordinator import RecoveryCoordinator
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.executors.position_executor.recovery import ExecutorRuntimeRestorer, RecoveryBlocked
from hummingbot.strategy_v2.models.base import RunnableStatus
from order_budget_controller_regression import make_config, make_controller
from order_budget_executor_regression import make_executor
from position_executor_recovery_regression import (
    recovery_record_with_tp,
    recovered_order,
    recovered_tp,
    snapshots,
)


class KeepOpenOrdersIntegrationTests(unittest.TestCase):
    def test_original_tp_restarts_with_same_id(self):
        executor = make_executor(amount=Decimal("2"))
        ExecutorRuntimeRestorer.restore(executor, recovery_record_with_tp(), snapshots())
        self.assertEqual(executor._take_profit_limit_order.order_id, "tp-1")

    def test_partial_fill_during_stop_updates_remaining_amount(self):
        executor = make_executor(amount=Decimal("2"))
        ExecutorRuntimeRestorer.restore(
            executor,
            recovery_record_with_tp(),
            snapshots(recovered_tp(filled="1", status="PARTIALLY_FILLED")),
        )
        self.assertEqual(
            executor._take_profit_limit_order.order.executed_amount_base,
            Decimal("1"),
        )
        self.assertEqual(executor._take_profit_limit_order.order.amount, Decimal("2"))

    def test_full_fill_during_stop_is_not_requoted(self):
        executor = make_executor(amount=Decimal("2"))
        ExecutorRuntimeRestorer.restore(
            executor,
            recovery_record_with_tp(),
            snapshots(recovered_tp(filled="2", status="FILLED")),
        )
        self.assertIsNone(executor._take_profit_limit_order)
        self.assertEqual(executor.status, RunnableStatus.SHUTTING_DOWN)

    def test_external_cancel_does_not_start_new_tp(self):
        executor = make_executor(amount=Decimal("2"))
        ExecutorRuntimeRestorer.restore(
            executor,
            recovery_record_with_tp(),
            snapshots(recovered_tp(filled="0.5", status="CANCELED")),
        )
        self.assertIsNone(executor._take_profit_limit_order)
        self.assertEqual(executor.status, RunnableStatus.SHUTTING_DOWN)

    def test_unknown_snapshot_blocks(self):
        executor = make_executor(amount=Decimal("2"))
        with self.assertRaises(RecoveryBlocked):
            ExecutorRuntimeRestorer.restore(
                executor,
                recovery_record_with_tp(),
                snapshots(recovered_tp(filled="0", status="UNKNOWN")),
            )

    def test_missing_snapshot_blocks(self):
        executor = make_executor(amount=Decimal("2"))
        with self.assertRaises(RecoveryBlocked):
            ExecutorRuntimeRestorer.restore(
                executor, recovery_record_with_tp(), {"open-1": recovered_order("open-1", "BUY", "2", "FILLED")}
            )

    def test_repeated_restore_is_idempotent(self):
        executor = make_executor(amount=Decimal("2"))
        executor._loss_exit = MagicMock()
        executor._loss_exit.requote_count = 0
        record = recovery_record_with_tp(loss_exit=True)
        ExecutorRuntimeRestorer.restore(executor, record, snapshots())
        ExecutorRuntimeRestorer.restore(executor, record, snapshots())
        self.assertEqual(len(executor._loss_exit_orders), 1)
        self.assertEqual(executor._loss_exit.requote_count, 0)

    def test_expired_tp_is_due_after_restart(self):
        executor = make_executor(
            timestamp=90.0,
            triple_barrier_config=TripleBarrierConfig(time_limit=10),
        )
        self.assertTrue(executor.is_expired)


class RecoveryCoordinatorIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_untracked_exchange_order_blocks_recovery(self):
        import tempfile
        from pathlib import Path
        from hummingbot.strategy_v2.controllers.executor_recovery import ExecutorRecoveryStore
        from executor_recovery_store_regression import valid_payload

        with tempfile.TemporaryDirectory() as directory:
            store = ExecutorRecoveryStore("bot-a", Path(directory))
            store.save(valid_payload())
            adapter = MagicMock()
            adapter.fetch_order_snapshot = AsyncMock(
                side_effect=lambda order_id: recovered_order(order_id, "SELL", "0", "OPEN")
            )
            adapter.fetch_open_order_ids = AsyncMock(return_value={"open-1", "tp-1", "unexpected"})
            coordinator = RecoveryCoordinator(store, lambda: adapter, MagicMock())
            await coordinator.reconcile([make_executor()])
            self.assertEqual(coordinator.state, "BLOCKED")
            adapter.fetch_open_order_ids.assert_awaited_once()


class PersistenceFailureTests(unittest.TestCase):
    def test_store_failure_blocks_trading(self):
        controller = make_controller(make_config())
        controller.recovery_state = "READY"
        controller._recovery_last_snapshots = None
        controller._recovery_coordinator = MagicMock()
        controller._recovery_coordinator.store.save.side_effect = OSError("disk full")
        controller._recovery_pending = {}
        controller._recovery_actions = []
        controller._recovery_task = None

        controller.persist_recovery_snapshots([])

        self.assertEqual(controller.recovery_state, "BLOCKED")
        self.assertIsNone(controller.get_executor_config("buy_0", Decimal("100"), Decimal("1")))


if __name__ == "__main__":
    unittest.main()
