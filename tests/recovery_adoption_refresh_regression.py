from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
import unittest

from controllers.generic.pmm_mister import PMMister
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig
from hummingbot.strategy_v2.executors.position_executor.recovery import ExecutorRuntimeRestorer
from order_budget_executor_regression import make_executor
from scripts.condor_bootstrap_recovery import build_adoption_record
from recovery_bootstrap_regression import open_order


class RecoveryAdoptionRefreshTests(unittest.TestCase):
    def test_adopted_order_is_marked_and_excluded_from_refresh_lifecycle(self):
        snapshot = open_order()
        record = build_adoption_record(snapshot, "binance", "ZEC-USDT")
        self.assertTrue(record["recovery_adopted"])

        executor = make_executor()
        executor.config = PositionExecutorConfig(**record["executor_config"])
        executor.connectors["binance"] = MagicMock()
        executor.connectors["binance"].get_price_by_type.return_value = Decimal("750")
        executor.connectors["binance"].quantize_order_amount.side_effect = lambda **kwargs: kwargs["amount"]
        ExecutorRuntimeRestorer.restore(executor, record, {snapshot.client_order_id: snapshot})
        self.assertTrue(executor.get_custom_info()["recovery_adopted"])

        info = SimpleNamespace(custom_info={"recovery_adopted": True})
        self.assertTrue(PMMister._skip_refresh_and_effectivization(info))
        info.custom_info["recovery_adopted"] = False
        self.assertFalse(PMMister._skip_refresh_and_effectivization(info))


if __name__ == "__main__":
    unittest.main()
