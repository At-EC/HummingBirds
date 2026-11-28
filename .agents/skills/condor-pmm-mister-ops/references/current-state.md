# 当前项目状态

最近验证：2026-11-28（服务器 UTC）。以下是带时间戳的快照；执行新任务时必须重新验证运行状态、订单和部署文件。

## 仓库

- 远程仓库：`https://github.com/At-EC/HummingBirds.git`
- 当前功能分支：`feat/keep-open-orders-recovery`
- 最近验证的策略修复提交：`8d73efb fix: deduplicate completed TP recovery snapshots`
- Draft PR：`https://github.com/At-EC/HummingBirds/pull/1`
- 本地开发目录：`recovery-worktree`
- 服务器开发目录：`/root/recovery-live`

## 实盘环境快照

- SSH 主机：`root@103.193.150.25`；使用本地既有密钥和 `known_hosts`，秘密不进入仓库。
- Bot 容器：`bot_20261126161333-20261126-161343`
- 运行镜像：`hummingbot/pmm-mister-loss-exit:v2.17.0-recovery-tp-dedup`
- Controller：`pmm_mister_loss_exit`
- Controller 配置 ID：`pmm_mister_loss_exit_sample`
- Connector / 交易对：Binance 现货，`ZEC-USDT`
- 恢复记录：容器内 `data/pmm_mister_loss_exit/runtime/pmm_mister_loss_exit_sample.json`
- 实例数据宿主机目录：`/root/hummingbot-api/bots/instances/bot_20261126161333-20261126-161343/data`
- 2026-11-28 17:41 UTC 容器为 `running`，健康检查为 healthy；17:39–17:41 UTC 持续出现新 BUY 成交和新 SELL TP。
- `scripts/condor_recreate.py` 的健康检查已补充恢复阻断检测：当前容器标准输出或最新启动后的日志文件出现 `Order recovery blocked` / `Executor recovery blocked` 时返回 `(False, 'order recovery blocked')`；旧启动周期之前的历史错误不会误报。服务器副本已更新，当前实盘只读结果为 healthy；此改动不需要重启 Bot。

## 2026-11-28 停止挂单异常与修复

- 异常期间最后一笔新挂单停在 15:54:34 UTC；同一秒出现 `Order recovery blocked: duplicate order id`，最后一笔完整成交为 16:05:15 UTC。
- 根因已确认：TP 完成事件将同一 TrackedOrder 同时留在 `_take_profit_limit_order` 和 `_close_order`，后续快照把同一订单写入 `take_profit_order` 与 `close_order`，触发 RecoveryStore 的重复订单保护。
- 修复位于 `position_executor/recovery.py`：当 TP 与 close 指向同一订单时，快照只保留 `take_profit_order`，省略重复的 `close_order`；现有恢复逻辑可根据 FILLED TP 重建收尾状态。
- 新增完成事件回归先失败后通过；新镜像内去重后的完整回归 68 项通过。测试输出中的 disk full 和无效端口是故障场景测试的预期日志。
- 17:38:41 UTC 已切换到 `v2.17.0-recovery-tp-dedup`。重建前 167 条接管记录全部有保护标记。
- 142 笔部署前基线订单中 141 笔保留；减少的 1 笔为普通 BUY，在启动后被正常刷新撤销。部署后快照新增 4 笔开放订单。
- 部署后恢复文件有 179 个 Executor、184 个唯一订单引用且无重复；观察期内未再出现 `Order recovery blocked`、`Executor recovery blocked` 或 duplicate order。
- 配置与 docker inspect 备份位于 `/root/condor-backups/recreated-bots/`，文件名带 `before-tp-dedup`。

## 最近确认的实盘配置

- `no_budget_tp_cancel_distance_pct: '0.05'`：预算不足时允许撤销距离超过 5% 的最远开放 TP。
- `no_budget_retry_seconds: 60`
- `HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN=true`

这些是最近确认值，不是不可变默认值。修改前先读取实际配置。

## 恢复能力与验证

- RecoveryStore、Binance 快照适配器、Executor 恢复、READY/BLOCKED 门控和 `hbot stop --keep-open-orders` 已实现。
- `scripts/condor_bootstrap_recovery.py` 为既有开放订单建立接管记录，并给历史 `adopted-*` 记录补写 `recovery_adopted=True`。
- 修复提交 `9a33867` 的相关完整回归为 71 项通过。
- 2026-11-28 15:41:52 UTC 使用 SIGKILL + `docker start` 重启，165 条接管记录在重启前全部有保护标记。
- 重启前开放订单快照为 139 笔；重启后快照为 146 笔。137 笔基线订单仍在，2 笔被撤销，9 笔新增。
- 被撤销的 2 笔是上次恢复后策略新建的普通订单，不是接管订单；它们在启动后被正常策略刷新撤销。137 笔接管旧订单均保留并重新加载。
- 最近启动日志未发现 `Order recovery blocked` 或 `Executor recovery blocked`。

## 重要限制与待确认事项

- “停止和启动不撤单”不等于“启动后策略永不撤单”。普通恢复订单仍可能按刷新和 effectivization 规则撤单。
- 历史上早期恢复曾发生旧订单撤销；不能将此前尝试描述为全部保留成功。
- 接管订单只监控，不自动生成新 TP；普通订单继续原策略生命周期。
- 当前恢复首版只支持 Binance 现货和本 Controller，不支持跨实例订单去重。
- 当前状态文件不保存实时订单清单。需要订单信息时重新查询交易所并保存带时间戳的本地快照。
- 服务器开发目录有既存修改，不得直接整目录覆盖或用 `git reset --hard` 清理。

## 常用入口

- 部署与故障排查：根目录 `README.md`
- 策略设计：`docs/superpowers/specs/2026-11-25-pmm-mister-loss-exit-design.md`
- 保留订单重建：`scripts/condor_recreate.py`
- 接管引导：`scripts/condor_bootstrap_recovery.py`
- 只读恢复诊断：`scripts/condor_recovery_check.py`
- 临时 Condor 登录：`condor_login.py` / `condor_login.cmd`
