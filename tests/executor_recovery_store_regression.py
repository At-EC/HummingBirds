import json
from decimal import Decimal
import unittest

from hummingbot.strategy_v2.controllers.executor_recovery import (
    ExecutorRecoveryStore,
    RecoveredOrderSnapshot,
)


def valid_payload():
    return {
        "schema_version": 1,
        "controller_id": "bot-a",
        "connector_name": "binance",
        "trading_pair": "ZEC-USDT",
        "updated_at": 100.0,
        "executors": [{
            "executor_id": "executor-1",
            "executor_config": {"side": "BUY"},
            "open_order": {
                "client_order_id": "open-1",
                "original_amount": "2",
                "filled_amount": "2",
            },
            "take_profit_order": {
                "client_order_id": "tp-1",
                "original_amount": "2",
                "filled_amount": "0.5",
            },
            "close_order": None,
            "loss_exit_orders": [],
            "terminal_order_ids": [],
            "loss_exit": {"lock_held": False},
        }],
    }


class RecoveryStoreTests(unittest.TestCase):
    def test_store_round_trip_and_atomic_write(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutorRecoveryStore("bot-a", Path(directory))
            store.save(valid_payload())
            self.assertEqual(store.load(), valid_payload())
            self.assertEqual(store.path.name, "bot-a.json")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_missing_store_returns_none(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(ExecutorRecoveryStore("bot-a", Path(directory)).load())

    def test_duplicate_order_id_is_rejected(self):
        import tempfile
        from pathlib import Path
        payload = valid_payload()
        payload["executors"][0]["loss_exit_orders"] = [
            payload["executors"][0]["take_profit_order"].copy()
        ]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "duplicate order"):
                ExecutorRecoveryStore("bot-a", Path(directory)).save(payload)

    def test_wrong_schema_is_rejected(self):
        import tempfile
        from pathlib import Path
        payload = valid_payload()
        payload["schema_version"] = 999
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "schema"):
                ExecutorRecoveryStore("bot-a", Path(directory)).save(payload)

    def test_invalid_amounts_are_rejected(self):
        import tempfile
        from pathlib import Path
        payload = valid_payload()
        payload["executors"][0]["take_profit_order"]["filled_amount"] = "3"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "amount"):
                ExecutorRecoveryStore("bot-a", Path(directory)).save(payload)


class RecoveredOrderSnapshotTests(unittest.TestCase):
    def test_remaining_amount_and_validation(self):
        snapshot = RecoveredOrderSnapshot(
            client_order_id="tp-1",
            exchange_order_id="exchange-1",
            side="SELL",
            order_type="LIMIT",
            price=Decimal("100"),
            original_amount=Decimal("2"),
            filled_amount=Decimal("0.5"),
            remaining_amount=Decimal("1.5"),
            status="PARTIALLY_FILLED",
            updated_at=100.0,
        )
        self.assertEqual(snapshot.remaining_amount, Decimal("1.5"))
        with self.assertRaisesRegex(ValueError, "remaining"):
            RecoveredOrderSnapshot(
                client_order_id="tp-1", exchange_order_id=None,
                side="SELL", order_type="LIMIT", price=Decimal("100"),
                original_amount=Decimal("2"), filled_amount=Decimal("0.5"),
                remaining_amount=Decimal("1"), status="OPEN", updated_at=100.0,
            )


if __name__ == "__main__":
    unittest.main()
