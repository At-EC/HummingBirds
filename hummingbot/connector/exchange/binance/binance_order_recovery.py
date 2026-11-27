import time
from decimal import Decimal

from hummingbot.connector.exchange.binance import binance_constants as CONSTANTS
from hummingbot.strategy_v2.controllers.executor_recovery import RecoveredOrderSnapshot


class OrderRecoveryQueryError(RuntimeError):
    pass


class BinanceOrderRecoveryAdapter:
    STATUS_MAP = {
        "NEW": "OPEN",
        "PARTIALLY_FILLED": "PARTIALLY_FILLED",
        "FILLED": "FILLED",
        "CANCELED": "CANCELED",
        "PENDING_CANCEL": "OPEN",
        "REJECTED": "FAILED",
        "EXPIRED": "CANCELED",
        "EXPIRED_IN_MATCH": "CANCELED",
    }

    def __init__(self, connector, trading_pair: str):
        self._connector = connector
        self._trading_pair = trading_pair

    def _convert_order(self, raw: dict) -> RecoveredOrderSnapshot:
        original = Decimal(str(raw["origQty"]))
        filled = Decimal(str(raw["executedQty"]))
        return RecoveredOrderSnapshot(
            client_order_id=str(raw["clientOrderId"]),
            exchange_order_id=str(raw["orderId"]),
            side=str(raw["side"]),
            order_type=str(raw["type"]),
            price=Decimal(str(raw["price"])),
            original_amount=original,
            filled_amount=filled,
            remaining_amount=original - filled,
            status=self.STATUS_MAP.get(str(raw["status"]), "UNKNOWN"),
            updated_at=float(raw["updateTime"]) * 1e-3,
        )

    def _convert_api_error(self, client_order_id: str, error: Exception) -> RecoveredOrderSnapshot:
        return RecoveredOrderSnapshot(
            client_order_id=client_order_id,
            exchange_order_id=None,
            side="UNKNOWN",
            order_type="UNKNOWN",
            price=Decimal("0"),
            original_amount=Decimal("0"),
            filled_amount=Decimal("0"),
            remaining_amount=Decimal("0"),
            status="UNKNOWN",
            updated_at=time.time(),
        )

    async def fetch_order_snapshot(self, client_order_id: str) -> RecoveredOrderSnapshot:
        try:
            symbol = await self._connector.exchange_symbol_associated_to_pair(
                trading_pair=self._trading_pair
            )
            raw = await self._connector._api_get(
                path_url=CONSTANTS.ORDER_PATH_URL,
                params={"symbol": symbol, "origClientOrderId": client_order_id},
                is_auth_required=True,
                limit_id=CONSTANTS.ORDER_PATH_URL,
            )
            return self._convert_order(raw)
        except Exception as error:
            return self._convert_api_error(client_order_id, error)

    async def fetch_fills_since(self, client_order_id: str, checkpoint: dict) -> list[dict]:
        snapshot = await self.fetch_order_snapshot(client_order_id)
        if snapshot.status == "UNKNOWN" or snapshot.exchange_order_id is None:
            raise OrderRecoveryQueryError(f"Unable to query fills for {client_order_id}")
        symbol = await self._connector.exchange_symbol_associated_to_pair(
            trading_pair=self._trading_pair
        )
        try:
            raw_fills = await self._connector._api_get(
                path_url=CONSTANTS.MY_TRADES_PATH_URL,
                params={"symbol": symbol, "orderId": int(snapshot.exchange_order_id)},
                is_auth_required=True,
                limit_id=CONSTANTS.MY_TRADES_PATH_URL,
            )
        except Exception as error:
            raise OrderRecoveryQueryError(f"Unable to query fills for {client_order_id}") from error
        last_trade_id = int(checkpoint.get("last_trade_id", "-1"))
        fills = {}
        for raw in raw_fills:
            trade_id = str(raw["id"])
            if int(trade_id) <= last_trade_id:
                continue
            fills[trade_id] = {
                "trade_id": trade_id,
                "client_order_id": client_order_id,
                "exchange_order_id": str(raw["orderId"]),
                "fill_base_amount": Decimal(str(raw["qty"])),
                "fill_quote_amount": Decimal(str(raw["quoteQty"])),
                "fill_price": Decimal(str(raw["price"])),
                "fee_amount": Decimal(str(raw["commission"])),
                "fee_asset": str(raw["commissionAsset"]),
                "fill_timestamp": float(raw["time"]) * 1e-3,
            }
        return sorted(
            fills.values(),
            key=lambda fill: (fill["fill_timestamp"], int(fill["trade_id"])),
        )


    async def fetch_open_order_ids(self) -> set[str]:
        symbol = await self._connector.exchange_symbol_associated_to_pair(
            trading_pair=self._trading_pair
        )
        try:
            raw_orders = await self._connector._api_get(
                path_url="/openOrders",
                params={"symbol": symbol},
                is_auth_required=True,
                limit_id=CONSTANTS.ORDER_PATH_URL,
            )
        except Exception as error:
            raise OrderRecoveryQueryError("Unable to query open orders") from error
        return {str(order["clientOrderId"]) for order in raw_orders}
