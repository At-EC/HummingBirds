from decimal import Decimal


class OrderBudgetGuard:
    """Process-local order budget state isolated by controller ID."""

    _states = {}
    _error_tokens = (
        "no budget",
        "not enough budget",
        "insufficient balance",
        "insufficient funds",
        "balance is insufficient",
        "-2010",
    )

    @classmethod
    def reset(cls, controller_id=None):
        if controller_id is None:
            cls._states.clear()
        else:
            cls._states.pop(controller_id, None)

    @classmethod
    def is_no_budget_error(cls, message):
        normalized = (message or "").lower()
        return any(token in normalized for token in cls._error_tokens)

    @classmethod
    def is_paused(cls, controller_id, now):
        state = cls._states.get(controller_id, {})
        return state.get("resume_at") is not None and now < state["resume_at"]

    @classmethod
    def note_no_budget(cls, controller_id, now, retry_seconds, message):
        cls._states.setdefault(controller_id, {}).update({
            "paused_at": now,
            "resume_at": now + retry_seconds,
            "last_error": message,
        })

    @classmethod
    def note_fill(cls, controller_id):
        state = cls._states.setdefault(controller_id, {})
        state["resume_at"] = None

    @classmethod
    def check_minimum(cls, controller_id, amount: Decimal, price: Decimal, minimum_quote: Decimal):
        notional = abs(amount * price)
        if minimum_quote <= 0 or notional >= minimum_quote:
            return True, None
        reason = f"notional {notional} is below minimum {minimum_quote}"
        cls._states.setdefault(controller_id, {})["last_skip_reason"] = reason
        return False, reason

    @classmethod
    def should_log(cls, controller_id, reason, now, interval=60):
        state = cls._states.setdefault(controller_id, {})
        if state.get("last_log_reason") == reason and now - state.get("last_log_at", 0) < interval:
            return False
        state.update({"last_log_reason": reason, "last_log_at": now})
        return True

    @classmethod
    def snapshot(cls, controller_id, now):
        state = cls._states.get(controller_id, {})
        return {
            "no_budget_paused": cls.is_paused(controller_id, now),
            "no_budget_resume_at": state.get("resume_at"),
            "no_budget_last_error": state.get("last_error"),
            "min_order_last_skip_reason": state.get("last_skip_reason"),
        }
