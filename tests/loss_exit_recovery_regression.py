import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from hummingbot.strategy_v2.controllers.loss_exit_recovery import LossExitRecoveryStore
from order_budget_controller_regression import make_config, make_controller
from order_budget_executor_regression import make_executor


def completed_executor_record():
    record = make_executor().snapshot_recovery_state()
    record["loss_exit"].update({
        "state": "COMPLETED",
        "lock_held": False,
        "reconciliation_required": False,
    })
    return record


def legacy_record(executor_id="executor-1"):
    return {
        "controller_id": "bot-a",
        "connector_name": "binance_paper_trade",
        "trading_pair": "ETH-USDT",
        "executor_id": executor_id,
        "active_order_id": None,
        "reconciliation_required": False,
    }


class LossExitRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def prepare_controller(self, directory, legacy, executor_records):
        config = make_config()
        controller = make_controller(config)
        old_store = LossExitRecoveryStore(config.id, Path(directory), run_id="old-run")
        old_store.save(legacy)
        controller._loss_exit_recovery_store = LossExitRecoveryStore(
            config.id, Path(directory), run_id="new-run"
        )
        controller._loss_exit_recovery_required = True
        controller._recovery_pending = {}
        controller._recovery_actions = []
        controller._recovery_coordinator = MagicMock()
        controller._recovery_coordinator.load_snapshots = AsyncMock(return_value={
            "payload": {"executors": executor_records},
            "snapshots": {record["executor_id"]: {} for record in executor_records},
        })
        controller.recovery_state = "PENDING"
        await controller._prepare_recovery_actions()
        return controller, old_store.path

    async def test_completed_legacy_record_is_cleared_after_main_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            controller, old_path = await self.prepare_controller(
                directory, legacy_record(), [completed_executor_record()]
            )

            self.assertFalse(controller._loss_exit_recovery_required)
            self.assertFalse(old_path.exists())

    async def test_active_legacy_record_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            record = completed_executor_record()
            record["loss_exit"].update({"state": "ACTIVE", "lock_held": True})
            controller, old_path = await self.prepare_controller(
                directory, legacy_record(), [record]
            )

            self.assertTrue(controller._loss_exit_recovery_required)
            self.assertTrue(old_path.exists())

    async def test_legacy_record_without_executor_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            controller, old_path = await self.prepare_controller(
                directory, legacy_record("missing-executor"), []
            )

            self.assertTrue(controller._loss_exit_recovery_required)
            self.assertTrue(old_path.exists())


if __name__ == "__main__":
    unittest.main()
