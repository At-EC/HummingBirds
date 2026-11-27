# Keep Open Orders Restart Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让受支持的 PMM Mister Loss Exit 实例在显式保留 TP 停止后，能够完成交易所对账并恢复原订单跟踪，任何不确定状态都阻止新交易。

**Architecture:** 用原子 RecoveryStore 持久化 Executor 和订单状态，用 Connector 适配器读取真实订单终态，在 Executor 启动前重建运行状态。Controller 只有在 RecoveryCoordinator 进入 READY 后才能创建或激活订单；停止和部署默认仍撤销订单。

**Tech Stack:** Python 3.13、Hummingbot 2.17.0、Pydantic、pytest、Docker、现有 `condor_recreate.py` 和覆盖发布流程。

## Global Constraints

- 首版仅支持 `pmm_mister_loss_exit`、Binance 现货、`binance_paper_trade` 和 `PositionExecutor`。
- 对账完成前不得创建普通订单、TP 或激活亏损退出；不确定时进入 BLOCKED。
- 未显式启用时，`shutdown(skip_order_cancellation=False)` 的现有行为不得改变。
- 不得使用 `SIGKILL` 作为正式部署方案。
- 不得输出 API 凭据、环境变量值或完整账户敏感快照。
- 每个任务先写失败测试并观察预期失败，再写最小实现；完整预算回归必须保持通过。
- 任何实盘更新都需要用户再次明确批准，本计划只授权开发、仓库更新和 Paper 验证。

## File Structure

- `hummingbot/strategy_v2/controllers/executor_recovery.py`：schema、RecoveryStore 和恢复数据类型。
- `hummingbot/connector/exchange/binance/binance_order_recovery.py`：Binance 订单快照适配器。
- `hummingbot/strategy_v2/executors/position_executor/recovery.py`：PositionExecutor 状态重建。
- `hummingbot/strategy_v2/executors/position_executor/position_executor.py`：恢复入口及持久化事件钩子。
- `controllers/generic/pmm_mister_loss_exit.py`：启动恢复协调与 READY/BLOCKED 门控。
- `hummingbot/cli/engine.py`：显式跳过撤单环境变量。
- `scripts/condor_recreate.py`：`--keep-open-orders` 安全部署参数。
- `scripts/condor_recovery_check.py`：只读恢复诊断。
- `tests/`：各组件单元测试和 Paper 集成测试。

---

### Task 1: RecoveryStore 与恢复数据类型

**Files:**
- Create: `hummingbot/strategy_v2/controllers/executor_recovery.py`
- Test: `tests/executor_recovery_store_regression.py`

**Interfaces:**
- `RecoveredOrderSnapshot`：订单 ID、方向、价格、原始数量、成交数量、剩余数量、状态、更新时间。
- `ExecutorRecoveryStore(controller_id: str, root: Path)`。
- `load() -> dict | None`、`save(payload: dict) -> None`、`path -> Path`。
- `validate_recovery_payload(payload: dict) -> None`。

- [ ] **Step 1: 写原子保存、无效数据和重复订单测试**

```python
def test_store_round_trip_and_atomic_write(tmp_path):
    store = ExecutorRecoveryStore("bot-a", tmp_path)
    store.save(valid_payload())
    assert store.load() == valid_payload()
    assert store.path.name == "bot-a.json"
    assert not list(tmp_path.glob("*.tmp"))


def test_duplicate_order_id_is_rejected(tmp_path):
    payload = valid_payload()
    payload["executors"].append(payload["executors"][0])
    with pytest.raises(ValueError, match="duplicate order"):
        ExecutorRecoveryStore("bot-a", tmp_path).save(payload)


def test_wrong_controller_or_schema_is_rejected(tmp_path):
    payload = valid_payload()
    payload["schema_version"] = 999
    with pytest.raises(ValueError, match="schema"):
        ExecutorRecoveryStore("bot-a", tmp_path).save(payload)
```

