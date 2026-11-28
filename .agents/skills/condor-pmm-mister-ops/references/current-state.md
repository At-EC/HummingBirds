# 当前项目状态

最近验证：2026-11-28（服务器 UTC）。以下是带时间戳的快照；执行新任务时必须重新验证运行状态、订单和部署文件。

## 仓库

- 远程仓库：`https://github.com/At-EC/HummingBirds.git`
- 当前功能分支：`feat/keep-open-orders-recovery`
- 最近验证的策略修复提交：`784ef79 fix: clear resolved loss exit recovery records`
- 近期恢复提交：`8d73efb`（TP 快照去重）、`26d24da`（完成退出释放锁）
- Condor 状态发布提交：`12d05cd feat: publish recovery state to Condor`
- Condor API 服务器本地提交：`2ee1a45 fix: surface blocked order recovery in bot status`（未宣称已推送其上游仓库）
- Draft PR：`https://github.com/At-EC/HummingBirds/pull/1`
- 本地开发目录：`recovery-worktree`
- 服务器开发目录：`/root/recovery-live`

## 实盘环境快照

- SSH 主机：`root@103.193.150.25`；使用本地既有密钥和 `known_hosts`，秘密不进入仓库。
- Bot 容器：`bot_20261126161333-20261126-161343`
- 运行镜像：`hummingbot/pmm-mister-loss-exit:v2.17.0-recovery-legacy-cleanup`
- Controller：`pmm_mister_loss_exit`
- Controller 配置 ID：`pmm_mister_loss_exit_sample`
- Connector / 交易对：Binance 现货，`ZEC-USDT`
- 恢复记录：容器内 `data/pmm_mister_loss_exit/runtime/pmm_mister_loss_exit_sample.json`
- 实例数据宿主机目录：`/root/hummingbot-api/bots/instances/bot_20261126161333-20261126-161343/data`
- 2026-11-28 18:51 UTC 容器 running、健康检查 healthy，Condor API 返回 `status=running`、`recovery_blocked=false`，Controller 为 `READY`；已出现新订单和成交。
- `scripts/condor_recreate.py` 的健康检查会识别当前启动周期内的 Order/Executor recovery blocked，并忽略旧启动周期的历史错误。

## 2026-11-28 恢复与 Condor 状态修复

- TP 完成时的重复快照已通过 `8d73efb` 修复：TP 与 close 为同一订单时只序列化一次。
- 遥测部署后稳定复现 `multiple loss exit locks found`。实测磁盘有 5 条 COMPLETED、0 条锁；恢复过程把这些历史已完成记录重新变成锁。
- `26d24da` 将调度锁限制为 ACTIVATING / ACTIVE；COMPLETED 不再重新持锁。新增恢复回归先失败后通过。
- `pmm_mister_loss_exit.get_custom_info()` 发布 `recovery_state` 和 `recovery_blocked`；Condor API 在任一 Controller 阻断时返回 `status=error`，正常 READY 时保持 running。现有前端对 error 显示红色，无需修改前端。
- 已在实际 Condor API 验证阻断时返回 error / true，修复后返回 running / false。没有可控制的已打开浏览器标签，因此未声称做过视觉截图验证。
- 多锁修复前 152 笔订单中 150 笔保留，2 笔普通订单由策略刷新撤销，部署后快照新增 4 笔。175 条接管记录在最终重建前全部有保护标记。
- Condor API 相关测试（含状态推送、停止与归档）在 asyncio auto 模式下 76 项通过。
- 配置和容器备份位于 `/root/condor-backups/recreated-bots/`，旧记录清理部署使用 `before-legacy-cleanup` 文件，旧 JSON 另有 `loss-exit-legacy.before-cleanup.json` 备份。
- `784ef79` 只清理被主恢复记录证明为 COMPLETED / TERMINATED、无锁、无活动退出单且无需对账的旧文件；其他记录继续保留并告警。最新启动后旧 JSON 文件数为 0，不再出现 Unfinished loss exit record 警告。
- 旧记录清理部署的 153 笔订单全部保留，新增 5 笔；完整策略 pytest 回归 45 项通过。

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
