from decimal import Decimal
import unittest

from hummingbot.strategy_v2.controllers.executor_recovery import RecoveredOrderSnapshot
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig
from hummingbot.strategy_v2.executors.position_executor.recovery import ExecutorRuntimeRestorer
from scripts.condor_bootstrap_recovery import build_adoption_record, merge_adoption_records
from order_budget_executor_regression import make_executor


def open_order(order_id="existing-1"):
    return RecoveredOrderSnapshot(
        client_order_id=order_id,
        exchange_order_id="exchange-1",
        side="SELL",
        order_type="LIMIT",
        price=Decimal("750"),
        original_amount=Decimal("2"),
        filled_amount=Decimal("0.5"),
        remaining_amount=Decimal("1.5"),
        status="PARTIALLY_FILLED",
        updated_at=100.0,
    )


class RecoveryBootstrapTests(unittest.TestCase):
    def test_adoption_record_preserves_order_without_creating_future_tp(self):
        snapshot = open_order()
        record = build_adoption_record(snapshot, "binance", "ZEC-USDT")
        self.assertEqual(record["open_order"]["client_order_id"], snapshot.client_order_id)
        self.assertIsNone(record["take_profit_order"])
        self.assertFalse(record["loss_exit"]["lock_held"])

        executor = make_executor()
        executor.config = PositionExecutorConfig(**record["executor_config"])
        ExecutorRuntimeRestorer.restore(
            executor, record, {snapshot.client_order_id: snapshot}
        )
        self.assertEqual(executor._open_order.order_id, snapshot.client_order_id)
        self.assertIsNone(executor._take_profit_limit_order)
        self.assertIsNone(executor.config.triple_barrier_config.take_profit)

    def test_merge_is_idempotent_and_preserves_existing_records(self):
        snapshot = open_order()
        payload = {
            "schema_version": 1,
            "controller_id": "pmm_mister_loss_exit_sample",
            "connector_name": "binance",
            "trading_pair": "ZEC-USDT",
            "updated_at": 90.0,
            "executors": [],
        }
        merge_adoption_records(payload, [snapshot], "pmm_mister_loss_exit_sample", 100.0)
        merge_adoption_records(payload, [snapshot], "pmm_mister_loss_exit_sample", 101.0)
        self.assertEqual(len(payload["executors"]), 1)
        self.assertEqual(payload["updated_at"], 101.0)


if __name__ == "__main__":
    unittest.main()


class RecoveryIdentityTests(unittest.TestCase):
    def test_identity_is_discovered_from_controller_config(self):
        import tempfile
        from pathlib import Path
        from scripts.condor_bootstrap_recovery import discover_controller_identity
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "sample.yml").write_text(
                "id: sample_pmm_loss_exit_btc_usdt\n"
                "connector_name: binance\n"
                "trading_pair: ZEC-USDT\n"
            )
            identity = discover_controller_identity(Path(directory))
        self.assertEqual(identity, {
            "id": "sample_pmm_loss_exit_btc_usdt",
            "connector_name": "binance",
            "trading_pair": "ZEC-USDT",
        })


class SnapshotFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_older_adapter_falls_back_to_individual_snapshots(self):
        from scripts.condor_bootstrap_recovery import fetch_open_orders

        class OlderAdapter:
            async def fetch_open_order_ids(self):
                return {"existing-1"}

            async def fetch_order_snapshot(self, order_id):
                return open_order(order_id)

        snapshots = await fetch_open_orders(OlderAdapter())
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].client_order_id, "existing-1")
