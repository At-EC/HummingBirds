import asyncio
import math
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator, model_validator

from controllers.generic import pmm_mister as _pmm_mister
from hummingbot.core.data_type.common import PriceType, TradeType
from hummingbot.strategy_v2.controllers.executor_recovery import ExecutorRecoveryStore
from hummingbot.strategy_v2.controllers.loss_exit_recovery import LossExitRecoveryStore
from hummingbot.strategy_v2.controllers.order_budget import OrderBudgetGuard
from hummingbot.strategy_v2.controllers.recovery_coordinator import RecoveryCoordinator
from hummingbot.strategy_v2.executors.data_types import PositionSummary
from hummingbot.strategy_v2.executors.position_executor.data_types import LossExitConfig, PositionExecutorConfig
from hummingbot.strategy_v2.executors.position_executor.loss_exit import LossExitState
from hummingbot.strategy_v2.executors.position_executor.recovery import ExecutorRuntimeRestorer
from hummingbot.strategy_v2.models.executor_actions import (
    ActivateLossExitAction,
    CancelTakeProfitAction,
    CreateExecutorAction,
    ExecutorAction,
    StopExecutorAction,
)


class PMMisterLossExitConfig(_pmm_mister.PMMisterConfig):
    controller_name: str = "pmm_mister_loss_exit"
    loss_exit_trigger_pct: Optional[Decimal] = Field(
        default=None, json_schema_extra={"is_updatable": True}
    )
    loss_exit_offset_pct: Decimal = Field(
        default=Decimal("0.001"), json_schema_extra={"is_updatable": True}
    )
    loss_exit_cooldown_seconds: int = Field(
        default=60, json_schema_extra={"is_updatable": True}
    )
    loss_exit_activation_delay_seconds: int = Field(
        default=300, json_schema_extra={"is_updatable": True}
    )
    tp_order_distance_tolerance_pct: Decimal = Field(
        default=Decimal("0"), ge=0, lt=1,
        json_schema_extra={"is_updatable": True},
    )
    min_order_amount_quote: Decimal = Field(
        default=Decimal("0"), ge=0, json_schema_extra={"is_updatable": True}
    )
    no_budget_retry_seconds: int = Field(
        default=300, ge=1, json_schema_extra={"is_updatable": True}
    )
    no_budget_tp_cancel_distance_pct: Decimal = Field(
        default=Decimal("0"), ge=0, json_schema_extra={"is_updatable": True}
    )

    @field_validator("loss_exit_trigger_pct", mode="before")
    @classmethod
    def parse_optional_trigger(cls, value):
        if value is None or value == "":
            return None
        return Decimal(str(value))

    @model_validator(mode="after")
    def validate_loss_exit(self):
        if self.loss_exit_trigger_pct is None:
            return self
        LossExitConfig(
            trigger_pct=self.loss_exit_trigger_pct,
            offset_pct=self.loss_exit_offset_pct,
            cooldown_seconds=self.loss_exit_cooldown_seconds,
            activation_delay_seconds=self.loss_exit_activation_delay_seconds,
        )
        if not self.take_profit_order_type.is_limit_type():
            raise ValueError("loss_exit requires take_profit_order_type LIMIT or LIMIT_MAKER")
        return self


