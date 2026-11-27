# PMM Mister Loss Exit：部署与运维手册

本仓库包含 `pmm_mister_loss_exit` Controller、Hummingbot 2.17.0 自定义镜像、发布包、Condor 注册与实例重建工具。

策略用于现货做市：当原 TP 长期未成交且浮亏达到条件时，按最大浮亏串行撤销并重挂退出订单，释放库存。亏损退出会主动实现亏损，不保证盈利或减少总亏损。

**先使用 Paper Trade 验证。实盘部署前必须确认交易所、交易对、订单、持仓和资金限制。**

## 1. 文件结构

```text
controllers/generic/
  pmm_mister.py                     # 基础 PMM Mister，不覆盖 Condor 中的现有版本
  pmm_mister_loss_exit.py           # 新 Controller
  pmm_mister_loss_exit.example.yml  # 配置示例

hummingbot/
  data_feed/market_data_provider.py
  strategy_v2/controllers/
  strategy_v2/executors/
  strategy_v2/models/

agents/_shared/skills/pmm_mister_loss_exit/
  SKILL.md
  pmm_mister_loss_exit.sample.yml   # Paper Trade 示例

Dockerfile                          # 固定已验证的 2.17.0 基础镜像 digest
package_release.sh                  # 生成 overlay 发布包
install_loss_exit.sh                # 独立容器覆盖安装与回滚
condor_login.py                     # 可重复使用的 Condor SSH 临时登录工具
condor_login.cmd                    # Windows 双击启动器
scripts/
  setup_condor.sh                   # 注册 Condor Controller 和示例配置
  condor_recreate.py                # 保留实例配置，替换镜像并健康检查
  test_release_scripts.sh
  test_overlay_container.sh
tests/                              # 策略、部署脚本与登录工具回归测试
```

当前自定义镜像：

```text
hummingbot/pmm-mister-loss-exit:v2.17.0
```

`version-2.17.0` 标签曾返回 `dev-2.18.0`，因此 Dockerfile 固定使用已验证的镜像 digest，不依赖可变标签。

## 2. 构建自定义镜像

```bash
git clone https://github.com/At-EC/HummingBirds.git
cd HummingBirds
chmod +x package_release.sh install_loss_exit.sh scripts/setup_condor.sh
docker build -t hummingbot/pmm-mister-loss-exit:v2.17.0 .
```

验证版本和 Controller：

```bash
docker run --rm hummingbot/pmm-mister-loss-exit:v2.17.0 \
  cat /home/hummingbot/hummingbot/VERSION

docker run --rm --workdir /home/hummingbot \
  hummingbot/pmm-mister-loss-exit:v2.17.0 \
  /opt/conda/envs/hummingbot/bin/python -c \
  'from controllers.generic.pmm_mister_loss_exit import PMMisterLossExit; print(PMMisterLossExit.__name__)'
```

预期分别输出 `2.17.0` 和 `PMMisterLossExit`。

## 3. 发布包与独立容器安装

生成发布包：

```bash
./package_release.sh
sha256sum -c release/pmm-loss-exit-overlay.tar.gz.sha256
```

输出：

```text
release/pmm-loss-exit-overlay.tar.gz
release/pmm-loss-exit-overlay.tar.gz.sha256
```

安装器执行以下步骤：

1. 检查容器、版本和源文件。
2. 保存 `docker inspect` 和原文件。
3. 停止容器并覆盖 11 个运行时文件。
4. 启动容器并执行 `py_compile` 和 Controller 导入检查。
5. 失败时恢复原文件并删除本次新增文件。

先 dry-run：

```bash
./install_loss_exit.sh --container hummingbot --dry-run
```

确认后执行：

```bash
./install_loss_exit.sh --container hummingbot --yes
```

成功输出包含：

```text
Runtime files: 21
Update verified successfully.
```

`--yes` 会停止并重启目标容器。不能只复制文件而不重启，因为 PositionExecutor 等模块已经加载。

离线安装：

