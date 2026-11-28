# 保留开放订单与重启恢复设计规格

## 1. 背景与结论

当前 `docker stop` 会触发 Hummingbot 优雅停止并撤销开放订单。强制停止可以避免撤单，但当前重启流程只读取历史绩效，不恢复活跃 Executor 和 TP 跟踪，可能留下未跟踪订单并生成重复 TP。

本设计增加完整的“保留开放订单＋重启对账”能力。核心目标不是单纯让订单留在交易所，而是确保重启后订单、持仓、Executor 和亏损退出状态一致，才允许恢复交易。

初始范围仅支持：

- `pmm_mister_loss_exit` Controller。
- Binance 现货和 `binance_paper_trade`。
- `PositionExecutor` 的原始开仓单、原始 LIMIT / LIMIT_MAKER TP、亏损退出 TP。
- 单个 Controller 内的订单恢复。

其他 Connector 必须在对账不确定时进入阻止状态，不得按 Binance 规则猜测恢复。

## 2. 安全不变量

以下规则优先级高于更新速度和可用性：

1. 对账完成前，不得创建新 Executor、普通开仓单或新 TP。
2. 任何订单、数量或状态无法确定时，不得激活或重挂亏损退出。
3. 同一原始订单 ID 最多恢复一次，不得创建第二个 TP 替代它。
4. 重启后只有交易所实际仍开放的订单才能标记为开放。
5. 停止期间全部成交的 TP 不得重新挂出；部分成交只能恢复剩余数量。
6. 恢复过程中不得自动撤销无法识别的交易所订单，先报警并等待人工处理。
7. 所有恢复决策可重复执行，重复重启不得重复恢复或重复挂单。
8. 默认部署行为保持不变：未显式启用保留订单模式时，停止仍撤销开放订单。
9. 日志不得输出 API 密钥、环境变量值或其他账户凭据。

## 3. 总体架构

新增四个协作组件：

### 3.1 ExecutorRecoveryStore

按 Controller 持久化活跃 Executor 和订单运行状态，不只保存亏损退出记录。

建议路径：

```text
data/pmm_mister_loss_exit/runtime/<controller_id>.json
```

使用“临时文件＋原子替换”写入，包含 schema 版本、Controller、Connector、交易对、更新时间和 Executor 列表。

状态变更时同步保存，而不是只依赖停止钩子，以覆盖异常退出：

- Executor 创建和终止。
- 开仓单、TP、退出 TP 创建。
- 订单部分成交、全部成交、撤销和失败。
- 亏损退出状态变化、退出锁变化和重挂次数变化。
- 恢复对账状态变化。

不为每个市场 tick 写盘。没有订单或状态变化时不写入。

### 3.2 ConnectorOrderRecoveryAdapter

隔离交易所差异，为恢复流程提供统一查询结果：

```text
fetch_order_snapshot(client_order_id) -> RecoveredOrderSnapshot
fetch_fills_since(client_order_id, checkpoint) -> list[RecoveredFill]
```

`RecoveredOrderSnapshot` 至少包含：

- 客户端订单 ID、交易所订单 ID。
- 方向、类型、价格、原始数量。
- 已成交数量、剩余数量。
- OPEN / PARTIALLY_FILLED / FILLED / CANCELED / FAILED / UNKNOWN。
- 交易所更新时间。

UNKNOWN 与 FILLED 必须严格区分。查不到订单不能直接当成已撤销或已成交。

初始实现 Binance 现货适配器和 Paper 模拟适配器。真实 Connector 的 API 返回必须经过适配器转换，Controller 不直接解析交易所原始 JSON。

### 3.3 ExecutorRuntimeRestorer

根据持久化记录和交易所快照重建：

- `PositionExecutorConfig`。
- `_open_order`、`_take_profit_limit_order`、`_close_order`。
- `_loss_exit_orders`、成交去重账本和终态订单集合。
- 已成交数量、剩余数量、手续费和平均成交价。
- 亏损退出状态、锁、激活时间、冷却和重挂状态。

恢复动作必须在 Executor 启动控制循环前完成。未通过校验的 Executor 不得调用 `start()`。

### 3.4 RecoveryCoordinator

在 Controller 产生任何交易动作之前执行启动状态机：

```text
DISABLED
  -> READY                         # 未启用保留订单模式

NO_RECORDS
  -> READY                         # 启用但无待恢复记录

PENDING
  -> RECONCILING
  -> READY                         # 全部订单和持仓一致
  -> BLOCKED                       # 任一不确定或冲突
```

`determine_executor_actions()` 在非 READY 状态下不得返回创建、激活或重挂动作。BLOCKED 状态只允许读取状态和输出诊断，不允许自动“修复”订单。