`valid_payload()` 使用一个 BUY Executor、一个 SELL TP 和 `schema_version=1`，所有数量使用字符串。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/executor_recovery_store_regression.py -q`
Expected: FAIL，提示模块或 `ExecutorRecoveryStore` 不存在。

- [ ] **Step 3: 实现严格 schema 和原子写入**

`save()` 先验证，再按 `controller_id/schema_version/updated_at/executors` 构造固定顶层结构；写 `<controller_id>.tmp` 后 `replace()` 到 `<controller_id>.json`。`load()` 对不存在返回 `None`，存在时 JSON 解析并再次验证。

数量校验统一使用：

```python
filled = Decimal(order["filled_amount"])
original = Decimal(order["original_amount"])
if original < 0 or filled < 0 or filled > original:
    raise ValueError("invalid order amounts")
```

- [ ] **Step 4: 运行测试并提交**

Run: `python -m pytest tests/executor_recovery_store_regression.py -q`
Expected: 全部 PASS。
Commit: `feat: add executor recovery store`

---

### Task 2: Connector 订单快照适配器

**Files:**
- Create: `hummingbot/connector/exchange/binance/binance_order_recovery.py`
- Test: `tests/binance_order_recovery_regression.py`

**Interfaces:**
- `BinanceOrderRecoveryAdapter(connector)`。
- `fetch_order_snapshot(client_order_id: str) -> RecoveredOrderSnapshot`。
- `fetch_fills_since(client_order_id: str, checkpoint: dict) -> list[dict]`。
- 查询异常映射为 `status=UNKNOWN`，绝不映射为 CANCELED 或 FILLED。

- [ ] **Step 1: 写 Binance 原始响应转换测试**

```python
def test_open_order_snapshot_preserves_remaining_amount():
    adapter = BinanceOrderRecoveryAdapter(MagicMock())
    snapshot = adapter._convert_order(binance_open_order())
    assert snapshot.status == "OPEN"
    assert snapshot.original_amount == Decimal("2")
    assert snapshot.filled_amount == Decimal("0.5")
    assert snapshot.remaining_amount == Decimal("1.5")


def test_not_found_is_unknown_not_canceled():
    adapter = BinanceOrderRecoveryAdapter(MagicMock())
    snapshot = adapter._convert_api_error("UNKNOWN_ORDER", "Order does not exist")
    assert snapshot.status == "UNKNOWN"
    assert snapshot.status != "CANCELED"
```

测试覆盖 NEW、PARTIALLY_FILLED、FILLED、CANCELED、REJECTED、EXPIRED、网络超时和查询不到。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/binance_order_recovery_regression.py -q`
Expected: FAIL，提示适配器不存在。

- [ ] **Step 3: 实现转换与只读查询**

状态映射集中为固定字典；未识别状态进入 UNKNOWN。成交明细以交易所 trade ID 去重，返回按时间排序的新增记录。适配器只调用查询接口，不调用创建、撤销或批量撤单接口。

- [ ] **Step 4: 运行单元测试与 Binance 只读连通性检查**

Run: `python -m pytest tests/binance_order_recovery_regression.py -q`
Expected: 全部 PASS。
另用实盘现有开放 TP 的客户端订单 ID 做只读查询，核对订单 ID、价格、数量和状态；不得创建测试订单。

Commit: `feat: add Binance order recovery adapter`

---

### Task 3: PositionExecutor 状态重建与事件持久化

**Files:**
- Create: `hummingbot/strategy_v2/executors/position_executor/recovery.py`
- Modify: `hummingbot/strategy_v2/executors/position_executor/position_executor.py`
- Test: `tests/position_executor_recovery_regression.py`

**Interfaces:**
- `PositionExecutor.snapshot_recovery_state() -> dict`。
- `PositionExecutor.restore_recovery_state(record: dict, snapshots: dict[str, RecoveredOrderSnapshot]) -> None`。
- `ExecutorRuntimeRestorer.restore(executor, record, snapshots) -> None`，在 `executor.start()` 前调用。

- [ ] **Step 1: 写原订单、部分成交和全部成交恢复测试**

```python
def test_open_tp_is_restored_with_same_id_and_remaining_amount():
    executor = make_executor()
    record = recovery_record_with_tp(filled="0.5", original="2")
    snapshot = recovered_tp(filled="0.5", original="2", status="PARTIALLY_FILLED")
    ExecutorRuntimeRestorer.restore(executor, record, {"tp-1": snapshot})
    assert executor._take_profit_limit_order.order_id == "tp-1"
    assert executor.amount_to_close == Decimal("1.5")


def test_filled_tp_is_not_recreated():
    executor = make_executor()
    record = recovery_record_with_tp(filled="0.5", original="2")
    snapshot = recovered_tp(filled="2", original="2", status="FILLED")
    ExecutorRuntimeRestorer.restore(executor, record, {"tp-1": snapshot})
    assert executor._take_profit_limit_order is None
    assert executor.close_type == CloseType.TAKE_PROFIT
```

