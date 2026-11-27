import asyncio
from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock, patch

from hummingbot.connector.exchange.paper_trade.paper_trade_exchange import PaperTradeExchange
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.trade_fee import AddedToCostTradeFee
from hummingbot.core.event.events import MarketOrderFailureEvent, OrderFilledEvent
from hummingbot.strategy.strategy_v2_base import StrategyV2Base
from hummingbot.strategy_v2.controllers.order_budget import OrderBudgetGuard
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig, TripleBarrierConfig
from hummingbot.strategy_v2.executors.position_executor.loss_exit import LossExitState
from hummingbot.strategy_v2.executors.position_executor.position_executor import PositionExecutor
from hummingbot.strategy_v2.models.base import RunnableStatus


def make_executor(**overrides):
    strategy = MagicMock(spec=StrategyV2Base)
    strategy.connectors = {"binance_paper_trade": MagicMock(spec=PaperTradeExchange)}
    strategy.connectors["binance_paper_trade"].quantize_order_amount.side_effect = lambda _, amount: amount
    strategy.buy.return_value = "open-order"
    strategy.sell.return_value = "tp-order"
    type(strategy).current_timestamp = PropertyMock(return_value=100.0)
    values = {
        "id": "executor-1",
        "controller_id": "bot-a",
        "timestamp": 100.0,
        "trading_pair": "ETH-USDT",
        "connector_name": "binance_paper_trade",
        "side": TradeType.BUY,
        "entry_price": Decimal("100"),
        "amount": Decimal("1"),
        "triple_barrier_config": TripleBarrierConfig(
            take_profit=Decimal("0.001"),
            open_order_type=OrderType.LIMIT,
            take_profit_order_type=OrderType.LIMIT,
        ),
    }
    values.update(overrides)
    with patch.object(PositionExecutor, "get_trading_rules", side_effect=AttributeError("no trading_rules")):
        return PositionExecutor(strategy, PositionExecutorConfig(**values))


def budget_failure():
    return MarketOrderFailureEvent(
        timestamp=100.0, order_id="open-order", order_type=OrderType.LIMIT,
        error_message="NO BUDGET",
    )


def filled_event():
    return OrderFilledEvent(
        timestamp=100.0, order_id="open-order", trading_pair="ETH-USDT",
        trade_type=TradeType.BUY, order_type=OrderType.LIMIT,
        price=Decimal("100"), amount=Decimal("1"),
        trade_fee=AddedToCostTradeFee(), exchange_trade_id="fill-1",
    )


def test_open_and_tp_respect_minimum_without_stopping_executor():
    OrderBudgetGuard.reset()
    executor = make_executor(min_order_amount_quote="101")
    executor.place_open_order()
    assert executor._open_order is None
    assert executor.status != RunnableStatus.TERMINATED
    executor.place_take_profit_limit_order(amount=Decimal("1"), price=Decimal("100"))
    assert executor._take_profit_limit_order is None
    executor.config.min_order_amount_quote = Decimal("10")
    executor.place_open_order()
    assert executor._open_order is not None
    executor.place_take_profit_limit_order(amount=Decimal("1"), price=Decimal("100"))
    assert executor._take_profit_limit_order is not None


def test_loss_exit_minimum_does_not_hold_or_complete_position():
    OrderBudgetGuard.reset()
    executor = make_executor(min_order_amount_quote="101")
    executor._loss_exit = MagicMock()
    executor._status = RunnableStatus.RUNNING
    executor._loss_exit_order_reconciliation_required = False
    executor.early_stop = MagicMock()
    with patch.object(PositionExecutor, "amount_to_close", new_callable=PropertyMock, return_value=Decimal("1")):
        with patch.object(PositionExecutor, "_get_loss_exit_price", return_value=Decimal("100")):
            executor._place_loss_exit_order()
    assert executor.status == RunnableStatus.RUNNING
    executor.early_stop.assert_not_called()
    executor._loss_exit.mark_order_placed.assert_not_called()


def test_no_budget_pauses_tp_and_fill_recovers():
    OrderBudgetGuard.reset()
    executor = make_executor(no_budget_retry_seconds=300)
    executor.process_order_failed_event(None, executor.connectors["binance_paper_trade"], budget_failure())
    executor.place_take_profit_limit_order(amount=Decimal("1"), price=Decimal("100"))
    assert executor._take_profit_limit_order is None
    executor.process_order_filled_event(None, executor.connectors["binance_paper_trade"], filled_event())
    executor.place_take_profit_limit_order(amount=Decimal("1"), price=Decimal("100"))
    assert executor._take_profit_limit_order is not None


def test_loss_exit_order_is_allowed_during_budget_pause():
    OrderBudgetGuard.reset()
    executor = make_executor(no_budget_retry_seconds=300)
    executor._loss_exit = MagicMock()
    executor._loss_exit.state = LossExitState.ACTIVATING
    executor._loss_exit_activated = True
    executor.process_order_failed_event(None, executor.connectors["binance_paper_trade"], budget_failure())

    executor.place_take_profit_limit_order(amount=Decimal("1"), price=Decimal("100"))

    assert executor._take_profit_limit_order is not None


def test_preflight_insufficient_balance_pauses_controller():
    OrderBudgetGuard.reset()
    executor = make_executor(no_budget_retry_seconds=30)
    adjusted_candidate = MagicMock()
    adjusted_candidate.amount = Decimal("0")
    executor.adjust_order_candidates = MagicMock(return_value=[adjusted_candidate])
    executor.stop = MagicMock()

    asyncio.run(executor.validate_sufficient_balance())

    assert executor.close_type.name == "INSUFFICIENT_BALANCE"
    executor.stop.assert_called_once()
    assert OrderBudgetGuard.is_paused("bot-a", 101.0)
    assert OrderBudgetGuard.is_paused("bot-a", 129.9)
    assert not OrderBudgetGuard.is_paused("bot-a", 130.0)
