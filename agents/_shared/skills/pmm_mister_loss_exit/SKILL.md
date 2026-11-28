---
name: pmm_mister_loss_exit
description: 基于 PMM Mister 的现货做市与串行亏损退出策略，支持延迟激活、最大浮亏选择、冷却跟随、开放 TP 距离过滤和 effectivization 优先级控制。
when_to_use: 当用户需要在 Condor 中部署、配置、验证或调整 pmm_mister_loss_exit 现货 Bot，尤其是库存被套利 TP 锁住、需要按浮亏释放库存，或需要避免新挂单靠近现有 TP 时使用。
created: '2026-11-26T00:00:00Z'
source: chat
---

# PMM Mister Loss Exit

用于现货 PMM Mister 策略部署和运维。该策略会主动实现亏损以释放库存，不保证盈利或减少总亏损。

## 部署前检查

1. 确认目标为**现货**，不得用于永续合约。
2. 确认镜像包含修改后的 PositionExecutor、Orchestrator 和恢复模块，版本为 2.17.0 或 2.18.0。
3. 上传并保留以下 Controller 文件：
   - `controllers/generic/pmm_mister.py`
   - `controllers/generic/pmm_mister_loss_exit.py`
4. TP 类型必须为 `LIMIT` 或 `LIMIT_MAKER`。
5. 首次部署使用 `binance_paper_trade` 和唯一配置 ID，不直接使用真实资金。
6. 不要依赖串行锁保护多个 Controller 或多个容器；锁仅在单个 Controller 内有效。

## 部署流程

1. 通过 `manage_controllers` 检查并上传 Controller 和配置。
2. 参考同目录 `pmm_mister_loss_exit.sample.yml`，设置唯一 `id`、交易所、交易对和资金上限。
3. 通过 `manage_bots` 部署 paper trade Bot，选择包含策略修改的自定义镜像。
4. 首次将 `loss_exit_trigger_pct` 留空，确认普通 TP 和 POSITION_HOLD 行为不变。
5. 启用四个亏损退出参数，并设置 `tp_order_distance_tolerance_pct`。
6. 完成多候选、部分成交、冷却、到期中断和重启恢复测试后，才考虑小资金实盘。

## 核心参数

| 参数 | 示例 | 含义 |
|---|---|---|
| `loss_exit_trigger_pct` | `0.005` | 原始成交价浮亏达到 0.5% 后进入激活等待；留空禁用 |
| `loss_exit_offset_pct` | `0.001` | 撤退限价单距离当前盘口 0.1% |
| `loss_exit_cooldown_seconds` | `60` | 同一撤退订单两次实际重挂的最小间隔 |
| `loss_exit_activation_delay_seconds` | `60` | 浮亏必须连续满足 60 秒才可成为候选 |
| `tp_order_distance_tolerance_pct` | `0.001` | 新挂单成交后的预期 TP 与已有同向开放 TP 距离小于 0.1% 时跳过该档位；0 禁用 |
| `min_order_amount_quote` | `10` | 最低下单名义金额（quote），低于时跳过；0 禁用，普通开单和 TP 均检查 |
| `no_budget_retry_seconds` | `300` | 明确预算错误后的暂停秒数；成交立即恢复，亏损退出激活与退出 TP 豁免 |
| `no_budget_tp_cancel_distance_pct` | `0` | 预算不足时只撤销超过该距离的最远 TP，转入 POSITION_HOLD 且不重挂；0 禁用 |
| `buy_position_effectivization_time` | `120` | BUY TP 有效秒数，到期优先撤单并进入 POSITION_HOLD |
| `sell_position_effectivization_time` | `120` | SELL TP 有效秒数，到期优先撤单并进入 POSITION_HOLD |

## 不可违反的优先级

1. **Effectivization 到期优先于所有撤退动作**：只有原 TP 仍开放时才能激活撤退；到期后候选和 ACTIVE 撤退均停止，不得重挂。
2. 手动停止、全局 TP/SL 和强制风控优先于撤退。
3. 同一时间最多一笔撤退订单，选择当前浮亏百分比最大者，不被其他候选抢占。
4. 当前订单全部成交或终止后，重新检查其他订单的资格，不沿用旧排名。
5. 新挂单与开放 TP 距离过近时只跳过冲突档位，其他 BUY/SELL 档位继续；已撤销或完成 TP 不参与过滤。

## 验收重点

- 激活等待期间价格恢复会重置计时。
- 多个候选只激活最大浮亏，完成后再重新筛选。
- 部分成交只处理剩余数量，不得超额卖出或买回。
- 冷却前不撤单，量化价格不变时不重复撤单。
- ACTIVE 撤退在 effectivization 到期时停止，不创建 replacement。
- 只有一个档位靠近开放 TP 时，其余三个档位仍正常挂单。
- 重启后存在未完成恢复记录时，不得自动补单或开新仓，必须先人工对账。

## 监控与排错

检查 Controller 自定义状态、Executor 状态、活跃退出订单、剩余数量、重挂次数、开放 TP 价格和恢复记录。

- 未激活：检查浮亏、连续等待时间、TP 是否开放及是否已到 effectivization 截止时间。
- 没有撤退：检查是否已有另一笔 ACTIVE/ACTIVATING 订单。
- 某档位未挂出：检查开放 TP 距离容忍度，不要误判为 spread 配置错误。
- 重启后停止交易：先核对交易所订单、余额和恢复文件，不要直接删除记录。
- 参数修改：Controller 报价层参数影响后续决策；Executor 创建时参数快照只影响之后新建的 Executor，已有 Executor 需要重启统一调整。
