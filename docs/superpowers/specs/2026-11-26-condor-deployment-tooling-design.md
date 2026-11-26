# Condor 部署工具链与 README 精简设计

日期：2026-11-26  
状态：已确认方案 A

## 目标

将本次部署中实际遇到的镜像错误、模板未注册、无界面退出、敏感配置保留和失败回滚整理为通用工具，避免重复手动修复。README 删除官方 Hummingbot 介绍，只保留本仓库策略和部署运维说明。

## 方案

### `scripts/setup_condor.sh`

职责：

- 从仓库复制 `pmm_mister_loss_exit.py` 和示例 YAML 到 Condor 对应目录。
- 不覆盖 Condor 现有 `pmm_mister.py`，避免删除其额外保护逻辑。
- 使用 Condor 实际文件系统检查 Controller 与配置是否存在。
- 输出模板名称、Controller 名称、connector、订单类型和自定义镜像。
- 不重启 Condor API，不创建或启动 Bot。

参数：

- `CONDOR_BOTS_DIR`，默认 `/root/hummingbot-api/bots`。
- `CONDOR_API_CONTAINER`，默认 `hummingbot-api`。
- 默认只执行文件复制和检查，不修改其他目录。

### `scripts/condor_recreate.py`

职责：保留实例配置和数据，仅替换容器镜像并修复无界面启动。

接口：

```text
--container NAME       必填，实例容器名
--image IMAGE          可选，默认 hummingbot/pmm-mister-loss-exit:v2.17.0
--yes                  实际停止、删除并重建；缺省仅 dry-run
--live                 明确允许按实盘配置重建
```

行为：

1. dry-run 显示目标镜像、挂载数量、网络、启动命令和实盘状态，不停止或删除容器。
2. 实际执行前读取 `docker inspect`，将完整备份保存到 root 私有目录。
3. 保留原环境变量、挂载、数据目录、Entrypoint、Cmd、WorkingDir、NetworkMode、RestartPolicy 和 Labels。
4. 若不存在 `HEADLESS_MODE`，追加 `HEADLESS_MODE=true`；不覆盖用户显式设置。
5. 临时环境文件权限为 `0600`，执行后删除，日志不输出环境变量或密钥。
6. 新镜像创建失败时使用原镜像重建并报告失败。
7. 启动后检查容器状态、策略日志中的模块缺失、策略启动成功和 TTY 错误；未通过检查不得宣称成功。
8. 检测配置中的 `binance` 等实盘 connector 时，必须同时提供 `--yes` 和 `--live`；Paper Trade 只需 `--yes`。

## README 全量重写

只包含：

- 策略功能与风险说明。
- 仓库文件结构和自定义镜像。
- 构建、发布包、独立安装和回滚。
- Condor 模板导入及正确镜像设置。
- 通用实例重建命令与 dry-run 示例。
- Paper Trade 与实盘的区别。
- 核心参数表。
- 本次实际故障及对应处理：错误镜像、模板不可见、缺少核心模块、无 TTY、配置/数据保留、实盘订单核对。
- 验证命令与部署检查清单。

删除官方 Hummingbot 项目介绍、交易所列表、赞助链接和其他无关内容。

## 测试

- dry-run 不停止、删除或创建容器。
- 正确注入自定义镜像和 `HEADLESS_MODE=true`，不覆盖已有设置。
- 挂载、启动命令、网络、标签和重启策略保持不变。
- 新镜像失败时调用原镜像回滚。
- 实盘缺少 `--live` 时拒绝执行。
- 临时环境文件被删除，标准输出不包含密钥值。
- 容器运行但策略失败时健康检查失败。
- 发布包和独立安装测试保持通过。

## 发布方式

- 先更新功能分支并运行测试。
- 通过 GitHub 集成直接推送到 `main`，不创建 PR。
- 不自动重建或停止当前正在运行的实盘 Bot。
