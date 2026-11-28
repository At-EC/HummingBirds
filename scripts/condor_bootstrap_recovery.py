import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.controllers.executor_recovery import ExecutorRecoveryStore
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig, TripleBarrierConfig


def discover_controller_identity(root: Path) -> dict:
    identities = []
    for path in sorted(root.glob("*.yml")):
        values = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            if key in ("id", "connector_name", "trading_pair"):
                values[key] = value.strip().strip("'\"")
        if all(values.get(field) for field in ("id", "connector_name", "trading_pair")):
            identities.append(values)
    if len(identities) != 1:
        raise ValueError(f"Expected one complete controller config, found {len(identities)}")
    return identities[0]


def build_adoption_record(snapshot, connector_name: str, trading_pair: str) -> dict:
    executor_id = "adopted-" + sha256(snapshot.client_order_id.encode()).hexdigest()[:16]
    order_type = OrderType[snapshot.order_type]
    config = PositionExecutorConfig(
        id=executor_id,
        type="position_executor",
        timestamp=snapshot.updated_at,
        trading_pair=trading_pair,
        connector_name=connector_name,
        side=TradeType[snapshot.side],
        entry_price=snapshot.price,
        amount=snapshot.original_amount,
        leverage=1,
        triple_barrier_config=TripleBarrierConfig(
            open_order_type=order_type,
            take_profit=None,
            take_profit_order_type=order_type,
        ),
    )
    return {
        "executor_id": executor_id,
        "executor_config": json.loads(config.model_dump_json()),
        "open_order": {
            "client_order_id": snapshot.client_order_id,
            "exchange_order_id": snapshot.exchange_order_id,
            "side": snapshot.side,
            "order_type": snapshot.order_type,
            "price": str(snapshot.price),
            "original_amount": str(snapshot.original_amount),
            "filled_amount": str(snapshot.filled_amount),
            "executed_amount_quote": str(snapshot.filled_amount * snapshot.price),
            "creation_timestamp": snapshot.updated_at,
            "updated_at": snapshot.updated_at,
            "status": snapshot.status,
            "fill_checkpoint": {},
        },
        "take_profit_order": None,
        "close_order": None,
        "loss_exit_orders": [],
        "terminal_order_ids": [],
        "loss_exit": {
            "state": "WATCHING",
            "lock_held": False,
            "reconciliation_required": False,
        },
    }


def merge_adoption_records(payload: dict, snapshots: list, controller_id: str, now: float) -> int:
    existing_ids = set()
    for executor in payload["executors"]:
        for field in ("open_order", "take_profit_order", "close_order"):
            order = executor.get(field)
            if order is not None:
                existing_ids.add(order["client_order_id"])
        for order in executor.get("loss_exit_orders", []):
            existing_ids.add(order["client_order_id"])
    added = 0
    for snapshot in snapshots:
        if snapshot.client_order_id in existing_ids:
            continue
        payload["executors"].append(
            build_adoption_record(snapshot, payload["connector_name"], payload["trading_pair"])
        )
        existing_ids.add(snapshot.client_order_id)
        added += 1
    payload["controller_id"] = controller_id
    payload["updated_at"] = now
    return added


def make_binance_adapter(connector_name: str, trading_pair: str):
    from hummingbot.client.config.config_crypt import ETHKeyFileSecretManger
    from hummingbot.client.config.security import Security
    from hummingbot.connector.exchange.binance.binance_exchange import BinanceExchange
    from hummingbot.connector.exchange.binance.binance_order_recovery import BinanceOrderRecoveryAdapter

    password = os.environ.get("CONFIG_PASSWORD") or os.environ.get("HBOT_PASSWORD")
    if not password:
        raise RuntimeError("Connector credentials are unavailable in this container")
    Security.login(ETHKeyFileSecretManger(password))
    keys = Security.api_keys(connector_name)
    connector = BinanceExchange(
        binance_api_key=keys["binance_api_key"],
        binance_api_secret=keys["binance_api_secret"],
        trading_pairs=[trading_pair],
        trading_required=True,
    )
    return BinanceOrderRecoveryAdapter(connector, trading_pair)


async def fetch_open_orders(adapter) -> list:
    if hasattr(adapter, "fetch_open_orders"):
        return await adapter.fetch_open_orders()
    order_ids = await adapter.fetch_open_order_ids()
    return [
        await adapter.fetch_order_snapshot(order_id)
        for order_id in sorted(order_ids)
    ]


async def main_async(args):
    identity = discover_controller_identity(Path("conf/controllers"))
    controller_id = args.controller_id or identity["id"]
    connector_name = args.connector_name or identity["connector_name"]
    trading_pair = args.trading_pair or identity["trading_pair"]
    if connector_name != "binance":
        raise ValueError(f"Unsupported recovery connector: {connector_name}")
    adapter = make_binance_adapter(connector_name, trading_pair)
    snapshots = await fetch_open_orders(adapter)
    store = ExecutorRecoveryStore(controller_id, Path(args.root))
    payload = store.load() or {
        "schema_version": 1,
        "controller_id": controller_id,
        "connector_name": connector_name,
        "trading_pair": trading_pair,
        "updated_at": 0.0,
        "executors": [],
    }
    import time
    added = merge_adoption_records(payload, snapshots, controller_id, time.time())
    store.save(payload)
    print(json.dumps({
        "controller_id": controller_id,
        "open_orders": len(snapshots),
        "adopted": added,
        "total_executors": len(payload["executors"]),
    }))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bootstrap recovery records for existing open orders")
    parser.add_argument("--controller-id")
    parser.add_argument("--root", default="data/pmm_mister_loss_exit/runtime")
    parser.add_argument("--connector-name")
    parser.add_argument("--trading-pair")
    args = parser.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