```bash
tar -xzf pmm-loss-exit-overlay.tar.gz -C /opt/pmm-loss-exit
cd /opt/pmm-loss-exit
chmod +x install_loss_exit.sh
./install_loss_exit.sh --container hummingbot --dry-run
./install_loss_exit.sh --container hummingbot --yes
```

## 4. Condor 模板注册

在仓库根目录执行：

```bash
./scripts/setup_condor.sh
```

脚本只复制以下两个文件并检查 Condor 是否能发现它们：

```text
/root/hummingbot-api/bots/controllers/generic/pmm_mister_loss_exit.py
/root/hummingbot-api/bots/conf/controllers/pmm_mister_loss_exit_sample.yml
```

它不会：

- 覆盖 Condor 现有 `pmm_mister.py`；
- 重启 Condor API；
- 创建或启动 Bot。

可选环境变量：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `CONDOR_BOTS_DIR` | `/root/hummingbot-api/bots` | Condor bots 根目录 |
| `CONDOR_API_CONTAINER` | `hummingbot-api` | Condor API 容器名 |

刷新 Deploy Bot 页面，查找 `pmm_mister_loss_exit_sample`。部署时必须将镜像明确设置为：

```text
hummingbot/pmm-mister-loss-exit:v2.17.0
```

**不要使用默认 `hummingbot/hummingbot:latest`，否则会缺少亏损退出核心模块。**

## 5. 通用实例重建

`condor_recreate.py` 用于修复已部署实例的镜像和无界面启动问题，同时保留：

- 环境变量与交易所凭据；
- 配置、数据目录、订单记录和日志；
- Entrypoint、Cmd、WorkingDir；
- 网络、Labels 和重启策略。

### Dry-run

```bash
python3 scripts/condor_recreate.py --container BOT_NAME
```

只显示当前镜像、目标镜像、挂载数、网络、启动命令和实盘状态，不停止、删除或创建容器。

### Paper Trade 重建

```bash
python3 scripts/condor_recreate.py --container BOT_NAME --yes
```

### 实盘重建

```bash
python3 scripts/condor_recreate.py --container BOT_NAME --yes --live
```

实盘配置必须同时提供 `--yes` 和 `--live`，否则脚本拒绝执行。

脚本行为：

1. 将完整 `docker inspect` 保存到 `/root/condor-backups/recreated-bots/`。
2. 使用权限 `0600` 的临时环境文件，结束后删除。
3. 缺少 `HEADLESS_MODE` 时追加 `HEADLESS_MODE=true`，不覆盖已有设置。
4. 使用自定义镜像重建；创建失败时使用原镜像回滚。
5. 检查容器状态和最新策略日志，容器 Up 但策略失败仍返回失败。

不会输出环境变量或密钥值。

## 6. 核心参数

| 参数 | 示例 | 含义 |
|---|---|---|
| `loss_exit_trigger_pct` | `0.005` | 浮亏达到 0.5% 后进入激活等待；留空禁用 |
| `loss_exit_offset_pct` | `0.001` | 退出限价单距离当前盘口 0.1% |
| `loss_exit_cooldown_seconds` | `60` | 同一退出订单两次实际重挂的最小间隔 |
| `loss_exit_activation_delay_seconds` | `60` | 浮亏必须连续满足 60 秒才可成为候选 |
| `tp_order_distance_tolerance_pct` | `0.001` | 新挂单与开放 TP，或其成交后预期 TP 与已有同向开放 TP，距离小于 0.1% 时跳过该档位；`0` 禁用 |
| `min_order_amount_quote` | `10` | 最低下单名义金额（quote），低于时跳过；`0` 禁用 |
| `no_budget_retry_seconds` | `300` | 明确预算错误后的暂停秒数；成交立即恢复，亏损退出激活与退出 TP 豁免 |
| `buy_position_effectivization_time` | `120` | BUY TP 有效秒数，到期优先撤单并进入 POSITION_HOLD |
| `sell_position_effectivization_time` | `120` | SELL TP 有效秒数，到期优先撤单并进入 POSITION_HOLD |

补充规则：

