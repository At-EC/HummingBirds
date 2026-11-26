from decimal import Decimal
from enum import Enum
from typing import Optional

from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.executors.position_executor.data_types import LossExitConfig


class LossExitState(str, Enum):
    DISABLED = "DISABLED"
    WATCHING = "WATCHING"
    ACTIVATION_WAIT = "ACTIVATION_WAIT"
    ELIGIBLE = "ELIGIBLE"
    ACTIVATING = "ACTIVATING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


def calculate_loss_pct(side: TradeType, entry_price: Decimal, current_price: Decimal) -> Decimal:
    if entry_price <= 0 or current_price <= 0:
        raise ValueError("entry_price and current_price must be greater than 0")
    if side == TradeType.BUY:
        return (entry_price - current_price) / entry_price
    if side == TradeType.SELL:
        return (current_price - entry_price) / entry_price
    raise ValueError("side must be BUY or SELL")


def calculate_loss_exit_price(side: TradeType, current_price: Decimal, offset_pct: Decimal) -> Decimal:
    if current_price <= 0:
        raise ValueError("current_price must be greater than 0")
    if side == TradeType.BUY:
        return current_price * (Decimal("1") + offset_pct)
    if side == TradeType.SELL:
        return current_price * (Decimal("1") - offset_pct)
    raise ValueError("side must be BUY or SELL")


class LossExitTracker:
    def __init__(self, config: LossExitConfig):
        self.config = config
        self.state = LossExitState.WATCHING
        self.loss_pct = Decimal("0")
        self.condition_since: Optional[float] = None
        self.eligible_since: Optional[float] = None
        self.last_successful_observation_at: Optional[float] = None
        self.last_requote_at: Optional[float] = None
        self.retry_after: Optional[float] = None
        self.requote_count = 0
        self._is_requote = False

    def observe(self, loss_pct: Decimal, timestamp: float) -> LossExitState:
        self.loss_pct = loss_pct
        self.last_successful_observation_at = timestamp
        if self.state in (LossExitState.ACTIVATING, LossExitState.ACTIVE,
                          LossExitState.COMPLETED, LossExitState.TERMINATED):
            return self.state
        if loss_pct < self.config.trigger_pct:
            self.state = LossExitState.WATCHING
            self.condition_since = None
            self.eligible_since = None
            return self.state
        if self.condition_since is None:
            self.condition_since = timestamp
            self.state = LossExitState.ACTIVATION_WAIT
        if timestamp - self.condition_since >= self.config.activation_delay_seconds:
            if self.state != LossExitState.ELIGIBLE:
                self.eligible_since = timestamp
            self.state = LossExitState.ELIGIBLE
        return self.state

    def activate(self, timestamp: float) -> None:
        if self.state != LossExitState.ELIGIBLE:
            raise ValueError(f"Cannot activate loss exit from {self.state.value}")
        self.state = LossExitState.ACTIVATING
        self.last_requote_at = timestamp
        self.retry_after = None
        self._is_requote = False

    def can_requote(self, timestamp: float) -> bool:
        return (self.state == LossExitState.ACTIVE and self.last_requote_at is not None
                and timestamp - self.last_requote_at >= self.config.cooldown_seconds)

    def can_place(self, timestamp: float) -> bool:
        return (self.state == LossExitState.ACTIVATING
                and (self.retry_after is None or timestamp >= self.retry_after))

    def begin_requote(self) -> None:
        if self.state != LossExitState.ACTIVE:
            raise ValueError(f"Cannot requote loss exit from {self.state.value}")
        self.state = LossExitState.ACTIVATING
        self.retry_after = None
        self._is_requote = True

    def mark_order_placed(self, timestamp: float) -> None:
        if self.state != LossExitState.ACTIVATING:
            raise ValueError(f"Cannot mark order placed from {self.state.value}")
        self.state = LossExitState.ACTIVE
        self.last_requote_at = timestamp
        self.retry_after = None
        if self._is_requote:
            self.requote_count += 1
        self._is_requote = False

    def note_order_failure(self, timestamp: float) -> None:
        if self.state not in (LossExitState.ACTIVATING, LossExitState.ACTIVE):
            raise ValueError(f"Cannot note order failure from {self.state.value}")
        self.state = LossExitState.ACTIVATING
        self.retry_after = timestamp + self.config.cooldown_seconds

    def terminate(self, completed: bool) -> None:
        if self.state in (LossExitState.COMPLETED, LossExitState.TERMINATED):
            return
        self.state = LossExitState.COMPLETED if completed else LossExitState.TERMINATED
