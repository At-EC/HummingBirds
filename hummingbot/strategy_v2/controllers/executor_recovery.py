import json
import math
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


RECOVERY_SCHEMA_VERSION = 1
ORDER_STATUSES = {
    "OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELED", "FAILED", "UNKNOWN",
}


@dataclass(frozen=True)
class RecoveredOrderSnapshot:
    client_order_id: str
    exchange_order_id: str | None
    side: str
    order_type: str
    price: Decimal
    original_amount: Decimal
    filled_amount: Decimal
    remaining_amount: Decimal
    status: str
    updated_at: float

    def __post_init__(self):
        if not self.client_order_id:
            raise ValueError("client_order_id is required")
        if self.status not in ORDER_STATUSES:
            raise ValueError(f"unsupported recovered order status: {self.status}")
        if self.original_amount < 0 or self.filled_amount < 0:
            raise ValueError("order amounts must be non-negative")
        if self.filled_amount > self.original_amount:
            raise ValueError("filled amount exceeds original amount")
        if self.remaining_amount != self.original_amount - self.filled_amount:
            raise ValueError("remaining amount does not match order amounts")
        if not math.isfinite(self.updated_at):
            raise ValueError("updated_at must be finite")


def _validate_order(order: dict, seen_order_ids: set[str]) -> None:
    if not isinstance(order, dict):
        raise ValueError("order record must be an object")
    order_id = order.get("client_order_id")
    if not isinstance(order_id, str) or not order_id:
        raise ValueError("client_order_id is required")
    if order_id in seen_order_ids:
        raise ValueError(f"duplicate order id: {order_id}")
    seen_order_ids.add(order_id)
    try:
        original = Decimal(str(order["original_amount"]))
        filled = Decimal(str(order["filled_amount"]))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid order amounts for {order_id}") from exc
    if not original.is_finite() or not filled.is_finite():
        raise ValueError(f"invalid order amounts for {order_id}")
    if original < 0 or filled < 0 or filled > original:
        raise ValueError(f"invalid order amounts for {order_id}")


def validate_recovery_payload(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError("recovery payload must be an object")
    if payload.get("schema_version") != RECOVERY_SCHEMA_VERSION:
        raise ValueError("unsupported recovery schema version")
    for field in ("controller_id", "connector_name", "trading_pair"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            raise ValueError(f"{field} is required")
    try:
        updated_at = float(payload["updated_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("updated_at must be finite") from exc
    if not math.isfinite(updated_at):
        raise ValueError("updated_at must be finite")
    executors = payload.get("executors")
    if not isinstance(executors, list):
        raise ValueError("executors must be a list")
    seen_executor_ids = set()
    seen_order_ids = set()
    loss_exit_locks = 0
    for executor in executors:
        if not isinstance(executor, dict):
            raise ValueError("executor record must be an object")
        executor_id = executor.get("executor_id")
        if not isinstance(executor_id, str) or not executor_id:
            raise ValueError("executor_id is required")
        if executor_id in seen_executor_ids:
            raise ValueError(f"duplicate executor id: {executor_id}")
        seen_executor_ids.add(executor_id)
        if not isinstance(executor.get("executor_config"), dict):
            raise ValueError(f"executor_config is required for {executor_id}")
        for field in ("open_order", "take_profit_order", "close_order"):
            order = executor.get(field)
            if order is not None:
                _validate_order(order, seen_order_ids)
        loss_exit_orders = executor.get("loss_exit_orders", [])
        if not isinstance(loss_exit_orders, list):
            raise ValueError("loss_exit_orders must be a list")
        for order in loss_exit_orders:
            _validate_order(order, seen_order_ids)
        loss_exit = executor.get("loss_exit", {})
        if not isinstance(loss_exit, dict):
            raise ValueError("loss_exit must be an object")
        loss_exit_locks += bool(loss_exit.get("lock_held", False))
    if loss_exit_locks > 1:
        raise ValueError("multiple loss exit locks found")


class ExecutorRecoveryStore:
    def __init__(self, controller_id: str, root: Path):
        if not controller_id:
            raise ValueError("controller_id is required")
        self.controller_id = controller_id
        self.path = root / f"{controller_id}.json"

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"unable to read recovery store: {self.path}") from exc
        validate_recovery_payload(payload)
        if payload["controller_id"] != self.controller_id:
            raise ValueError("recovery store controller mismatch")
        return payload

    def save(self, payload: dict) -> None:
        validate_recovery_payload(payload)
        if payload["controller_id"] != self.controller_id:
            raise ValueError("recovery store controller mismatch")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