- 浮亏最大的一笔优先退出，完成后才重新筛选其他候选。
- 部分成交只处理剩余数量。
- 新挂单只跳过与当前开放 TP 冲突的档位，其他档位继续。
- 普通开单和原始 TP 在预算暂停期间停止，亏损退出激活与退出 TP 必须继续，避免撤单后无法重挂。
- 预算暂停只保存在内存中，重启 Controller 后清除。
- 串行锁仅在单个 Controller 内有效，不保证多个 Controller 或容器之间去重。

## 7. 验证

```bash
bash tests/test_setup_condor.sh
python -m pytest tests/test_condor_recreate.py -q
python -m pytest tests/order_budget_regression.py \
  tests/order_budget_controller_regression.py \
  tests/order_budget_executor_regression.py -q
python -m unittest discover -s tests -p 'test_condor_login.py' -v
bash scripts/test_release_scripts.sh
TEST_IMAGE=hummingbot/pmm-mister-loss-exit:v2.17.0 \
  bash scripts/test_overlay_container.sh
```

独立安装测试包括重复安装、故障回滚、Controller 导入和新增文件检查。

Paper Trade 示例使用：

```yaml
connector_name: binance_paper_trade
trading_pair: BTC-USDT
open_order_type: LIMIT
take_profit_order_type: LIMIT
min_order_amount_quote: '10'
no_budget_retry_seconds: 300
```

Paper Trade 与实盘的区别：

- `binance_paper_trade` 使用公共行情和模拟余额，不提交真实订单。
- `binance` 使用真实账户，会创建真实订单并产生真实盈亏。
- 切换前必须重新检查 connector、交易对和 API 凭据，不要仅替换镜像后假设仍是模拟交易。

## 8. 故障排查

| 问题 | 原因与处理 |
|---|---|
| Deploy Bot 中没有新模板 | 先运行 `scripts/setup_condor.sh`，再刷新页面；直接启动的独立容器不会自动注册模板。 |
| `No module named loss_exit_recovery` | 使用了官方 `latest` 镜像。改为 `hummingbot/pmm-mister-loss-exit:v2.17.0`。 |
| 容器 Up 但策略失败 | 查看实例日志，不要只检查容器状态；重建脚本也会执行策略健康检查。 |
| `Input is not a terminal` | quickstart 进入 UI。确保 `HEADLESS_MODE=true`，不要仅追加 TTY。 |
| 镜像内部显示 `dev-2.18.0` | 使用了错误的 `version-2.17.0` 标签。使用仓库固定 digest 的 Dockerfile 重建。 |
| 脚本 `Permission denied` | 执行 `chmod +x package_release.sh install_loss_exit.sh scripts/setup_condor.sh`，并确认 LF 换行。 |
| 实盘缺少 `--live` | 这是安全保护。确认真实订单风险后再同时提供 `--yes --live`。 |
| 强制停止后订单状态未知 | 同时检查数据库和交易所订单，不能假定 Created 订单已撤销。 |
| 安装后需要恢复 | 安装器自动回滚；保留输出中的 Backup 路径和错误日志。 |

## 9. 实盘检查清单

- [ ] 自定义镜像版本为 2.17.0。
- [ ] 发布包、独立安装和回滚测试通过。
- [ ] Condor 模板和配置已注册。
- [ ] Paper Trade 中普通开单、TP、退出和预算恢复均已验证。
- [ ] 已确认 connector、交易对、资金和最大回撤限制。
- [ ] 已核对 Binance 当前挂单和持仓，没有重复订单。
- [ ] 已确认无界面启动与策略健康检查通过。
- [ ] 已知备份位置和回滚命令。
- [ ] 首次实盘使用小资金并持续观察日志。

## 10. Condor 临时登录工具

`condor_login.py` 通过 SSH 生成 24 小时管理员会话、建立隧道并打开本地 Condor 页面，无需 Telegram，也不修改服务器认证配置或 Bot。

### Windows 双击使用

直接双击仓库根目录的 `condor_login.cmd`。启动器自动寻找 Python 3，并将参数传给 `condor_login.py`。

默认读取以下本地文件：