另测 UNKNOWN 抛 `RecoveryBlocked`、缺失快照抛 `RecoveryBlocked`、成交 ID 去重、活跃亏损退出只恢复一个锁。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/position_executor_recovery_regression.py -q`
Expected: FAIL，提示恢复接口不存在。

- [ ] **Step 3: 实现快照、重建和事件钩子**

恢复原订单时使用已有 `InFlightOrder` 和 `TrackedOrder`，不经过 `place_order()`。FILLED / CANCELED 不重建为开放订单。UNKNOWN 或数量矛盾抛 `RecoveryBlocked`。

在订单创建、成交、撤销、失败和亏损退出状态变化后调用同一个 `snapshot_recovery_state()`；Controller 负责写入 RecoveryStore，Executor 不直接操作文件。

- [ ] **Step 4: 运行恢复及原有预算回归**

Run: `python -m pytest tests/position_executor_recovery_regression.py tests/order_budget_regression.py tests/order_budget_controller_regression.py tests/order_budget_executor_regression.py -q`
Expected: 全部 PASS。

Commit: `feat: restore position executor order state`

---

### Task 4: RecoveryCoordinator 与 Controller 交易门控

**Files:**
- Create: `hummingbot/strategy_v2/controllers/recovery_coordinator.py`
- Modify: `controllers/generic/pmm_mister_loss_exit.py`
- Test: `tests/recovery_coordinator_regression.py`

**Interfaces:**
- `RecoveryCoordinator(store, adapter_factory, restorer)`。
- `state`: `PENDING | RECONCILING | READY | BLOCKED`。
- `reconcile(executors: list[PositionExecutor]) -> None`。
- `diagnostics() -> dict`。

- [ ] **Step 1: 写门控与幂等测试**

```python
def test_blocked_recovery_disables_new_orders_and_loss_exit():
    controller = make_controller_with_recovery(status="UNKNOWN")
    assert controller.get_executor_config("buy_0", Decimal("100"), Decimal("1")) is None
    assert controller.get_loss_exit_activation_action() is None
    assert controller.recovery_state == "BLOCKED"


def test_recovered_tp_participates_in_direction_distance_filter():
    controller = make_controller_with_recovered_sell_tp("100.95")
    assert controller.get_executor_config("buy_0", Decimal("100"), Decimal("1")) is None
```

覆盖无记录 READY、全部成功 READY、任一 UNKNOWN BLOCKED、重复执行不重复恢复、其他 Controller 交叉管理 BLOCKED。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/recovery_coordinator_regression.py -q`
Expected: FAIL，提示协调器不存在。

- [ ] **Step 3: 接入启动流程和动作门控**

Coordinator 在 Controller 第一次 `determine_executor_actions()` 前完成基础校验；需要交易所查询时保持 RECONCILING 并返回空动作。全部恢复成功后把 Executor 加入 Orchestrator 活跃集合，再进入 READY。BLOCKED 只输出诊断，不产生交易动作。

- [ ] **Step 4: 运行协调器及 Controller 回归**

Run: `python -m pytest tests/recovery_coordinator_regression.py tests/order_budget_controller_regression.py -q`
Expected: 全部 PASS。

Commit: `feat: gate trading until recovery completes`

---

### Task 5: 显式保留订单停止与部署参数

**Files:**
- Modify: `hummingbot/cli/engine.py`
- Modify: `scripts/condor_recreate.py`
- Modify: `tests/test_condor_recreate.py`
- Modify: `package_release.sh`、`install_loss_exit.sh` 及对应发布测试

**Interfaces:**
- 环境变量 `HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN=true`。
- CLI `--keep-open-orders`，实盘仍同时要求 `--yes --live`。

- [ ] **Step 1: 写默认撤单和显式保留测试**