class PMMisterLossExit(_pmm_mister.PMMister):
    SNAPSHOT_MAX_AGE_SECONDS = 5

    def __init__(self, config: PMMisterLossExitConfig, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self._loss_exit_recovery_store = LossExitRecoveryStore(config.id)
        self._loss_exit_recovery_required = self._loss_exit_recovery_store.has_records()
        self._loss_exit_runtime_owns_record = False
        self._loss_exit_recovery_executor_id: Optional[str] = None
        self._loss_exit_recovery_logged = False
        self.recovery_state = (
            "PENDING"
            if os.getenv("HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN", "").lower() == "true"
            else "DISABLED"
        )
        self._recovery_pending = {}
        self._recovery_actions = []
        self._recovery_task = None
        self._recovery_last_snapshots = None
        self._no_budget_last_cancel_pause_at = None
        store = ExecutorRecoveryStore(
            config.id, Path("data/pmm_mister_loss_exit/runtime")
        )

        def adapter_factory():
            if config.connector_name != "binance":
                raise ValueError(f"Unsupported recovery connector: {config.connector_name}")
            from hummingbot.connector.exchange.binance.binance_order_recovery import (
                BinanceOrderRecoveryAdapter,
            )
            connector = self.market_data_provider.get_connector(config.connector_name)
            return BinanceOrderRecoveryAdapter(connector, config.trading_pair)

        self._recovery_coordinator = RecoveryCoordinator(
            store, adapter_factory, ExecutorRuntimeRestorer
        )

    def _get_open_tp_prices(self, side: Optional[TradeType] = None) -> List[Decimal]:
        prices = []
        for executor in self.executors_info:
            info = executor.custom_info
            if not info.get("take_profit_order_open", False):
                continue
            entry_side = getattr(getattr(executor, "config", None), "side", None)
            tp_side = None
            if entry_side == TradeType.BUY:
                tp_side = TradeType.SELL
            elif entry_side == TradeType.SELL:
                tp_side = TradeType.BUY
            if side is not None and tp_side != side:
                continue
            try:
                price = Decimal(str(info.get("take_profit_order_price")))
            except (InvalidOperation, TypeError, ValueError):
                continue
            if price.is_finite() and price > 0:
                prices.append(price)
        return prices

    def _is_tp_distance_conflict(self, price: Decimal, side: Optional[TradeType] = None) -> bool:
        tolerance = self.config.tp_order_distance_tolerance_pct
        if tolerance <= 0:
            return False
        return any(
            abs(price - tp_price) / tp_price < tolerance
            for tp_price in self._get_open_tp_prices(side)
        )

    def _is_expected_tp_distance_conflict(self, level_id: str, price: Decimal) -> bool:
        take_profit = self.config.take_profit
        if not take_profit or not self.config.take_profit_order_type.is_limit_type():
            return False
        if level_id.startswith("buy"):
            tp_side = TradeType.SELL
            expected_tp_price = price * (1 + take_profit)
        elif level_id.startswith("sell"):
            tp_side = TradeType.BUY
            expected_tp_price = price * (1 - take_profit)
        else:
            return False
        return self._is_tp_distance_conflict(expected_tp_price, tp_side)

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        if self.recovery_state not in ("READY", "DISABLED"):
            return None
        now = self.market_data_provider.time()
        if OrderBudgetGuard.is_paused(self.config.id, now):
            return None
        allowed, reason = OrderBudgetGuard.check_minimum(
            self.config.id, amount, price, self.config.min_order_amount_quote
        )
        if not allowed:
            if OrderBudgetGuard.should_log(self.config.id, reason, now):
                self.logger().warning(reason)
            return None
        if self._is_expected_tp_distance_conflict(level_id, price):
            return None
        executor_config = super().get_executor_config(level_id, price, amount)
        executor_config.controller_id = self.config.id
        executor_config.min_order_amount_quote = self.config.min_order_amount_quote
        executor_config.no_budget_retry_seconds = self.config.no_budget_retry_seconds
        if self.config.loss_exit_trigger_pct is not None:
            barriers = executor_config.triple_barrier_config.model_copy(deep=True)
            barriers.loss_exit = LossExitConfig(
                trigger_pct=self.config.loss_exit_trigger_pct,
                offset_pct=self.config.loss_exit_offset_pct,
                cooldown_seconds=self.config.loss_exit_cooldown_seconds,
                activation_delay_seconds=self.config.loss_exit_activation_delay_seconds,
            )
            executor_config.triple_barrier_config = barriers
        return executor_config

    def _get_eligible_loss_exit_candidates(self, now: float) -> List:
        candidates = []
        for executor in self.executors_info:
            info = executor.custom_info
            if not executor.is_active or not executor.is_trading:
                continue
            if info.get("loss_exit_state") != LossExitState.ELIGIBLE.value:
                continue
            if not info.get("take_profit_order_open", False):
                continue
            try:
                loss_pct = Decimal(str(info.get("loss_pct")))
                eligible_since = float(info.get("eligible_since"))
                observed_at = float(info.get("last_successful_observation_at"))
                observation_age = now - observed_at
                if not loss_pct.is_finite():
                    raise ValueError("loss_pct is not finite")
                if not math.isfinite(eligible_since) or eligible_since > now:
                    raise ValueError("eligible_since is not finite or is in the future")
                if not math.isfinite(observed_at) or not 0 <= observation_age <= self.SNAPSHOT_MAX_AGE_SECONDS:
                    raise ValueError("last successful observation is stale or invalid")
            except (InvalidOperation, TypeError, ValueError, OverflowError) as error:
                self.logger().warning(
                    f"Ignoring invalid loss exit candidate {executor.id}: {error}"
                )
                continue
            candidates.append(executor)
        return candidates

    def get_loss_exit_activation_action(self) -> Optional[ActivateLossExitAction]:
        # Loss exit must remain available during a budget pause: it cancels
        # the original TP and replaces it to release inventory and budget.
        if self.recovery_state not in ("READY", "DISABLED"):
            return None
        if self.config.manual_kill_switch or self._global_close_phase is not None:
            return None
        if self._loss_exit_runtime_owns_record:
            return None
        if any(executor.custom_info.get("loss_exit_lock_held", False) for executor in self.executors_info):
            return None

        candidates = self._get_eligible_loss_exit_candidates(self.market_data_provider.time())
        if not candidates:
            return None
        selected = min(
            candidates,
            key=lambda executor: (
                -Decimal(str(executor.custom_info["loss_pct"])),
                float(executor.custom_info["eligible_since"]),
                executor.id,
            ),
        )
        return ActivateLossExitAction(controller_id=self.config.id, executor_id=selected.id)

    def _get_owned_loss_exit_executor(self):
        return next(
            (item for item in self.executors_info
             if item.id == self._loss_exit_recovery_executor_id),
            None,
        )

    def _has_fresh_loss_exit_snapshot(self, info: dict) -> bool:
        try:
            snapshot_at = float(info.get("loss_exit_snapshot_at"))
            snapshot_age = self.market_data_provider.time() - snapshot_at
        except (TypeError, ValueError, OverflowError):
            return False
        return math.isfinite(snapshot_at) and 0 <= snapshot_age <= self.SNAPSHOT_MAX_AGE_SECONDS

    def _loss_exit_reconciliation_required(self, info: dict) -> bool:
        record = self._loss_exit_recovery_store.load() or {}
        return bool(
            record.get("reconciliation_required", False)
            or info.get("loss_exit_reconciliation_required", False)
        )

    def _is_loss_exit_recovery_complete(self) -> bool:
        executor = self._get_owned_loss_exit_executor()
        if executor is None or executor.is_done is not True:
            return False
        info = executor.custom_info
        if info.get("loss_exit_state") not in {
                LossExitState.COMPLETED.value, LossExitState.TERMINATED.value}:
            return False
        if self._loss_exit_reconciliation_required(info):
            return False
        if info.get("loss_exit_lock_held", False) or info.get("active_exit_order_id"):
            return False
        return self._has_fresh_loss_exit_snapshot(info)

    def _is_loss_exit_activation_refused(self) -> bool:
        executor = self._get_owned_loss_exit_executor()
        if executor is None or not executor.is_active:
            return False
        info = executor.custom_info
        if info.get("loss_exit_state") not in {
                LossExitState.WATCHING.value,
                LossExitState.ACTIVATION_WAIT.value,
                LossExitState.ELIGIBLE.value}:
            return False
        if self._loss_exit_reconciliation_required(info):
            return False
        if info.get("loss_exit_lock_held", False) or info.get("active_exit_order_id"):
            return False
        return self._has_fresh_loss_exit_snapshot(info)

    def _save_loss_exit_recovery(self, executor_id: str, snapshot) -> None:
        previous = self._loss_exit_recovery_store.load() or {} if self._loss_exit_runtime_owns_record else {}
        active_order_id = snapshot.custom_info.get("active_exit_order_id") if snapshot else None
        reconciliation_required = bool(
            previous.get("reconciliation_required", False)
            or (snapshot and snapshot.custom_info.get("loss_exit_reconciliation_required", False))
        )
        if active_order_id is None:
            active_order_id = previous.get("active_order_id")
        self._loss_exit_recovery_store.save({
            "controller_id": self.config.id,
            "connector_name": self.config.connector_name,
            "trading_pair": self.config.trading_pair,
            "executor_id": executor_id,
            "active_order_id": active_order_id,
            "reconciliation_required": reconciliation_required,
        })
        self._loss_exit_recovery_executor_id = executor_id
        self._loss_exit_runtime_owns_record = True

    def _clear_loss_exit_recovery(self) -> None:
        self._loss_exit_recovery_store.clear()
        self._loss_exit_runtime_owns_record = False
        self._loss_exit_recovery_executor_id = None

    def _sync_loss_exit_recovery(self, actions: List[ExecutorAction]) -> None:
        activation = next((action for action in actions if isinstance(action, ActivateLossExitAction)), None)
        active = next(
            (executor for executor in self.executors_info
             if executor.custom_info.get("loss_exit_lock_held", False)),
            None,
        )
        if activation is not None:
            self._save_loss_exit_recovery(activation.executor_id, active)
            return
        if self._loss_exit_runtime_owns_record:
            owned = self._get_owned_loss_exit_executor()
            if (owned is not None
                    and owned.custom_info.get("loss_exit_reconciliation_required", False)):
                self._save_loss_exit_recovery(owned.id, owned)
            if self._is_loss_exit_recovery_complete() or self._is_loss_exit_activation_refused():
                self._clear_loss_exit_recovery()
            elif active is not None and active.id == self._loss_exit_recovery_executor_id:
                self._save_loss_exit_recovery(active.id, active)
            return
        if active is not None:
            self._save_loss_exit_recovery(active.id, active)

    def mark_recovery_blocked(self, error: str) -> None:
        self.recovery_state = "BLOCKED"
        self.logger().error(f"Order recovery blocked: {error}")

    def get_recovery_restore_data(self, executor_id: str):
        return self._recovery_pending.get(executor_id)

    def complete_recovery_executor(self, executor_id: str) -> None:
        self._recovery_pending.pop(executor_id, None)
        if not self._recovery_pending and self.recovery_state == "RESTORING":
            self.recovery_state = "READY"

    async def _prepare_recovery_actions(self) -> None:
        try:
            recovered = await self._recovery_coordinator.load_snapshots()
            if recovered is None:
                self.recovery_state = "READY"
                return
            actions = []
            for record in recovered["payload"]["executors"]:
                executor_id = record["executor_id"]
                executor_config = PositionExecutorConfig(**record["executor_config"])
                self._recovery_pending[executor_id] = {
                    "record": record,
                    "snapshots": recovered["snapshots"][executor_id],
                }
                actions.append(CreateExecutorAction(
                    controller_id=self.config.id,
                    executor_config=executor_config,
                ))
            self._recovery_actions = actions
            self.recovery_state = "RESTORING"
        except Exception as error:
            self.mark_recovery_blocked(str(error))

    def _recovery_actions_step(self) -> List[ExecutorAction]:
        if self.recovery_state == "PENDING":
            self.recovery_state = "RECONCILING"
            self._recovery_task = asyncio.create_task(self._prepare_recovery_actions())
        elif self.recovery_state == "RESTORING":
            actions, self._recovery_actions = self._recovery_actions, []
            return actions
        return []

    def persist_recovery_snapshots(self, executor_snapshots: List[dict]) -> None:
        if self.recovery_state not in ("READY", "DISABLED"):
            return
        import json
        comparable = json.dumps(executor_snapshots, sort_keys=True)
        if comparable == self._recovery_last_snapshots:
            return
        payload = {
            "schema_version": 1,
            "controller_id": self.config.id,
            "connector_name": self.config.connector_name,
            "trading_pair": self.config.trading_pair,
            "updated_at": self.market_data_provider.time(),
            "executors": executor_snapshots,
        }
        try:
            self._recovery_coordinator.store.save(payload)
        except Exception as error:
            self.mark_recovery_blocked(str(error))
            return
        self._recovery_last_snapshots = comparable

    def get_no_budget_tp_cancel_action(self) -> Optional[CancelTakeProfitAction]:
        tolerance = self.config.no_budget_tp_cancel_distance_pct
        now = self.market_data_provider.time()
        budget = OrderBudgetGuard.snapshot(self.config.id, now)
        if tolerance <= 0 or not budget["no_budget_paused"]:
            return None
        pause_at = budget.get("no_budget_paused_at")
        if pause_at == getattr(self, "_no_budget_last_cancel_pause_at", None):
            return None
        current_price = self.market_data_provider.get_price_by_type(
            self.config.connector_name, self.config.trading_pair, PriceType.MidPrice
        )
        if current_price is None or not current_price.is_finite() or current_price <= 0:
            return None
        candidates = []
        for executor in self.executors_info:
            info = executor.custom_info
            if not executor.is_active or not executor.is_trading:
                continue
            if (info.get("no_budget_tp_cancel_requested", False)
                    or info.get("loss_exit_lock_held", False)):
                continue
            if not info.get("take_profit_order_open", False):
                continue
            try:
                tp_price = Decimal(str(info.get("take_profit_order_price")))
            except (InvalidOperation, TypeError, ValueError):
                continue
            if not tp_price.is_finite() or tp_price <= 0:
                continue
            if executor.config.side == TradeType.SELL:
                distance = (current_price - tp_price) / current_price
            elif executor.config.side == TradeType.BUY:
                distance = (tp_price - current_price) / current_price
            else:
                continue
            if distance > tolerance:
                candidates.append((distance, executor))
        if not candidates:
            return None
        _, selected = max(candidates, key=lambda item: (item[0], item[1].id))
        self._no_budget_last_cancel_pause_at = pause_at
        self.logger().info(
            f"Cancel distant TP for no budget: executor={selected.id} "
            f"distance={max(candidates, key=lambda item: item[0])[0]}"
        )
        return CancelTakeProfitAction(
            controller_id=self.config.id,
            executor_id=selected.id,
        )

    def determine_executor_actions(self) -> List[ExecutorAction]:
        if self.recovery_state not in ("READY", "DISABLED"):
            return self._recovery_actions_step()
        actions = super().determine_executor_actions()
        if self._loss_exit_recovery_required:
            if not self._loss_exit_recovery_logged:
                self.logger().error(
                    "Unfinished loss exit record found after restart. Reconcile exchange orders and "
                    "remaining balances, remove the recovery record, then restart this controller."
                )
                self._loss_exit_recovery_logged = True
            return [action for action in actions if isinstance(action, StopExecutorAction)]
        if self._loss_exit_runtime_owns_record:
            self._sync_loss_exit_recovery(actions)
            return actions
        cancel_action = self.get_no_budget_tp_cancel_action()
        if cancel_action is not None:
            actions.append(cancel_action)
            self._sync_loss_exit_recovery(actions)
            return actions
        activation = self.get_loss_exit_activation_action()
        if activation is not None and not any(
                isinstance(action, StopExecutorAction) and action.executor_id == activation.executor_id
                for action in actions):
            actions.append(activation)
        self._sync_loss_exit_recovery(actions)
        return actions

    def get_positions_for_risk(self) -> List[PositionSummary]:
        """Combine enabled executor exposure and net opposite sides by market."""
        positions = {
            (position.connector_name, position.trading_pair): position
            for position in super().get_positions_for_risk()
        }
        enabled_states = {
            LossExitState.WATCHING.value,
            LossExitState.ACTIVATION_WAIT.value,
            LossExitState.ELIGIBLE.value,
            LossExitState.ACTIVATING.value,
            LossExitState.ACTIVE.value,
        }
        seen_executor_ids = set()
        for executor in self.executors_info:
            info = executor.custom_info
            if (not executor.is_active or not executor.is_trading
                    or info.get("level_id") == "global_close"
                    or info.get("loss_exit_state") not in enabled_states
                    or executor.id in seen_executor_ids
                    or "remaining_position_amount" not in info):
                continue
            seen_executor_ids.add(executor.id)
            try:
                amount = Decimal(str(info["remaining_position_amount"]))
                entry_price = Decimal(str(info["current_position_average_price"]))
                mark_price = Decimal(str(info.get(
                    "current_market_price", self.processed_data.get("reference_price")
                )))
                closed_amount = Decimal(str(info.get("close_filled_amount", "0")))
                closed_quote = Decimal(str(info.get("close_filled_amount_quote", "0")))
                volume = Decimal(str(executor.filled_amount_quote))
            except (InvalidOperation, TypeError, ValueError):
                self.logger().warning(f"Skipping invalid active position snapshot {executor.id}")
                continue
            if amount <= 0:
                continue
            side = executor.config.side
            unrealized = ((mark_price - entry_price) * amount if side == TradeType.BUY
                          else (entry_price - mark_price) * amount)
            realized = (closed_quote - closed_amount * entry_price if side == TradeType.BUY
                        else closed_amount * entry_price - closed_quote)
            active_position = PositionSummary(
                connector_name=executor.config.connector_name,
                trading_pair=executor.config.trading_pair,
                volume_traded_quote=volume,
                side=side,
                amount=amount,
                breakeven_price=entry_price,
                unrealized_pnl_quote=unrealized,
                realized_pnl_quote=realized,
                cum_fees_quote=executor.cum_fees_quote,
            )
            key = (active_position.connector_name, active_position.trading_pair)
            previous = positions.get(key)
            if previous is None:
                positions[key] = active_position
                continue
            previous_signed = previous.amount if previous.side == TradeType.BUY else -previous.amount
            active_signed = active_position.amount if side == TradeType.BUY else -active_position.amount
            net_amount = previous_signed + active_signed
            combined_realized = previous.realized_pnl_quote + active_position.realized_pnl_quote
            if previous_signed == 0 or active_signed == 0 or previous_signed * active_signed > 0:
                combined_unrealized = previous.unrealized_pnl_quote + active_position.unrealized_pnl_quote
            else:
                matched = min(abs(previous_signed), abs(active_signed))
                if previous_signed > 0:
                    combined_realized += (
                        active_position.breakeven_price - previous.breakeven_price
                    ) * matched
                else:
                    combined_realized += (
                        previous.breakeven_price - active_position.breakeven_price
                    ) * matched
                combined_unrealized = Decimal("0")
            if net_amount == 0:
                merged_side = previous.side
                breakeven_price = Decimal("0")
                combined_unrealized = Decimal("0")
            else:
                merged_side = TradeType.BUY if net_amount > 0 else TradeType.SELL
                if previous_signed == 0:
                    breakeven_price = active_position.breakeven_price
                elif active_signed == 0:
                    breakeven_price = previous.breakeven_price
                elif previous_signed * active_signed > 0:
                    total_weight = abs(previous_signed) + abs(active_signed)
                    breakeven_price = (
                        abs(previous_signed) * previous.breakeven_price
                        + abs(active_signed) * active_position.breakeven_price
                    ) / total_weight
                elif abs(previous_signed) > abs(active_signed):
                    breakeven_price = previous.breakeven_price
                else:
                    breakeven_price = active_position.breakeven_price
                if previous_signed * active_signed < 0:
                    combined_unrealized = (
                        (mark_price - breakeven_price) * abs(net_amount)
                        if merged_side == TradeType.BUY
                        else (breakeven_price - mark_price) * abs(net_amount)
                    )
            positions[key] = PositionSummary(
                connector_name=previous.connector_name,
                trading_pair=previous.trading_pair,
                volume_traded_quote=previous.volume_traded_quote + active_position.volume_traded_quote,
                side=merged_side,
                amount=abs(net_amount),
                breakeven_price=breakeven_price,
                unrealized_pnl_quote=combined_unrealized,
                realized_pnl_quote=combined_realized,
                cum_fees_quote=previous.cum_fees_quote + active_position.cum_fees_quote,
            )
        return [position for position in positions.values() if position.amount > 0]

    def stop_actions_proposal(self) -> List[ExecutorAction]:
        # Effectivization always wins: expiring TPs must never be kept alive by loss exit.
        return super().stop_actions_proposal()

    def get_custom_info(self) -> dict:
        info = super().get_custom_info()
        active_states = {LossExitState.ACTIVATING.value, LossExitState.ACTIVE.value}
        active = next(
            (executor for executor in self.executors_info
             if executor.custom_info.get("loss_exit_lock_held", False)
             and executor.custom_info.get("loss_exit_state") in active_states),
            None,
        )
        candidate_count = len(self._get_eligible_loss_exit_candidates(self.market_data_provider.time()))
        info.update({
            "loss_exit_active_executor": active.id if active else None,
            "loss_exit_active_side": active.config.side.name if active else None,
            "loss_exit_candidate_count": candidate_count,
            "loss_exit_active_price": active.custom_info.get("active_exit_price") if active else None,
            "loss_exit_remaining_amount": active.custom_info.get("remaining_exit_amount") if active else None,
        })
        info.update(OrderBudgetGuard.snapshot(self.config.id, self.market_data_provider.time()))
        info["min_order_amount_quote"] = str(self.config.min_order_amount_quote)
        return info