```text
ssh/id_ed25519
ssh/known_hosts
```

这些文件是本地私密配置，不在仓库中，不要提交或分享。需要指定其他路径时，在终端执行：

```powershell
python condor_login.py --key "C:\path\id_ed25519" --known-hosts "C:\path\known_hosts"
```

### 命令行使用

```bash
python condor_login.py
```

脚本自动打开 `http://localhost:18082/`。保持终端运行以维持本地访问，按 `Ctrl+C` 清理临时代理和脚本创建的 SSH 隧道。会话过期后重新运行即可。

可选参数：

| 参数 | 默认值 | 用途 |
|---|---|---|
| `--host` | `103.193.150.25` | SSH 服务器地址 |
| `--user` | `root` | SSH 用户 |
| `--key` | `ssh/id_ed25519` | 本地 SSH 私钥 |
| `--known-hosts` | `ssh/known_hosts` | 本地服务器指纹文件 |
| `--port` | `18082` | 本地 Condor 访问端口 |
| `--no-open` | 关闭 | 不自动打开浏览器 |

端口被占用时换用其他端口：

```bash
python condor_login.py --port 18083
```

安全行为：

- JWT 只用于内存中的一次性同源登录，不出现在 URL、日志或磁盘文件中。
- 代理仅监听 `127.0.0.1`，不能从局域网或公网访问。
- 强制校验 SSH 主机指纹，不自动接受新指纹。
- 脚本只终止自己创建的隧道，不影响已有连接。

### 服务器部署目录

登录工具的独立服务器副本位于：

```text
/root/condor-login
```

更新该副本：

```bash
cd /root/condor-login
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_condor_login.py' -v
```

该目录仅保存工具和测试，不运行后台服务。日常登录仍在本地 Windows 机器运行脚本。现有 `/root/HummingBirds`、Condor 服务和 Bot 不因登录工具更新而改变。


## 11. 保留开放订单与重启恢复（开发分支）

本功能只适用于 `pmm_mister_loss_exit`、Binance 现货和受支持的恢复适配器。默认停止行为不变，仍撤销开放订单；不要将 `SIGKILL` 作为部署方式。

### 前置条件

- 当前容器和目标镜像都包含恢复组件。
- 第一次升级到恢复版本时，必须使用默认撤单更新；之后才可使用保留订单更新。
- 保留订单更新前必须通过全部 Paper 场景和只读订单检查。
- 对账完成前不会创建新订单或激活亏损退出。

### 显式保留订单停止

```bash
hbot stop --keep-open-orders
```

普通 `hbot stop` 和 SIGTERM 仍撤销开放订单。保留订单停止使用独立信号并调用 `skip_order_cancellation=True`。

### 保留订单重建

Paper：

```bash
python3 scripts/condor_recreate.py \
  --container BOT_NAME --keep-open-orders --yes
```

实盘必须同时确认：

```bash
python3 scripts/condor_recreate.py \
  --container BOT_NAME --keep-open-orders --yes --live
```

如果原容器或目标镜像缺少恢复组件，脚本会拒绝执行。不得绕过该检查。

### 恢复状态

- `READY`：订单和持仓对账完成，可以恢复交易。
- `RECONCILING`：正在查询和恢复，不挂新单。
- `BLOCKED`：存在 UNKNOWN、数量不一致、未跟踪订单或保存失败，不挂新单，也不激活亏损退出。

只读诊断：

```bash
python3 scripts/condor_recovery_check.py --container BOT_NAME
```

该命令只读取恢复记录和交易所订单，不写状态、不撤单、不挂单。

### 安全限制

- 首版不支持其他 Connector 或多个 Controller 交叉管理同一交易对。
- 停止期间全部成交的 TP 不会重挂；部分成交只恢复剩余数量。
- 外部撤单进入 POSITION_HOLD 收尾，不自动创建新 TP。
- 不兼容的旧镜像不能用于保留订单回滚；回滚目标也必须包含恢复组件。
- Paper Trade 的进程内模拟订单不能完全代表交易所真实订单，实盘前仍需 Binance 只读适配器验证和明确批准。