```python
def test_shutdown_defaults_to_canceling_orders():
    assert shutdown_skip_flag({}) is False


def test_shutdown_skip_requires_explicit_true():
    assert shutdown_skip_flag({"HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN": "true"}) is True
    assert shutdown_skip_flag({"HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN": "1"}) is False


def test_live_keep_open_orders_requires_yes_and_live():
    with pytest.raises(ValueError, match="--live"):
        validate_recreate_args(container="live-bot", keep_open_orders=True, yes=True, live=False)
```

部署测试还须验证：旧镜像缺少恢复 sentinel 时拒绝保留订单更新；普通更新不追加该环境变量。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_condor_recreate.py tests/test_shutdown_recovery.py -q`
Expected: FAIL，提示标志或参数不存在。

- [ ] **Step 3: 实现停止参数与版本保护**

引擎退出调用：

```python
skip = os.getenv("HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN", "").lower() == "true"
await hb.trading_core.shutdown(skip_order_cancellation=skip)
```

`condor_recreate.py` 仅在显式 `--keep-open-orders` 时追加环境变量，并检查镜像内 `executor_recovery.py` 和适配器存在。发布清单加入新增运行时文件，更新 `Runtime files` 数量和回滚清单。

- [ ] **Step 4: 运行部署、停止与发布回归**

Run: `python -m pytest tests/test_condor_recreate.py tests/test_shutdown_recovery.py -q && bash scripts/test_release_scripts.sh`
Expected: 全部 PASS；默认停止仍撤单。

Commit: `feat: add explicit keep-open-orders deployment`

---

### Task 6: 只读恢复诊断工具

**Files:**
- Create: `scripts/condor_recovery_check.py`
- Test: `tests/test_condor_recovery_check.py`

**Interfaces:**
- `python3 scripts/condor_recovery_check.py --container BOT_NAME`。
- 输出 READY / BLOCKED、订单差异和所需人工动作；不写文件、不撤单、不挂单。

- [ ] **Step 1: 写只读与诊断测试**

模拟 RecoveryStore 和适配器，断言 UNKNOWN 时退出码为 `2`，READY 为 `0`；调用记录中不得出现创建、撤销或状态清除方法，输出不得包含环境变量值。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_condor_recovery_check.py -q`
Expected: FAIL，提示脚本不存在。

- [ ] **Step 3: 实现诊断输出**

每个差异包含 Controller、Executor、订单 ID、本地状态、交易所状态和下一步建议。异常输出不包含完整交易所响应。

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest tests/test_condor_recovery_check.py -q`
Expected: 全部 PASS。
Commit: `feat: add read-only recovery diagnostics`

---

### Task 7: Paper 集成验收与文档

**Files:**
- Create: `tests/paper_keep_open_orders_regression.py`
- Modify: `README.md`
- Verify: 全部运行时文件和 Paper 容器

**Interfaces:**
- 可重复执行的 Paper 保留订单重启测试。
- 默认更新与保留订单更新的用户操作文档。

- [ ] **Step 1: 先实现可重复的 Paper 场景驱动**

场景驱动记录更新前订单 ID，控制模拟交易所订单状态，重启后读取恢复结果。覆盖规格中的 12 个场景；每个场景先断言当前代码缺少恢复能力而失败，再接入实现。

- [ ] **Step 2: 运行完整回归**

Run: `python -m pytest tests -q && bash scripts/test_release_scripts.sh`
Expected: 全部 PASS；预算、TP 距离、部署和登录工具测试无回归。

- [ ] **Step 3: 在 Paper 容器执行实际更新**

先 dry-run，再仅更新 `pmm-loss-exit-paper-v5`。验证原 TP 保留、同 ID 恢复、停止期间成交补偿、UNKNOWN 时 BLOCKED、无重复 TP；保存备份和测试输出。

- [ ] **Step 4: 更新文档并做最终只读实盘适配器检查**

README 说明默认撤单、保留订单参数、BLOCKED 处理和兼容回滚。对实盘只读取订单快照，不更新、不重启、不创建订单。

Commit: `test: verify keep-open-orders recovery`

## Execution Handoff

优先在当前会话按任务顺序实施，每个任务完成测试后再进入下一项。任何任务出现交易所行为不明确、测试反复失败或需要改变安全不变量时，停止并重新评审设计，不通过猜测继续实现。