## 4. 持久化数据模型

每个 Executor 记录至少包含：

```json
{
  "schema_version": 1,
  "controller_id": "bot-a",
  "connector_name": "binance",
  "trading_pair": "ZEC-USDT",
  "updated_at": 1795762000.0,
  "executors": [
    {
      "executor_id": "executor-1",
      "executor_config": {},
      "open_order": {},
      "take_profit_order": {},
      "close_order": null,
      "loss_exit_orders": [],
      "terminal_order_ids": [],
      "fill_checkpoint": {},
      "loss_exit": {
        "state": "WATCHING",
        "lock_held": false,
        "condition_since": null,
        "eligible_since": null,
        "requote_count": 0,
        "last_requote_at": null,
        "reconciliation_required": false
      }
    }
  ]
}
```

每个订单记录至少包含：

- 客户端订单 ID、交易所订单 ID（如已返回）。
- 原始价格、原始数量、方向、订单类型和 PositionAction。
- 最新已确认的成交数量和成交明细检查点。
- 本地最后确认状态及时间。

配置序列化必须包含恢复所需字段，但不得包含 Connector 凭据。

## 5. 停止流程

### 5.1 显式启用方式

在引擎退出路径使用现有能力：

```python
await trading_core.shutdown(skip_order_cancellation=True)
```

建议通过容器环境变量启用：

```text
HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN=true
```

默认未设置或为 `false` 时保持现有撤单行为。

保留订单更新必须走 `condor_recreate.py` 或等价的容器重建流程，以便显式增加环境变量并保留配置、数据、网络和凭据。普通 `install_loss_exit.sh` 覆盖更新继续采用默认撤单行为，不通过伪造环境或强制 kill 绕过。

部署工具增加显式参数：

```bash
python3 scripts/condor_recreate.py \
  --container BOT_NAME \
  --keep-open-orders \
  --yes
```

实盘仍必须额外提供 `--live`。启用该模式前，部署工具必须确认目标版本包含恢复组件；旧版本不得使用。

### 5.2 停止顺序

1. 将最新 Executor 和订单状态原子写入 RecoveryStore。
2. 停止策略控制循环，阻止新交易动作。
3. 调用 `shutdown(skip_order_cancellation=True)`。
4. 保留交易所订单，更新容器代码和镜像。
5. 启动后先进入 RECONCILING，不立即恢复报价。

若状态保存失败，必须中止“保留订单停止”，不得假装已安全保存。部署工具应报告失败并保持旧实例状态，由操作者决定改为正常撤单停止还是取消更新。

## 6. 重启对账流程

### 6.1 基础校验

逐项检查：

- schema 版本可识别。
- controller_id、connector、交易对与当前配置一致。
- 当前 Connector＋交易对没有由其他 Controller 同时管理；无法确认归属或存在交叉管理时进入 BLOCKED。
- Executor 配置可解析且方向、TP 类型有效。
- 订单 ID 非空且不重复。
- 数量和成交账本满足：`0 <= filled <= original`。
- 亏损退出锁最多由一个 Executor 持有。

任何基础校验失败进入 BLOCKED。

### 6.2 按订单状态恢复

| 持久化状态与交易所结果 | 恢复动作 |
|---|---|
| 开放，交易所仍开放且数量一致 | 重建原订单 ID 的 TrackedOrder，继续跟踪 |
| 开放，交易所部分成交 | 更新成交账本，只恢复剩余数量 |
| 开放，交易所已全部成交 | 重放缺失成交结果，关闭对应流程，不再挂单 |
| 开放，交易所已撤销 | 标记终态，按原策略处理，不自动重挂 |
| 开放，交易所明确失败 | 标记失败并进入相应恢复状态，不自动假定预算错误 |
| 查询 UNKNOWN、超时或返回矛盾 | BLOCKED |
| 本地有记录但交易所无此订单 | BLOCKED，除非能通过订单历史明确证明终态 |
| 交易所有订单但本地无记录 | 不接管、不撤单；报告未跟踪订单并 BLOCKED |

恢复成交时必须按交易所成交 ID 去重，不能仅按时间或数量推断。

### 6.3 恢复后持仓校验

汇总原始开仓成交、TP 成交、亏损退出成交和数据库持仓记录，核对：

- Executor 的 `open_filled_amount`。
- `close_filled_amount` 和 `amount_to_close`。
- 当前交易所可用余额与持仓方向。
- 是否存在同一价格、同一方向、同一原始订单的重复 TP。

余额因其他策略或人工操作而变化时，不强行把差额归属当前 Controller；无法确认归属则 BLOCKED。

### 6.4 恢复正常规则

只有全部恢复完成后才进入 READY：

