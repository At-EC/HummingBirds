from decimal import Decimal
import unittest
from unittest.mock import AsyncMock, MagicMock

from hummingbot.connector.exchange.binance.binance_order_recovery import BinanceOrderRecoveryAdapter
from hummingbot.strategy_v2.controllers.executor_recovery import RecoveredOrderSnapshot


def binance_open_order():
    return {
        "orderId": 99,
        "clientOrderId": "tp-1",
        "symbol": "ZECUSDT",
        "side": "SELL",
        "type": "LIMIT",
        "price": "100.5",
        "origQty": "2",
        "executedQty": "0.5",
        "status": "PARTIALLY_FILLED",
        "updateTime": 1234500,
    }


def snapshot():
    return RecoveredOrderSnapshot(
        client_order_id="tp-1", exchange_order_id="99", side="SELL",
        order_type="LIMIT", price=Decimal("100.5"), original_amount=Decimal("2"),
        filled_amount=Decimal("0.5"), remaining_amount=Decimal("1.5"),
        status="PARTIALLY_FILLED", updated_at=1234.5,
    )


class BinanceOrderRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.adapter = BinanceOrderRecoveryAdapter(MagicMock(), "ZEC-USDT")

    def test_open_order_snapshot_preserves_remaining_amount(self):
        result = self.adapter._convert_order(binance_open_order())
        self.assertEqual(result.status, "PARTIALLY_FILLED")
        self.assertEqual(result.original_amount, Decimal("2"))
        self.assertEqual(result.filled_amount, Decimal("0.5"))
        self.assertEqual(result.remaining_amount, Decimal("1.5"))
        self.assertEqual(result.exchange_order_id, "99")

    def test_terminal_statuses_are_explicit(self):
        for source, expected in (("FILLED", "FILLED"), ("CANCELED", "CANCELED"), ("REJECTED", "FAILED")):
            raw = binance_open_order()
            raw["status"] = source
            if source == "FILLED":
                raw["executedQty"] = raw["origQty"]
            self.assertEqual(self.adapter._convert_order(raw).status, expected)

    def test_not_found_is_unknown_not_canceled(self):
        result = self.adapter._convert_api_error("tp-1", Exception("Order does not exist"))
        self.assertEqual(result.status, "UNKNOWN")
        self.assertNotEqual(result.status, "CANCELED")


class BinanceOrderRecoveryAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_order_uses_client_order_id(self):
        connector = MagicMock()
        connector.exchange_symbol_associated_to_pair = AsyncMock(return_value="ZECUSDT")
        connector._api_get = AsyncMock(return_value=binance_open_order())
        adapter = BinanceOrderRecoveryAdapter(connector, "ZEC-USDT")

        result = await adapter.fetch_order_snapshot("tp-1")

        self.assertEqual(result.client_order_id, "tp-1")
        params = connector._api_get.call_args.kwargs["params"]
        self.assertEqual(params, {"symbol": "ZECUSDT", "origClientOrderId": "tp-1"})
        self.assertTrue(connector._api_get.call_args.kwargs["is_auth_required"])

    async def test_fetch_fills_filters_checkpoint_and_deduplicates(self):
        connector = MagicMock()
        connector.exchange_symbol_associated_to_pair = AsyncMock(return_value="ZECUSDT")
        connector._api_get = AsyncMock(return_value=[
            {"id": 100, "orderId": 99, "qty": "0.2", "quoteQty": "20", "price": "100",
             "commission": "0.01", "commissionAsset": "USDT", "time": 1000000},
            {"id": 101, "orderId": 99, "qty": "0.3", "quoteQty": "30", "price": "100",
             "commission": "0.01", "commissionAsset": "USDT", "time": 1001000},
            {"id": 101, "orderId": 99, "qty": "0.3", "quoteQty": "30", "price": "100",
             "commission": "0.01", "commissionAsset": "USDT", "time": 1001000},
        ])
        adapter = BinanceOrderRecoveryAdapter(connector, "ZEC-USDT")
        adapter.fetch_order_snapshot = AsyncMock(return_value=snapshot())

        fills = await adapter.fetch_fills_since("tp-1", {"last_trade_id": "100"})

        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0]["trade_id"], "101")
        self.assertEqual(fills[0]["fill_base_amount"], Decimal("0.3"))
        self.assertEqual(fills[0]["fill_timestamp"], 1001.0)


if __name__ == "__main__":
    unittest.main()


class BinanceOpenOrdersTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_open_order_ids_uses_read_only_endpoint(self):
        connector = MagicMock()
        connector.exchange_symbol_associated_to_pair = AsyncMock(return_value="ZECUSDT")
        connector._api_get = AsyncMock(return_value=[
            {"clientOrderId": "tp-1"}, {"clientOrderId": "tp-2"},
        ])
        adapter = BinanceOrderRecoveryAdapter(connector, "ZEC-USDT")

        result = await adapter.fetch_open_order_ids()

        self.assertEqual(result, {"tp-1", "tp-2"})
        kwargs = connector._api_get.call_args.kwargs
        self.assertEqual(kwargs["path_url"], "/openOrders")
        self.assertEqual(kwargs["params"], {"symbol": "ZECUSDT"})
        self.assertTrue(kwargs["is_auth_required"])
