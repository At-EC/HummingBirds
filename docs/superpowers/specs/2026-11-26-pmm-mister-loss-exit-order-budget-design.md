# PMM Mister Loss Exit：最小下单金额与预算不足恢复设计

日期：2026-11-26  
状态：已确认方案 A

## 目标

为 `pmm_mister_loss_exit` 增加统一的下单名义金额限制和预算不足暂停机制，覆盖普通开单、原始 TP 与亏损退出 TP，避免低于用户阈值的订单进入交易所，并避免预算错误后持续立即重试。

## 范围与原则

- 仅影响当前 Controller 进程内、同一 `controller_id` 的订单创建。
- 不撤销已有订单，不改变 TP 距离过滤、最大浮亏串行退出、effectivization 优先级等既有语义。
- 撤单、刷新、effectivization、全局风控平仓不因预算暂停而被禁止。
- 预算暂停状态只保存在内存中，重启 Controller 后清除，不新增持久化状态。
- `min_order_amount_quote = 0` 时关闭最小金额检查，保持现有行为。

## 配置参数

### `min_order_amount_quote`

- 类型：`Decimal`，必须大于或等于 `0`。
- 默认：`0`。
- 含义：允许创建的订单所需的最小名义金额，以交易对的 quote 资产计价。
- 计算：`notional = abs(amount * price)`。
- `notional < min_order_amount_quote` 时跳过该笔订单；等于阈值时允许下单。
- 普通 buy/sell、原始 TP 和亏损退出 TP 均检查。
- 低于阈值时不终止 Executor，不撤销已有订单，不进入 POSITION_HOLD；后续 tick 中金额满足条件后自动重试。

### `no_budget_retry_seconds`

- 类型：`int`，必须大于或等于 `1`。
- 默认：`300`。
- 含义：预算不足错误后的最长暂停时间。成交可提前解除暂停。

## 共享预算状态

新增进程内预算状态组件，以 `controller_id` 隔离：

- `paused_at`：最近一次确认预算不足的时间。
- `resume_at`：允许因超时恢复的时间。
- `last_error`：最近一次预算错误摘要。
- `last_skip_reason`：最近一次最小金额跳过原因。

不同 Controller 不共享暂停状态。普通 Controller 与 Executor 都通过同一个组件查询和更新状态。

## 普通开单流程

Controller 在生成 `CreateExecutorAction` 前：

1. 若预算暂停有效，不创建新 Executor。
2. 若 `amount * price` 小于阈值，跳过当前 level，其他 level 仍可创建。
3. 被跳过的 level 保留在后续 tick 的候选中，不写入永久禁用状态。

Executor 创建 open order 前再次执行相同检查，避免 Controller 与 Executor 状态不同步造成漏检。

## TP 与亏损退出流程

PositionExecutor 在创建原始 TP 或亏损退出 TP 前：

1. 原始 TP 在预算暂停有效时不下单；亏损退出 TP 不受预算暂停限制，确保撤单后可以重挂。
2. 若名义金额低于阈值，不下单，记录跳过原因，并在后续 tick 重试。
3. 原始 TP 未创建或等待重试时，不伪造成交，不提前终止 Executor。
4. 亏损退出因最小金额无法下单时，不进入 POSITION_HOLD，不标记完成；保留串行锁，避免其他亏损退出订单同时创建。

## 预算错误识别与暂停

处理 `MarketOrderFailureEvent` 时读取 `error_message`，进行大小写归一化匹配：

- `no budget`
- `not enough budget`
- `insufficient balance`
- `insufficient funds`
- `balance is insufficient`
- 交易所错误码 `-2010`

只有明确匹配时才暂停，避免将网络、精度、价格或未知错误误判为预算不足。错误消息为空时不触发预算暂停。

确认预算不足后：

1. 记录 `paused_at`、`resume_at = paused_at + no_budget_retry_seconds` 和错误摘要。
2. 暂停当前 Controller 的普通新开单和原始 TP；亏损退出激活与退出 TP 必须豁免，以便撤销原 TP 并重新挂单释放库存与预算。
3. 已有订单及撤单、effectivization、全局风控流程继续运行。

## 恢复条件

满足任一条件即恢复：

1. 同一 `controller_id` 的任意订单产生 `OrderFilledEvent`，立即清除暂停。
2. 当前时间达到 `resume_at`，自动清除暂停。

恢复后的第一笔订单仍必须通过最小金额检查。若再次发生明确的预算错误，重新计算暂停时间。

## 可观测性

Controller 或 Executor 的自定义状态中增加：

- `no_budget_paused`
- `no_budget_resume_at`
- `no_budget_last_error`
- `min_order_amount_quote`
- `min_order_last_skip_reason`

日志按时间和原因限流，避免每个 tick 重复输出相同跳过原因。

## 测试

### 配置

- 默认参数保持原行为。
- 负数最小金额和非法重试时间被拒绝。
- YAML 字符串数值可正确解析。

### 最小金额

- 小于阈值时普通 buy/sell 被跳过，其他合格 level 不受影响。
- 等于阈值时允许下单。
- 原始 TP 与亏损退出 TP 低于阈值时不创建订单，后续满足条件可恢复。
- 已有订单不因跳过而被撤销。

### 预算错误与恢复

- 明确预算错误触发同一 Controller 的共享暂停。
- 非预算错误和空错误消息不触发暂停。
- 普通新开单和原始 TP 在暂停期间被阻止，亏损退出激活与退出 TP 仍可执行。
- 任意订单成交后立即恢复。
- 无成交时到期自动恢复。
- 不同 `controller_id` 互不影响。

### 回归与部署

- 运行现有 PositionExecutor、Orchestrator 和 Controller 测试。
- 运行 Paper Trade 兼容性回归。
- 验证发布包包含全部文件，独立安装与失败回滚通过。
- 更新 Condor 示例配置，但不启动真实资金交易。

## 非目标

- 不根据账户余额动态提高订单金额。
- 不自动撤销已有订单来释放预算。
- 不实现跨进程、跨容器或跨 Controller 的预算锁。
- 不将所有异常都视为预算不足。