- 恢复的开放 TP 纳入 `tp_order_distance_tolerance_pct` 的同向和入口距离检查。
- TP 有效期在停止期间已到期时，恢复后按现有高优先级规则撤销，不恢复成永久有效订单。
- 原 TP 仍有效且满足亏损退出条件时，重新计算连续满足时间；不能把停止期间无法观察的时间伪造成连续满足。
- 已激活亏损退出的订单恢复其锁，其他候选继续等待。
- 预算暂停不跨越进程重启自动延续；重启后先由余额和对账结果重新判断。
- READY 后才允许普通开单和新的亏损退出动作。

## 7. 异常与人工恢复

BLOCKED 日志必须给出可操作的诊断：

- Controller、Executor、订单 ID。
- 本地状态与交易所状态差异。
- 缺失或重复的成交明细。
- 需要人工核实的具体项目。

不输出完整账户余额快照或凭据。

提供只读诊断命令：

```bash
python3 scripts/condor_recovery_check.py --container BOT_NAME
```

它只读取 RecoveryStore 和交易所订单，输出 READY / BLOCKED 及差异，不写状态、不撤单、不挂单。

人工对账完成后，通过显式命令清除或修正恢复记录。不得通过简单删除所有记录来绕过 BLOCKED；删除前必须确认交易所没有遗留订单。

## 8. 部署与回滚

### 8.1 默认更新

不改变当前安装器的默认行为：

- 停止并撤销开放订单。
- 更新并重启。
- 不启用订单恢复。

### 8.2 保留订单更新

必须同时满足：

- 新版本镜像包含 RecoveryStore、Restorer、Coordinator 和 Connector 适配器。
- 目标为受支持的 Controller 和 Connector。
- dry-run 已完成。
- Paper 验收通过。
- 实盘显式提供 `--keep-open-orders --yes --live`。

### 8.3 回滚

代码回滚不得破坏 RecoveryStore。旧版本如果不认识新 schema，不得继续以保留订单模式启动。

回滚只能回到“包含兼容恢复能力的上一版本”，不能回到完全没有恢复组件的旧镜像。否则必须先正常撤单，再回滚。

## 9. 测试要求

### 9.1 单元测试

- RecoveryStore 原子写入、schema 校验和重复记录拒绝。
- 订单方向、价格、数量、成交去重和剩余数量计算。
- 同向 TP 距离过滤把恢复订单纳入结果。
- 预算暂停、最低金额过滤和亏损退出豁免不回归。
- 停止环境变量默认 false，仅在显式 true 时跳过撤单。

### 9.2 Paper 集成测试

每个场景都记录更新前订单 ID，重启后检查没有重复 ID：

1. 原始 TP 未变化：重启后仍是同一订单并被同一 Executor 跟踪。
2. 停止期间 TP 部分成交：只恢复剩余数量。
3. 停止期间 TP 全部成交：不重新挂 TP，Executor 正常结束。
4. 停止期间 TP 被外部撤销：进入终态，不自动重挂。
5. 查询超时或 UNKNOWN：进入 BLOCKED，不挂任何新单。
6. 本地有记录、交易所无记录：进入 BLOCKED。
7. 交易所有记录、本地缺失：进入 BLOCKED，不自动撤单。
8. 多个同向 TP 和双向 TP：全部按原订单恢复，距离过滤有效。
9. 活跃亏损退出：只恢复一个锁和一个退出 TP，不激活第二个候选。
10. TP 在停止期间到期：恢复后按有效期规则处理。
11. 连续两次重启：恢复幂等，无重复成交和重复订单。
12. 状态写入失败：部署拒绝进入保留订单停止。

### 9.3 实盘前只读验收

在真实账户上先运行只读 `condor_recovery_check.py` 的适配器测试，确认 Binance 订单查询、成交历史和客户端订单 ID 映射正确。不得用真实订单做首次功能测试。

## 10. 验收标准

只有同时满足以下条件才可考虑实盘启用：

- 所有单元测试和 Paper 场景通过。
- 停止容器时交易所开放 TP 未被撤销。
- 重启后所有 TP 都由原 Executor 和原订单 ID 跟踪。
- 停止期间成交得到准确补偿，无重复 TP。
- 任一不确定状态都能可靠进入 BLOCKED，且没有新订单产生。
- dry-run 能明确展示将保留的订单、目标版本和恢复结果。
- 保留兼容恢复能力的回滚路径已经验证。

## 11. 非目标

- 不保证多个 Controller 或容器共享订单时自动去重。
- 不承诺首版支持所有交易所。
- 不在对账不确定时自动撤销或重建订单。
- 不保证服务器断电、交易所历史缺失或人工改单后仍能无人工介入恢复。
- 不把强制 `SIGKILL` 作为正式部署方案。
