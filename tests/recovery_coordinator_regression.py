from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock

from hummingbot.strategy_v2.controllers.executor_recovery import RecoveredOrderSnapshot
from hummingbot.strategy_v2.controllers.recovery_coordinator import RecoveryCoordinator
from hummingbot.strategy_v2.executors.executor_orchestrator import ExecutorOrchestrator
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction
from executor_recovery_store_regression import valid_payload
from order_budget_controller_regression import make_config, make_controller
from order_budget_executor_regression import make_executor


def recovered_order(order_id, status):
    original = Decimal("2")
    filled = original if status == "FILLED" else Decimal("0")
    return RecoveredOrderSnapshot(
        client_order_id=order_id, exchange_order_id=f"exchange-{order_id}",
        side="SELL", order_type="LIMIT", price=Decimal("100"),
        original_amount=original, filled_amount=filled,
        remaining_amount=original - filled, status=status, updated_at=100.0,
    )


class RecoveryCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_records_is_ready(self):
        import tempfile
        from pathlib import Path
        from hummingbot.strategy_v2.controllers.executor_recovery import ExecutorRecoveryStore
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutorRecoveryStore("bot-a", Path(directory))
            coordinator = RecoveryCoordinator(store, MagicMock(), MagicMock())
            await coordinator.reconcile([])
            self.assertEqual(coordinator.state, "READY")

    async def test_unknown_snapshot_blocks_without_restoring(self):
        import tempfile
        from pathlib import Path
        from hummingbot.strategy_v2.controllers.executor_recovery import ExecutorRecoveryStore
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutorRecoveryStore("bot-a", Path(directory))
            store.save(valid_payload())
            adapter = MagicMock()
            adapter.fetch_order_snapshot = AsyncMock(
                side_effect=lambda order_id: recovered_order(order_id, "UNKNOWN")
            )
            restorer = MagicMock()
            coordinator = RecoveryCoordinator(store, lambda: adapter, restorer)
            await coordinator.reconcile([])
            self.assertEqual(coordinator.state, "BLOCKED")
            restorer.restore.assert_not_called()

    async def test_valid_snapshots_restore_all_executors(self):
        import tempfile
        from pathlib import Path
        from hummingbot.strategy_v2.controllers.executor_recovery import ExecutorRecoveryStore
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutorRecoveryStore("bot-a", Path(directory))
            store.save(valid_payload())
            adapter = MagicMock()
            adapter.fetch_order_snapshot = AsyncMock(
                side_effect=lambda order_id: recovered_order(
                    order_id, "FILLED" if order_id == "open-1" else "PARTIALLY_FILLED"
                )
            )
            adapter.fetch_open_order_ids = AsyncMock(return_value={"open-1", "tp-1"})
            restorer = MagicMock()
            coordinator = RecoveryCoordinator(store, lambda: adapter, restorer)
            executor = SimpleNamespace(config=SimpleNamespace(id="executor-1"))
            await coordinator.reconcile([executor])
            self.assertEqual(coordinator.state, "READY")
            restorer.restore.assert_called_once()


class ControllerRecoveryGateTests(unittest.TestCase):
    def test_blocked_recovery_disables_new_orders_and_loss_exit(self):
        controller = make_controller(make_config())
        controller.recovery_state = "BLOCKED"
        self.assertIsNone(controller.get_executor_config("buy_0", Decimal("100"), Decimal("1")))
        self.assertIsNone(controller.get_loss_exit_activation_action())


class OrchestratorRecoveryTests(unittest.TestCase):
    def make_orchestrator(self, controller, executor):
        orchestrator = object.__new__(ExecutorOrchestrator)
        orchestrator._executor_mapping = {"position_executor": MagicMock(return_value=executor)}
        orchestrator.strategy = SimpleNamespace(controllers={"bot-a": controller})
        orchestrator.active_executors = {"bot-a": []}
        orchestrator.executors_update_interval = 1.0
        orchestrator.executors_max_retries = 1
        orchestrator.logger = MagicMock(return_value=MagicMock())
        return orchestrator

    def test_create_executor_restores_before_start(self):
        controller = MagicMock()
        controller.get_recovery_restore_data.return_value = {
            "record": {"executor_id": "executor-1"}, "snapshots": {"open-1": {}},
        }
        executor = MagicMock()
        orchestrator = self.make_orchestrator(controller, executor)
        action = CreateExecutorAction(
            controller_id="bot-a", executor_config=make_executor().config,
        )

        orchestrator.create_executor(action)

        executor.restore_recovery_state.assert_called_once_with(
            {"executor_id": "executor-1"}, {"open-1": {}}
        )
        executor.start.assert_called_once()
        controller.complete_recovery_executor.assert_called_once_with("executor-1")

    def test_active_executor_snapshots_are_forwarded_for_persistence(self):
        controller = MagicMock()
        executor = MagicMock()
        executor.snapshot_recovery_state.return_value = {"executor_id": "executor-1"}
        orchestrator = self.make_orchestrator(controller, executor)
        orchestrator.active_executors = {"bot-a": [executor]}

        orchestrator._persist_recovery_snapshots()

        controller.persist_recovery_snapshots.assert_called_once_with([
            {"executor_id": "executor-1"}
        ])


if __name__ == "__main__":
    unittest.main()
