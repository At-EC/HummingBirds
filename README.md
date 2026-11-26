![Hummingbot](https://github.com/user-attachments/assets/3213d7f8-414b-4df8-8c1b-a0cd142a82d8)

----
[![License](https://img.shields.io/badge/License-Apache%202.0-informational.svg)](https://github.com/hummingbot/hummingbot/blob/master/LICENSE)
[![Twitter](https://img.shields.io/twitter/url?url=https://twitter.com/_hummingbot?style=social&label=_hummingbot)](https://twitter.com/_hummingbot)
[![Youtube](https://img.shields.io/youtube/channel/subscribers/UCxzzdEnDRbylLMWmaMjywOA)](https://www.youtube.com/@hummingbot)
[![Discord](https://img.shields.io/discord/530578568154054663?logo=discord&logoColor=white&style=flat-square)](https://discord.gg/hummingbot)

Hummingbot is an open-source framework that helps you design and deploy automated trading strategies, or **bots**, that can run on many centralized or decentralized exchanges. Over the past year, Hummingbot users have generated over $34 billion in trading volume across 140+ unique trading venues.

The Hummingbot codebase is free and publicly available under the Apache 2.0 open-source license. Our mission is to **democratize high-frequency trading** by creating a global community of algorithmic traders and developers that share knowledge and contribute to the codebase.

## Quick Links

* [Website and Docs](https://hummingbot.org): Official Hummingbot website and documentation
* [Installation](https://hummingbot.org/installation/): Install Hummingbot on various platforms
* [Discord](https://discord.gg/hummingbot): The main gathering spot for the global Hummingbot community
* [YouTube](https://www.youtube.com/c/hummingbot): Videos that teach you how to get the most out of Hummingbot
* [Twitter](https://twitter.com/_hummingbot): Get the latest announcements about Hummingbot
* [Reported Volumes](https://reporting.hummingbot.org/): Reported trading volumes across all Hummingbot instances
* [Newsletter](https://hummingbot.substack.com): Get our newsletter whenever we ship a new release

## Getting Started

### Condor (AI harness)

**[Condor](https://github.com/hummingbot/condor)** is the AI harness for building and running agentic strategies and bot instances. It connects LLM-powered decision-making to deterministic trade execution via the Hummingbot API, controlled through Telegram or its web dashboard. See **[condor.hummingbot.org](https://condor.hummingbot.org/)** to get started.

### `hbot` CLI

The recommended way to run the Hummingbot client directly is the **`hbot` command-line interface**, installed from
source. `hbot` runs, controls, and monitors a trading bot non-interactively: start/stop a bot, author
and tune configs, and read trades, PnL, logs, and status — all scriptable, as compact Markdown with
stable exit codes. See the **[hbot CLI guide](hummingbot/cli/README.md)** for the full reference.

Requires [Anaconda or Miniconda](https://www.anaconda.com/download).

```bash
# Clone the repository
git clone https://github.com/hummingbot/hummingbot.git
cd hummingbot

# Create the conda environment, build extensions, and expose the `hbot` CLI
make install

# Activate the environment
conda activate hummingbot
hbot --help
```

To use `hbot` outside the conda environment, run `make link-cli` to add it to your host PATH.

On first use, `hbot` prompts for a keystore password that encrypts your exchange API keys — set `HBOT_PASSWORD` or pass `--password-stdin` to run non-interactively (e.g. in scripts or agent workflows).

Then create a config and run the `simple_pmm` **paper trading script** — it simulates trading against live Binance market data, so no API keys are required:

```bash
hbot create simple_pmm --name conf_paper_bot.yml \
     --set exchange=binance_paper_trade --set trading_pair=BTC-USDT
hbot start conf_paper_bot.yml                          # run it (one bot per install)
hbot status                                            # check on it
hbot stop                                              # stop gracefully
```

To trade **live**, connect your exchange API keys and run a **strategy controller** like `pmm_mister` — a reusable V2 strategy whose settings can be tuned live while the bot runs:

```bash
hbot connect binance                                   # store API keys (encrypted)
hbot create pmm_mister --name conf_my_bot.yml \
     --set connector_name=binance --set trading_pair=BTC-USDT --set total_amount_quote=100
hbot start conf_my_bot.yml                             # run it (one bot per install)
```

Full command reference and ontology: **[hbot CLI guide](hummingbot/cli/README.md)**.

### Docker

Prefer containers? `hbot` works the same way — install [Docker Compose](https://docs.docker.com/compose/install/), then:

```bash
git clone https://github.com/hummingbot/hummingbot.git
cd hummingbot
make setup            # answer `y` to "Include Gateway?" to add the DEX middleware
make deploy           # start the container (interactive client by default)
make link-cli         # put the `hbot` command on your host PATH (dispatches into the container)

hbot --help           # same commands as the source install above
```

`make link-cli` installs a small wrapper that runs `hbot` inside the container, so every command
above is identical whether you installed from source or Docker. (Or skip it and use
`docker exec -it hummingbot hbot <command>`.) To dedicate the container to `hbot` instead of the
interactive client, uncomment `command: tail -f /dev/null` in `docker-compose.yml` before
`make deploy` — see [Running in Docker](hummingbot/cli/README.md#running-in-docker).

### Interactive Client (TUI)

The classic full-screen client is the Docker default:
`make deploy`, then `docker attach hummingbot` — or run it from source with
`make install && make run`. With Gateway included it starts in development mode
(unencrypted HTTP); for production HTTPS use the `DEV=false` flag and run `gateway generate-certs`.
See [Development vs Production Modes](https://hummingbot.org/gateway/installation/#development-vs-production-modes).

---

For comprehensive installation instructions and troubleshooting, visit our [Installation](https://hummingbot.org/installation/) documentation.

## Strategies

Hummingbot offers several frameworks for building and running algorithmic trading strategies — see the [Strategies docs](https://hummingbot.org/strategies/) for a full overview:

* **[Scripts](./scripts)**: Single-file Python strategies — the easiest way to build and customize your own bot. Example: [`simple_pmm.py`](./scripts/simple_pmm.py), a basic market making script.
* **[Controllers](./controllers)**: Reusable V2 strategies whose configs can be backtested, deployed, and tuned live while running. Example: [`pmm_mister.py`](./controllers/generic/pmm_mister.py), a full-featured market making controller.
* **[Executors](./hummingbot/strategy_v2/executors)**: Self-contained building blocks that manage order lifecycles for common patterns — position, DCA, grid, arbitrage, XEMM, TWAP, and LP. Example: [`position_executor`](./hummingbot/strategy_v2/executors/position_executor), which manages a directional position with triple-barrier risk controls.
* **[V1 Strategies](./hummingbot/strategy)**: Classic legacy strategies such as Pure Market Making, Avellaneda Market Making, and Cross-Exchange Market Making. Example: [`cross_exchange_market_making`](./hummingbot/strategy/cross_exchange_market_making), which market makes on one exchange and hedges fills on another.

## Exchange Connectors

Hummingbot connectors standardize REST and WebSocket API interfaces to different types of exchanges, enabling you to build sophisticated trading strategies that can be deployed across many exchanges with minimal changes.

### Connector Types

We classify exchange connectors into three main categories:

* **CLOB CEX**: Centralized exchanges with central limit order books that take custody of your funds. Connect via API keys.
  - **Spot**: Trading spot markets
  - **Perpetual**: Trading perpetual futures markets

* **CLOB DEX**: Decentralized exchanges with on-chain central limit order books. Non-custodial, connect via wallet keys.
  - **Spot**: Trading spot markets on-chain
  - **Perpetual**: Trading perpetual futures on-chain

* **AMM DEX**: Decentralized exchanges using Automated Market Maker protocols. Non-custodial, connect via Gateway middleware.
  - **Router**: DEX aggregators that find optimal swap routes
  - **AMM**: Traditional constant product (x*y=k) pools
  - **CLMM**: Concentrated Liquidity Market Maker pools with custom price ranges

### Exchange Sponsors

We are grateful for the following exchanges that support the development and maintenance of Hummingbot via broker partnerships and sponsorships.

| Exchange | Type | Sub-Type(s) | Connector ID(s) | Discount |
|------|------|------|-------|----------|
| [Backpack](https://hummingbot.org/exchanges/backpack/) | CLOB CEX | Spot, Perpetual | `backpack`, `backpack_perpetual` | [![Sign up for Backpack using Hummingbot's referral link!](https://img.shields.io/static/v1?label=Sponsor&message=Link&color=orange)](https://backpack.exchange/join/1tvdqfkk) |
| [Binance](https://hummingbot.org/exchanges/binance/) | CLOB CEX | Spot, Perpetual | `binance`, `binance_perpetual` | [![Sign up for Binance using Hummingbot's referral link for a 10% discount!](https://img.shields.io/static/v1?label=Fee&message=%2d10%25&color=orange)](https://accounts.binance.com/register?ref=CBWO4LU6) |
| [Bitget](https://hummingbot.org/exchanges/bitget/) | CLOB CEX | Spot, Perpetual | `bitget`, `bitget_perpetual` | [![Sign up for Bitget using Hummingbot's referral link!](https://img.shields.io/static/v1?label=Sponsor&message=Link&color=orange)](https://www.bitget.com/expressly?channelCode=v9cb&vipCode=26rr&languageType=0) |
| [Derive](https://hummingbot.org/exchanges/derive/) | CLOB DEX | Spot, Perpetual | `derive`, `derive_perpetual` | [![Sign up for Derive using Hummingbot's referral link!](https://img.shields.io/static/v1?label=Sponsor&message=Link&color=orange)](https://www.derive.xyz/invite/7SA0V) |
| [Gate.io](https://hummingbot.org/exchanges/gate-io/) | CLOB CEX | Spot, Perpetual | `gate_io`, `gate_io_perpetual` | [![Sign up for Gate.io using Hummingbot's referral link for a 20% discount!](https://img.shields.io/static/v1?label=Fee&message=%2d20%25&color=orange)](https://www.gate.io/referral/invite/HBOTGATE_0_103) |
| [Hyperliquid](https://hummingbot.org/exchanges/hyperliquid/) | CLOB DEX | Spot, Perpetual | `hyperliquid`, `hyperliquid_perpetual` | - |
| [KuCoin](https://hummingbot.org/exchanges/kucoin/) | CLOB CEX | Spot, Perpetual | `kucoin`, `kucoin_perpetual` | [![Sign up for Kucoin using Hummingbot's referral link for a 20% discount!](https://img.shields.io/static/v1?label=Fee&message=%2d20%25&color=orange)](https://www.kucoin.com/r/af/hummingbot) |
| [Meteora](https://hummingbot.org/exchanges/gateway/meteora/) | AMM DEX | CLMM | `meteora` | - |
| [OKX](https://hummingbot.org/exchanges/okx/) | CLOB CEX | Spot, Perpetual | `okx`, `okx_perpetual` | [![Sign up for OKX using Hummingbot's referral link for a 20% discount!](https://img.shields.io/static/v1?label=Fee&message=%2d20%25&color=orange)](https://www.okx.com/join/1931920269) |
| [Orca](https://hummingbot.org/exchanges/gateway/orca/) | AMM DEX | CLMM | `orca` | - |
| [XRP Ledger](https://hummingbot.org/exchanges/xrpl/) | CLOB DEX | Spot | `xrpl` | - |

### Other Exchange Connectors

Currently, the master branch of Hummingbot also includes the following exchange connectors, which are maintained and updated through the Hummingbot Foundation governance process. See [Governance](https://hummingbot.org/about/governance/) for more information.

| Exchange | Type | Sub-Type(s) | Connector ID(s) | Discount |
|------|------|------|-------|----------|
| [0x Protocol](https://hummingbot.org/gateway/connectors/) | AMM DEX | Router | `0x` | - |
| [Aevo](https://hummingbot.org/exchanges/aevo/) | CLOB CEX | Perpetual | `aevo_perpetual` | - |
| [Architect](https://hummingbot.org/exchanges/architect/) | CLOB CEX | Perpetual | `architect_perpetual` | - |
| [Balancer](https://hummingbot.org/exchanges/gateway/balancer/) | AMM DEX | AMM | `balancer` | - |
| [BingX](https://hummingbot.org/exchanges/bing_x/) | CLOB CEX | Spot | `bing_x` | - |
| [Bitrue](https://hummingbot.org/exchanges/bitrue/) | CLOB CEX | Spot | `bitrue` | - |
| [Bitstamp](https://hummingbot.org/exchanges/bitstamp/) | CLOB CEX | Spot | `bitstamp` | - |
| [BTC Markets](https://hummingbot.org/exchanges/btc-markets/) | CLOB CEX | Spot | `btc_markets` | - |
| [Bybit](https://hummingbot.org/exchanges/bybit/) | CLOB CEX | Spot, Perpetual | `bybit`, `bybit_perpetual` | - |
| [Coinbase](https://hummingbot.org/exchanges/coinbase/) | CLOB CEX | Spot | `coinbase_advanced_trade` | - |
| [Curve](https://hummingbot.org/exchanges/gateway/curve/) | AMM DEX | AMM | `curve` | - |
| [Decibel](https://hummingbot.org/exchanges/decibel/) | CLOB CEX | Perpetual | `decibel_perpetual` | - |
| [Dexalot](https://hummingbot.org/exchanges/dexalot/) | CLOB DEX | Spot | `dexalot` | - |
| [DFlow](https://hummingbot.org/exchanges/gateway/jupiter/#other-solana-routers) | AMM DEX | Router | `dflow` | - |
| [dYdX](https://hummingbot.org/exchanges/dydx/) | CLOB DEX | Perpetual | `dydx_v4_perpetual` | - |
| [EVEDEX](https://hummingbot.org/exchanges/evedex/) | CLOB CEX | Perpetual | `evedex_perpetual` | - |
| [Foxbit](https://hummingbot.org/exchanges/foxbit/) | CLOB CEX | Spot | `foxbit` | - |
| [Gemini](https://hummingbot.org/exchanges/gemini/) | CLOB CEX | Spot | `gemini` | - |
| [GRVT](https://hummingbot.org/exchanges/grvt/) | CLOB CEX | Perpetual | `grvt_perpetual` | - |
| [HTX (Huobi)](https://hummingbot.org/exchanges/htx/) | CLOB CEX | Spot | `htx` | - |
| [Injective Helix](https://hummingbot.org/exchanges/injective/) | CLOB DEX | Spot, Perpetual | `injective_v2`, `injective_v2_perpetual` | - |
| [Jupiter](https://hummingbot.org/exchanges/gateway/jupiter/) | AMM DEX | Router | `jupiter` | - |
| [Kraken](https://hummingbot.org/exchanges/kraken/) | CLOB CEX | Spot | `kraken` | - |
| [Lambdaplex](https://hummingbot.org/exchanges/lambdaplex/) | CLOB DEX | Spot | `lambdaplex` | - |
| [Lighter](https://hummingbot.org/exchanges/lighter/) | CLOB DEX | Spot, Perpetual | `lighter`, `lighter_perpetual` | - |
| [MEXC](https://hummingbot.org/exchanges/mexc/) | CLOB CEX | Spot | `mexc` | - |
| [NDAX](https://hummingbot.org/exchanges/ndax/) | CLOB CEX | Spot | `ndax` | - |
| [OKX DEX](https://hummingbot.org/exchanges/gateway/jupiter/#other-solana-routers) | AMM DEX | Router | `okx` | - |
| [Pacifica](https://hummingbot.org/exchanges/pacifica/) | CLOB CEX | Perpetual | `pacifica_perpetual` | - |
| [PancakeSwap](https://hummingbot.org/exchanges/gateway/pancakeswap/) | AMM DEX | Router | `pancakeswap` | - |
| [Raydium](https://hummingbot.org/exchanges/gateway/raydium/) | AMM DEX | AMM, CLMM | `raydium` | - |
| [Titan](https://hummingbot.org/exchanges/gateway/jupiter/#other-solana-routers) | AMM DEX | Router | `titan` | - |
| [Uniswap](https://hummingbot.org/exchanges/gateway/uniswap/) | AMM DEX | Router | `uniswap` | - |

## Other Hummingbot Repos

* [Condor](https://github.com/hummingbot/condor): AI harness for building and running agentic strategies and bot instances
* [Hummingbot API](https://github.com/hummingbot/hummingbot-api): The central hub for running Hummingbot trading bots
* [Gateway](https://github.com/hummingbot/gateway): Typescript based API client for DEX connectors
* [Hummingbot Site](https://github.com/hummingbot/hummingbot-site): Official documentation for Hummingbot - we welcome contributions here too!

## Getting Help

If you encounter issues or have questions, here's how you can get assistance:

* Consult our [FAQ](https://hummingbot.org/faq/), [Troubleshooting Guide](https://hummingbot.org/troubleshooting/), or [Glossary](https://hummingbot.org/glossary/)
* To report bugs or suggest features, submit a [GitHub issue](https://github.com/hummingbot/hummingbot/issues)
* Join our [Discord community](https://discord.gg/hummingbot) and ask questions in the #support channel

We pledge that we will not use the information/data you provide us for trading purposes nor share them with third parties.

## Contributions

The Hummingbot architecture features modular components that can be maintained and extended by individual community members.

We welcome contributions from the community! Please review these [guidelines](./CONTRIBUTING.md) before submitting a pull request.

If you represent an exchange that wants an official Hummingbot connector, see [How to Add a Hummingbot Connector](https://hummingbot.org/exchanges/#how-to-add-a-hummingbot-connector) for the available integration options.

## Legal

* **License**: Hummingbot is open source and licensed under [Apache 2.0](./LICENSE).
* **Data collection**: See [Reporting](https://hummingbot.org/reporting/) for information on anonymous data collection and reporting in Hummingbot.


## PMM Mister Loss Exit：服务器安装与运维手册

本节介绍如何在远程 Linux 服务器上，将 `pmm_mister_loss_exit` 安装到正在运行的官方 Hummingbot Docker 容器中。

安装器采用**原容器覆盖更新**：备份原文件，停止容器，覆盖运行时文件，重新启动并验证。不会删除或重建容器，也不会修改容器的镜像、挂载、端口、环境变量、交易所密钥或重启策略。

> **重要提示**
>
> - 当前仅支持 Hummingbot **2.17.0 或 2.18.0**。
> - `--yes` 会停止并重新启动容器，会产生短暂停机。
> - 必须先在 paper trade 容器验证，不要直接更新真实资金 Bot。
> - 修改了 PositionExecutor 等已加载模块，因此不能只复制文件而不重启。

### 1. 安装流程

```text
检查 Docker、容器和 Hummingbot 版本
→ 保存 docker inspect 和原文件
→ docker stop
→ docker cp 覆盖 9 个运行时文件
→ docker start
→ py_compile 与新 Controller 导入检查
→ 成功保留备份；失败自动恢复备份
```

每次安装都会生成独立备份，支持重复执行和失败回滚。

### 2. 服务器要求

- Linux 或 WSL；
- Bash；
- Docker CLI，且当前用户有权限执行 `docker inspect`、`docker exec`、`docker cp`、`docker stop` 和 `docker start`；
- 已运行官方 Hummingbot 2.17.0 或 2.18.0 容器；
- 能够访问 GitHub。

先检查 Docker 和容器：

```bash
docker version
docker ps
```

确认目标容器名称。以下示例统一使用 `hummingbot`，如果你的名称不同，请替换：

```bash
docker inspect --format '{{.State.Running}}' hummingbot
docker exec hummingbot cat /home/hummingbot/hummingbot/VERSION
```

预期分别输出：

```text
true
2.17.0 或 2.18.0
```

### 3. 下载源码

```bash
git clone <repository-url> HummingBirds
cd HummingBirds
chmod +x package_release.sh install_loss_exit.sh
```

如果仓库已经存在：

```bash
cd HummingBirds
git pull
chmod +x package_release.sh install_loss_exit.sh
```

建议更新前确认提交：

```bash
git log -1 --oneline
```

### 4. 执行预检

先运行 dry-run：

```bash
./install_loss_exit.sh --container hummingbot --dry-run
```

预检会检查：

- 源文件是否完整；
- 容器是否存在且正在运行；
- Hummingbot 版本是否为 2.17.0 或 2.18.0；
- 安装计划和源目录。

不带 `--dry-run` 或 `--yes` 时，也只显示计划，不会停止或修改容器：

```bash
./install_loss_exit.sh --container hummingbot
```

### 5. 执行安装

确认预检无误后：

```bash
./install_loss_exit.sh --container hummingbot --yes
```

成功时会看到类似输出：

```text
Container: hummingbot
Hummingbot: 2.17.0 或 2.18.0
Runtime files: 9
Backup: /path/to/loss-exit-backups/YYYYMMDD-HHMMSS-PID
PMMisterLossExit
Update verified successfully.
```

默认备份目录：

```text
./loss-exit-backups/
```

备份中包含：

- `container-inspect.json`；
- 被覆盖文件的原始版本；
- 安装前不存在的文件清单，用于回滚时删除。

### 6. 安装后验证

检查容器状态：

```bash
docker inspect --format '{{.State.Running}}' hummingbot
docker logs --tail 100 hummingbot
```

手动验证新 Controller 可以导入：

```bash
docker exec --workdir /home/hummingbot hummingbot \
  /opt/conda/envs/hummingbot/bin/python -c \
  'from controllers.generic.pmm_mister_loss_exit import PMMisterLossExit, PMMisterLossExitConfig; print(PMMisterLossExit.__name__)'
```

预期输出：

```text
PMMisterLossExit
```

如果导入失败，安装器会自动恢复备份并尝试重新启动容器。请保留终端错误信息和备份目录。

### 7. 配置 paper trade

在 Condor Workspace Editor 上传以下两个文件：

1. `controllers/generic/pmm_mister.py`
2. `controllers/generic/pmm_mister_loss_exit.py`

参考 `controllers/generic/pmm_mister_loss_exit.example.yml` 创建配置。初期建议：

```yaml
connector_name: binance_paper_trade
loss_exit_trigger_pct: '0.005'
loss_exit_offset_pct: '0.001'
loss_exit_cooldown_seconds: 60
loss_exit_activation_delay_seconds: 60
tp_order_distance_tolerance_pct: '0.001'
```

`tp_order_distance_tolerance_pct` 用于避免新挂单与当前仍开放的 TP 价格过于接近。`0.001` 表示 0.1%，设为 `0` 时禁用。距离严格小于容忍度的冲突档位不创建，其他档位继续；等于容忍度时允许。已撤销或已完成的 TP 不参与过滤。

先做一次禁用功能回归：

```yaml
loss_exit_trigger_pct:
```

确认普通 TP 和 POSITION_HOLD 行为正常后，再启用功能并检查：

- 浮亏条件持续满足后才会激活；
- 多笔候选只退出当前最大浮亏订单；
- 当前订单完成前不会激活下一笔；
- 部分成交后只处理剩余数量；
- 冷却时间内不会频繁撤单；
- 重启后恢复记录会阻止未对账的自动补单。

参数热更新只影响之后新建的 Executor；已有订单需要重启后统一使用新参数。串行锁仅在单个 Controller 内有效，不要用它保证多个 Controller 之间的订单去重。

`buy_position_effectivization_time` 和 `sell_position_effectivization_time` 具有最高优先级：只有原 TP 在有效时间内且仍开放时才允许激活撤退；到期后，激活等待、候选和 ACTIVE 撤退都必须停止并撤销 TP，不得继续重挂。若激活等待时间超过 effectivization 时间，订单通常会先进入 POSITION_HOLD，这是预期行为。

### 8. 重复安装和升级

安装器可重复运行，每次都会生成新备份：

```bash
./install_loss_exit.sh --container hummingbot --yes
```

升级源码后：

```bash
git pull
./install_loss_exit.sh --container hummingbot --dry-run
./install_loss_exit.sh --container hummingbot --yes
```

不需要重新构建 Docker 镜像。

### 9. 故障回滚

安装过程中出现复制失败、语法错误或导入失败时，脚本会尝试自动回滚，包括：

1. 停止容器；
2. 恢复已有文件；
3. 启动容器；
4. 删除本次新增文件。

如果需要手动回滚，找到安装输出中的 `Backup:` 路径，然后执行：

```bash
BACKUP_DIR=/path/to/loss-exit-backups/YYYYMMDD-HHMMSS-PID
CONTAINER_NAME=hummingbot

docker stop --timeout 60 "$CONTAINER_NAME"

cd "$BACKUP_DIR/files"
find . -type f -print0 | while IFS= read -r -d '' file; do
  docker cp "$file" "$CONTAINER_NAME:/home/hummingbot/${file#./}"
done

docker start "$CONTAINER_NAME"

while IFS= read -r path; do
  docker exec "$CONTAINER_NAME" rm -f "/home/hummingbot/$path"
done < "$BACKUP_DIR/added-files.txt"
```

随后再次执行导入检查和日志检查。

### 10. 环境变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `CONTAINER_NAME` | `hummingbot` | 默认容器名，也可通过 `--container` 指定 |
| `CONTAINER_HOME` | `/home/hummingbot` | 容器内 Hummingbot 根目录 |
| `STOP_TIMEOUT` | `60` | 停止容器时等待的秒数 |
| `BACKUP_ROOT` | `$PWD/loss-exit-backups` | 备份根目录 |
| `ALLOW_VERSION_MISMATCH` | `0` | 设为 `1` 时允许非 2.17.0 或 2.18.0 版本，风险较高 |

示例：

```bash
BACKUP_ROOT=/var/backups/hummingbot \
STOP_TIMEOUT=90 \
./install_loss_exit.sh --container hummingbot --yes
```

不建议在未审查兼容性的情况下使用：

```bash
ALLOW_VERSION_MISMATCH=1 ./install_loss_exit.sh --container hummingbot --yes
```

### 11. 生成最小发布包

在完整仓库中运行：

```bash
./package_release.sh
```

生成：

```text
release/pmm-loss-exit-overlay.tar.gz
release/pmm-loss-exit-overlay.tar.gz.sha256
```

校验：

```bash
sha256sum -c release/pmm-loss-exit-overlay.tar.gz.sha256
```

离线服务器安装：

```bash
tar -xzf pmm-loss-exit-overlay.tar.gz -C /opt/pmm-loss-exit
cd /opt/pmm-loss-exit
chmod +x install_loss_exit.sh
./install_loss_exit.sh --container hummingbot --dry-run
./install_loss_exit.sh --container hummingbot --yes
```

发布包仅包含运行时必需文件、安装脚本和说明，不包含完整 Hummingbot 源码和测试文件。

### 12. 常见问题

| 问题 | 原因与处理 |
|---|---|
| `Container not found` | 容器名错误或 Docker 权限不足。运行 `docker ps` 并修正 `--container`。 |
| `Container is not running` | 先启动容器，再执行安装。 |
| `Unsupported Hummingbot version` | 当前只支持 2.17.0 或 2.18.0；先确认官方版本，不要盲目强制安装。 |
| `Missing source file` | 仓库不完整、路径错误或发布包损坏；重新 clone 或重新解压。 |
| `Permission denied` | 当前用户无法操作 Docker；将用户加入 Docker 组或由管理员执行。 |
| 安装后导入失败 | 安装器会回滚；保存错误日志和备份目录，检查目标版本与文件完整性。 |
| 更新后策略未出现 | 确认上传的是两个 Controller 文件，并检查 Condor 是否指向已更新的 Bot 容器。 |
| 脚本无法执行 | 运行 `chmod +x package_release.sh install_loss_exit.sh`，并确认 shell 文件为 LF 换行。 |
| 容器长时间未停止 | 调整 `STOP_TIMEOUT`，并先通过正常方式停止策略和交易。 |

### 13. 实盘前检查清单

- [ ] 原生 Strategy V2 测试通过；
- [ ] paper trade 部署成功；
- [ ] 禁用功能时与原策略行为一致；
- [ ] 延迟激活和计时重置正确；
- [ ] 多候选串行退出正确；
- [ ] 部分成交没有超额卖出或买回；
- [ ] 冷却重挂和外部撤单正常；
- [ ] 重启恢复记录能够阻止未对账补单；
- [ ] 已设置资金和最大回撤限制；
- [ ] 已确认备份位置和回滚命令。

完成上述验证后，才考虑使用小资金实盘。
