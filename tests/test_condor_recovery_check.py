from dataclasses import replace
from decimal import Decimal
import json
import subprocess
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from scripts import condor_recovery_check
from executor_recovery_store_regression import valid_payload
from hummingbot.strategy_v2.controllers.executor_recovery import RecoveredOrderSnapshot


def recovered_order(order_id, status):
    original = Decimal("2")
    filled = original if status == "FILLED" else Decimal("0")
    return RecoveredOrderSnapshot(
        client_order_id=order_id, exchange_order_id=f"exchange-{order_id}",
        side="SELL", order_type="LIMIT", price=Decimal("100"),
        original_amount=original, filled_amount=filled,
        remaining_amount=original - filled, status=status, updated_at=100.0,
    )


class RecoveryCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_returns_blocked_without_mutating_store(self):
        store = MagicMock()
        store.load.return_value = valid_payload()
        adapter = MagicMock()
        adapter.fetch_order_snapshot = AsyncMock(
            side_effect=lambda order_id: recovered_order(order_id, "UNKNOWN")
        )
        state, _ = await condor_recovery_check.run_diagnostics(store, adapter)
        self.assertEqual(state, "BLOCKED")
        store.save.assert_not_called()

    async def test_matching_open_orders_return_ready(self):
        payload = valid_payload()
        store = MagicMock()
        store.load.return_value = payload
        adapter = MagicMock()

        def snapshot(order_id):
            record = payload["executors"][0][
                "open_order" if order_id == "open-1" else "take_profit_order"
            ]
            status = "FILLED" if order_id == "open-1" else "PARTIALLY_FILLED"
            result = recovered_order(order_id, status)
            filled = Decimal(record["filled_amount"])
            return replace(
                result,
                filled_amount=filled,
                remaining_amount=result.original_amount - filled,
            )

        adapter.fetch_order_snapshot = AsyncMock(side_effect=snapshot)
        state, report = await condor_recovery_check.run_diagnostics(store, adapter)
        self.assertEqual(state, "READY")
        self.assertEqual(report["controller_id"], "bot-a")

    async def test_filled_amount_regression_is_blocked(self):
        payload = valid_payload()
        payload["executors"][0]["take_profit_order"]["filled_amount"] = "1.5"
        store = MagicMock()
        store.load.return_value = payload
        adapter = MagicMock()
        adapter.fetch_order_snapshot = AsyncMock(
            side_effect=lambda order_id: recovered_order(order_id, "PARTIALLY_FILLED")
        )
        state, _ = await condor_recovery_check.run_diagnostics(store, adapter)
        self.assertEqual(state, "BLOCKED")


class RecoveryCheckHostTests(unittest.TestCase):
    def test_host_only_executes_read_only_worker(self):
        result = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"state": "READY"}), stderr=""
        )
        with patch("scripts.condor_recovery_check.subprocess.run", return_value=result) as run:
            exit_code = condor_recovery_check.main(["--container", "demo"])
        self.assertEqual(exit_code, 0)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["docker", "exec", "demo"])
        self.assertNotIn("stop", command)
        self.assertNotIn("rm", command)


if __name__ == "__main__":
    unittest.main()
