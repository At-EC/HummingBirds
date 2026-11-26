from decimal import Decimal

from hummingbot.strategy_v2.controllers.order_budget import OrderBudgetGuard


def test_pause_is_per_controller_and_recovers_on_fill_or_timeout():
    OrderBudgetGuard.reset()
    OrderBudgetGuard.note_no_budget("bot-a", 100.0, 300, "NO BUDGET")
    assert OrderBudgetGuard.is_paused("bot-a", 101.0)
    assert not OrderBudgetGuard.is_paused("bot-b", 101.0)
    OrderBudgetGuard.note_fill("bot-a")
    assert not OrderBudgetGuard.is_paused("bot-a", 102.0)
    OrderBudgetGuard.note_no_budget("bot-a", 200.0, 300, "insufficient balance")
    assert OrderBudgetGuard.is_paused("bot-a", 499.9)
    assert not OrderBudgetGuard.is_paused("bot-a", 500.0)


def test_minimum_and_error_matching():
    OrderBudgetGuard.reset()
    allowed, reason = OrderBudgetGuard.check_minimum("bot-a", Decimal("1"), Decimal("10"), Decimal("10"))
    assert allowed and reason is None
    allowed, reason = OrderBudgetGuard.check_minimum("bot-a", Decimal("0.9"), Decimal("10"), Decimal("10"))
    assert not allowed and "9" in reason and "10" in reason
    assert OrderBudgetGuard.is_no_budget_error("Account has insufficient balance")
    assert OrderBudgetGuard.is_no_budget_error("code=-2010")
    assert not OrderBudgetGuard.is_no_budget_error("price filter failed")
    assert not OrderBudgetGuard.is_no_budget_error("")
    assert OrderBudgetGuard.should_log("bot-a", reason, 100.0)
    assert not OrderBudgetGuard.should_log("bot-a", reason, 101.0)
    assert OrderBudgetGuard.should_log("bot-a", reason, 160.0)
