import argparse
import asyncio
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess

from hummingbot.strategy_v2.controllers.executor_recovery import ExecutorRecoveryStore


def order_records(payload):
    for executor in payload.get("executors", []):
        for field in ("open_order", "take_profit_order", "close_order"):
            order = executor.get(field)
            if order is not None:
                yield executor["executor_id"], order
        for order in executor.get("loss_exit_orders", []):
            yield executor["executor_id"], order


async def run_diagnostics(store, adapter):
    try:
        payload = store.load()
        if payload is None:
            return "READY", {"state": "READY", "reason": "no recovery records"}
        order_reports = []
        differences = []
        seen = set()
        for executor_id, local in order_records(payload):
            order_id = local["client_order_id"]
            if order_id in seen:
                continue
            seen.add(order_id)
            remote = await adapter.fetch_order_snapshot(order_id)
            order_reports.append({
                "executor_id": executor_id,
                "order_id": order_id,
                "local_status": local.get("status"),
                "exchange_status": remote.status,
                "local_filled": local["filled_amount"],
                "exchange_filled": str(remote.filled_amount),
            })
            if remote.status == "UNKNOWN":
                differences.append(f"{order_id}: exchange state UNKNOWN")
                continue
            if remote.client_order_id != order_id:
                differences.append(f"{order_id}: order ID mismatch")
            local_original = Decimal(str(local["original_amount"]))
            local_filled = Decimal(str(local["filled_amount"]))
            if remote.original_amount != local_original:
                differences.append(f"{order_id}: original amount mismatch")
            if remote.filled_amount < local_filled:
                differences.append(f"{order_id}: filled amount regressed")
        state = "BLOCKED" if differences else "READY"
        return state, {
            "state": state,
            "controller_id": payload["controller_id"],
            "connector_name": payload["connector_name"],
            "trading_pair": payload["trading_pair"],
            "orders": order_reports,
            "differences": differences,
        }
    except Exception as error:
        return "BLOCKED", {"state": "BLOCKED", "error": str(error)}


def make_binance_adapter(connector_name, trading_pair):
    from hummingbot.client.config.config_crypt import ETHKeyFileSecretManger
    from hummingbot.client.config.security import Security
    from hummingbot.connector.exchange.binance.binance_exchange import BinanceExchange
    from hummingbot.connector.exchange.binance.binance_order_recovery import (
        BinanceOrderRecoveryAdapter,
    )

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


async def worker(args):
    store = ExecutorRecoveryStore(args.controller_id, Path(args.root))
    payload = store.load()
    if payload is None:
        report = {"state": "READY", "reason": "no recovery records"}
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if payload["connector_name"] != "binance":
        report = {
            "state": "BLOCKED",
            "error": f"Unsupported recovery connector: {payload['connector_name']}",
        }
        print(json.dumps(report, ensure_ascii=False))
        return 2
    adapter = make_binance_adapter(
        payload["connector_name"], payload["trading_pair"]
    )
    state, report = await run_diagnostics(store, adapter)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if state == "READY" else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Condor order recovery diagnostics")
    parser.add_argument("--container")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--controller-id", default="pmm_mister_loss_exit_sample")
    parser.add_argument("--root", default="data/pmm_mister_loss_exit/runtime")
    args = parser.parse_args(argv)
    if args.worker:
        return asyncio.run(worker(args))
    if not args.container:
        parser.error("--container is required outside worker mode")
    command = [
        "docker", "exec", args.container,
        "/opt/conda/envs/hummingbot/bin/python",
        "/home/hummingbot/scripts/condor_recovery_check.py",
        "--worker", "--controller-id", args.controller_id, "--root", args.root,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.stdout:
        print(result.stdout.strip())
    elif result.returncode != 0:
        print(f"WORKER_FAILED={result.returncode}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
