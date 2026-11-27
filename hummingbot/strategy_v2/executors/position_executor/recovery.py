import json
from decimal import Decimal

from hummingbot.core.data_type.common import OrderType, PositionAction, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState
from hummingbot.strategy_v2.controllers.executor_recovery import RecoveredOrderSnapshot
from hummingbot.strategy_v2.executors.position_executor.loss_exit import LossExitState
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType, TrackedOrder


class RecoveryBlocked(RuntimeError):
    pass


class ExecutorRuntimeRestorer:
    ORDER_STATES = {
        "OPEN": OrderState.OPEN,
        "PARTIALLY_FILLED": OrderState.PARTIALLY_FILLED,
        "FILLED": OrderState.FILLED,
        "CANCELED": OrderState.CANCELED,
        "FAILED": OrderState.FAILED,
    }

    @staticmethod
    def _snapshot_order(tracked, fallback_amount=Decimal("0"), fallback_price=None,
                        fallback_side=None, fallback_type=None):
        if tracked is None:
            return None
        order = tracked.order
        original = order.amount if order is not None else fallback_amount
        price = tracked.price if tracked.price is not None else fallback_price
        side = order.trade_type.name if order is not None else fallback_side
        order_type = order.order_type.name if order is not None else fallback_type
        if order is not None and order.is_filled:
            status = "FILLED"
        elif order is not None and order.current_state == OrderState.CANCELED:
            status = "CANCELED"
        elif order is not None and order.current_state == OrderState.FAILED:
            status = "FAILED"
        elif tracked.executed_amount_base > 0:
            status = "PARTIALLY_FILLED"
        else:
            status = "OPEN"
        return {
            "client_order_id": tracked.order_id,
            "exchange_order_id": order.exchange_order_id if order is not None else None,
            "side": side,
            "order_type": order_type,
            "price": str(price),
            "original_amount": str(original),
            "filled_amount": str(tracked.executed_amount_base),
            "executed_amount_quote": str(tracked.executed_amount_quote),
            "creation_timestamp": tracked.creation_timestamp,
            "updated_at": tracked.last_update_timestamp,
            "status": status,
            "fill_checkpoint": {
                "trade_ids": sorted(order.order_fills) if order is not None else [],
            },
        }

    @classmethod
    def snapshot(cls, executor) -> dict:
        config = executor.config
        loss_exit = executor._loss_exit
        return {
            "executor_id": config.id,
            "executor_config": json.loads(config.model_dump_json()),
            "open_order": cls._snapshot_order(
                executor._open_order,
                fallback_amount=config.amount,
                fallback_price=config.entry_price,
                fallback_side=config.side.name,
                fallback_type=config.triple_barrier_config.open_order_type.name,
            ),
            "take_profit_order": cls._snapshot_order(
                executor._take_profit_limit_order,
                fallback_amount=config.amount,
                fallback_price=config.entry_price,
                fallback_side=executor.close_order_side.name,
                fallback_type=config.triple_barrier_config.take_profit_order_type.name,
            ),
            "close_order": cls._snapshot_order(executor._close_order),
            "loss_exit_orders": [
                cls._snapshot_order(tracked)
                for tracked in executor._loss_exit_orders.values()
            ],
            "terminal_order_ids": sorted(executor._loss_exit_terminal_order_ids),
            "loss_exit": {
                "state": loss_exit.state.value if loss_exit is not None else LossExitState.DISABLED.value,
                "lock_held": executor.loss_exit_lock_held,
                "loss_pct": str(loss_exit.loss_pct) if loss_exit is not None else "0",
                "condition_since": loss_exit.condition_since if loss_exit is not None else None,
                "eligible_since": loss_exit.eligible_since if loss_exit is not None else None,
                "last_successful_observation_at": (
                    loss_exit.last_successful_observation_at if loss_exit is not None else None
                ),
                "last_requote_at": loss_exit.last_requote_at if loss_exit is not None else None,
                "retry_after": loss_exit.retry_after if loss_exit is not None else None,
                "requote_count": loss_exit.requote_count if loss_exit is not None else 0,
                "reconciliation_required": executor._loss_exit_order_reconciliation_required,
            },
        }

    @classmethod
    def _restore_order(cls, record: dict, snapshot: RecoveredOrderSnapshot,
                       trading_pair: str, position_action: PositionAction) -> TrackedOrder:
        if snapshot.status == "UNKNOWN":
            raise RecoveryBlocked(f"Order state is unknown: {record['client_order_id']}")
        if snapshot.client_order_id != record["client_order_id"]:
            raise RecoveryBlocked("Recovered order ID mismatch")
        original = Decimal(str(record["original_amount"]))
        previous_filled = Decimal(str(record["filled_amount"]))
        if snapshot.original_amount != original:
            raise RecoveryBlocked(f"Original amount changed for {snapshot.client_order_id}")
        if snapshot.filled_amount < previous_filled:
            raise RecoveryBlocked(f"Filled amount regressed for {snapshot.client_order_id}")
        order = InFlightOrder(
            client_order_id=snapshot.client_order_id,
            trading_pair=trading_pair,
            order_type=OrderType[snapshot.order_type],
            trade_type=TradeType[snapshot.side],
            amount=snapshot.original_amount,
            creation_timestamp=float(record.get("creation_timestamp") or snapshot.updated_at),
            price=snapshot.price,
            exchange_order_id=snapshot.exchange_order_id,
            initial_state=cls.ORDER_STATES[snapshot.status],
            position=position_action,
        )
        order.executed_amount_base = snapshot.filled_amount
        order.executed_amount_quote = snapshot.filled_amount * snapshot.price
        order.last_update_timestamp = snapshot.updated_at
        tracked = TrackedOrder(order_id=snapshot.client_order_id)
        tracked.order = order
        return tracked

    @classmethod
    def restore(cls, executor, record: dict,
                snapshots: dict[str, RecoveredOrderSnapshot]) -> None:
        if record.get("executor_id") != executor.config.id:
            raise RecoveryBlocked("Executor ID mismatch")
        open_record = record.get("open_order")
        if open_record is None or open_record["client_order_id"] not in snapshots:
            raise RecoveryBlocked("Open order snapshot is missing")
        executor._open_order = cls._restore_order(
            open_record,
            snapshots[open_record["client_order_id"]],
            executor.config.trading_pair,
            PositionAction.OPEN,
        )
        tp_record = record.get("take_profit_order")
        if tp_record is not None:
            order_id = tp_record["client_order_id"]
            if order_id not in snapshots:
                raise RecoveryBlocked(f"TP snapshot is missing: {order_id}")
            snapshot = snapshots[order_id]
            tracked = cls._restore_order(
                tp_record, snapshot, executor.config.trading_pair, executor.close_position_action
            )
            if snapshot.status in ("OPEN", "PARTIALLY_FILLED"):
                executor._take_profit_limit_order = tracked
            elif snapshot.status == "FILLED":
                executor._close_order = tracked
                executor.close_type = CloseType.TAKE_PROFIT
                executor._status = RunnableStatus.SHUTTING_DOWN
            elif snapshot.status in ("CANCELED", "FAILED"):
                executor.close_type = CloseType.POSITION_HOLD
                executor._status = RunnableStatus.SHUTTING_DOWN
            executor._loss_exit_terminal_order_ids.add(order_id)
        for exit_record in record.get("loss_exit_orders", []):
            order_id = exit_record["client_order_id"]
            if order_id not in snapshots:
                raise RecoveryBlocked(f"Loss exit snapshot is missing: {order_id}")
            if executor._take_profit_limit_order and executor._take_profit_limit_order.order_id == order_id:
                tracked = executor._take_profit_limit_order
            elif executor._close_order and executor._close_order.order_id == order_id:
                tracked = executor._close_order
            else:
                tracked = cls._restore_order(
                    exit_record, snapshots[order_id], executor.config.trading_pair,
                    executor.close_position_action,
                )
            executor._loss_exit_orders[order_id] = tracked
        executor._loss_exit_terminal_order_ids.update(record.get("terminal_order_ids", []))
        loss_record = record.get("loss_exit", {})
        if executor._loss_exit is not None:
            state = LossExitState(loss_record.get("state", "WATCHING"))
            executor._loss_exit.state = state
            executor._loss_exit.loss_pct = Decimal(str(loss_record.get("loss_pct", "0")))
            executor._loss_exit.condition_since = loss_record.get("condition_since")
            executor._loss_exit.eligible_since = loss_record.get("eligible_since")
            executor._loss_exit.last_successful_observation_at = loss_record.get(
                "last_successful_observation_at"
            )
            executor._loss_exit.last_requote_at = loss_record.get("last_requote_at")
            executor._loss_exit.retry_after = loss_record.get("retry_after")
            executor._loss_exit.requote_count = int(loss_record.get("requote_count", 0))
            executor._loss_exit_activated = state in (
                LossExitState.ACTIVATING, LossExitState.ACTIVE, LossExitState.COMPLETED
            )
        executor._loss_exit_order_reconciliation_required = bool(
            loss_record.get("reconciliation_required", False)
        )
