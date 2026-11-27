# Condor Deployment Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供可重复使用的 Condor 模板注册与实例重建工具，并将 README 精简为本仓库部署运维手册。

**Architecture:** `setup_condor.sh` 只负责文件注册和发现检查；`condor_recreate.py` 负责保留实例配置的镜像替换、dry-run、回滚和健康检查。测试使用临时目录和 mocked Docker 调用，不接触真实 Bot。

**Tech Stack:** Bash、Python 3 标准库、pytest、Docker CLI、Markdown。

## Global Constraints

- 默认镜像为 `hummingbot/pmm-mister-loss-exit:v2.17.0`。
- 不覆盖 Condor 现有 `pmm_mister.py`，不重启 API，不自动启动实盘 Bot。
- 只有 `--yes` 才重建；实盘必须额外提供 `--live`。
- 保留环境变量、挂载、数据、Entrypoint、Cmd、WorkingDir、NetworkMode、RestartPolicy 和 Labels。
- 不输出密钥；临时环境文件权限 `0600` 且执行后删除。
- 容器 Up 但策略失败仍视为失败。

---

### Task 1: Condor 模板注册脚本

**Files:**
- Create: `scripts/setup_condor.sh`
- Test: `tests/test_setup_condor.sh`

**Interfaces:**
- `CONDOR_BOTS_DIR` 默认 `/root/hummingbot-api/bots`。
- `CONDOR_API_CONTAINER` 默认 `hummingbot-api`。

- [ ] **Step 1: 写失败测试**

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bots/controllers/generic" "$TMP/bots/conf/controllers"
cat > "$TMP/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_DOCKER_LOG"
if [[ "$*" == *"CONTROLLER_PRESENT"* ]]; then
  printf 'CONTROLLER_PRESENT True\nCONFIG_PRESENT True\n'
fi
EOF
chmod +x "$TMP/docker"
export MOCK_DOCKER_LOG="$TMP/docker.log"
export PATH="$TMP:$PATH"
export CONDOR_BOTS_DIR="$TMP/bots"
export CONDOR_API_CONTAINER=hummingbot-api

"$ROOT/scripts/setup_condor.sh"

test -f "$TMP/bots/controllers/generic/pmm_mister_loss_exit.py"
test -f "$TMP/bots/conf/controllers/pmm_mister_loss_exit_sample.yml"
test ! -e "$TMP/bots/controllers/generic/pmm_mister.py"
grep 'CONFIG_PRESENT True' "$MOCK_DOCKER_LOG" >/dev/null
grep 'CONTROLLER_PRESENT True' "$MOCK_DOCKER_LOG" >/dev/null
```

- [ ] **Step 2: 运行测试确认失败**

Run: `bash tests/test_setup_condor.sh`
Expected: `scripts/setup_condor.sh` 不存在，FAIL。

- [ ] **Step 3: 实现注册脚本**

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOTS="${CONDOR_BOTS_DIR:-/root/hummingbot-api/bots}"
API="${CONDOR_API_CONTAINER:-hummingbot-api}"
CONTROLLER_SRC="$ROOT/controllers/generic/pmm_mister_loss_exit.py"
CONFIG_SRC="$ROOT/agents/_shared/skills/pmm_mister_loss_exit/pmm_mister_loss_exit.sample.yml"
CONTROLLER_DST="$BOTS/controllers/generic/pmm_mister_loss_exit.py"
CONFIG_DST="$BOTS/conf/controllers/pmm_mister_loss_exit_sample.yml"
mkdir -p "$(dirname "$CONTROLLER_DST")" "$(dirname "$CONFIG_DST")"
cp "$CONTROLLER_SRC" "$CONTROLLER_DST"
cp "$CONFIG_SRC" "$CONFIG_DST"
docker exec "$API" python -c \
  'from utils.file_system import fs_util; c=[f for f in fs_util.list_files("controllers/generic") if f.endswith(".py")]; y=[f for f in fs_util.list_files("conf/controllers") if f.endswith(".yml")]; print("CONTROLLER_PRESENT", "pmm_mister_loss_exit.py" in c); print("CONFIG_PRESENT", "pmm_mister_loss_exit_sample.yml" in y); config=fs_util.read_yaml_file("conf/controllers/pmm_mister_loss_exit_sample.yml"); print("CONTROLLER", config.get("controller_name")); print("CONNECTOR", config.get("connector_name")); print("ORDER_TYPES", config.get("open_order_type"), config.get("take_profit_order_type"))'
printf 'IMAGE=hummingbot/pmm-mister-loss-exit:v2.17.0\n'
```

- [ ] **Step 4: 运行测试确认通过**

Run: `bash tests/test_setup_condor.sh`
Expected: exit 0，两个文件存在，原 `pmm_mister.py` 未创建或覆盖。

- [ ] **Step 5: 提交**

```bash
git add scripts/setup_condor.sh tests/test_setup_condor.sh
git commit -m "feat: add Condor template setup script"
```

---

### Task 2: 通用实例重建与健康检查

**Files:**
- Create: `scripts/condor_recreate.py`
- Test: `tests/test_condor_recreate.py`

**Interfaces:**
- `--container NAME`、`--image IMAGE`、`--yes`、`--live`。
- `build_run_args(inspect, env_file, image) -> list[str]`
- `is_live_deployment(inspect) -> bool`
- `main() -> int`

- [ ] **Step 1: 写失败测试**

```python
import json
import subprocess
from scripts.condor_recreate import build_run_args, is_live_deployment, main


def make_inspect():
    return {
        "Name": "/demo",
        "Config": {
            "Image": "hummingbot/hummingbot:latest",
            "Env": ["CONFIG_PASSWORD=secret"],
            "Entrypoint": ["/entry"],
            "Cmd": ["run"],
            "WorkingDir": "/home/hummingbot",
            "Labels": {"a": "b"},
        },
        "HostConfig": {"RestartPolicy": {"Name": "no"}, "NetworkMode": "host"},
        "Mounts": [{"Source": "/a", "Destination": "/b", "Mode": "rw"}],
    }


def test_args_preserve_runtime_and_force_headless():
    inspect = make_inspect()
    args = build_run_args(inspect, "/tmp/env", "custom:image")
    assert "custom:image" in args
    assert "/a:/b:rw" in args
    assert "run" in args
    assert is_live_deployment(inspect)


def test_secret_not_in_arguments():
    args = build_run_args(make_inspect(), "/tmp/env", "custom:image")
    assert "CONFIG_PASSWORD=secret" not in args
    assert "/tmp/env" in args


def test_dry_run_does_not_mutate_container(monkeypatch):
    calls = []

    class Result:
        stdout = json.dumps([make_inspect()])
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args) or Result())
    assert main(["--container", "demo"]) == 0
    assert all(call[0][1] == "inspect" for call in calls)


def test_custom_image_failure_restores_original(monkeypatch):
    calls = []

    class Result:
        def __init__(self, stdout="", stderr=""):
            self.stdout = stdout
            self.stderr = stderr

    inspect = make_inspect()
    responses = [
        Result(stdout=json.dumps([inspect])),
        subprocess.CalledProcessError(1, ["docker", "run"], stderr="failed"),
        Result(stdout="original-id"),
    ]
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args) or responses.pop(0))
    assert main(["--container", "demo", "--yes", "--live"]) != 0
    run_images = [call[0][-2] for call in calls if call[0][1] == "run"]
    assert run_images == ["custom:image", "hummingbot/hummingbot:latest"]


def test_paper_trade_is_not_live(tmp_path):
    controllers = tmp_path / "controllers"
    controllers.mkdir()
    (controllers / "sample.yml").write_text("connector_name: binance_paper_trade\n")
    inspect = make_inspect()
    inspect["Mounts"] = [{"Source": str(controllers), "Destination": "/home/hummingbot/conf/controllers", "Mode": "rw"}]
    assert not is_live_deployment(inspect)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_condor_recreate.py -q`
Expected: 模块不存在，FAIL。

- [ ] **Step 3: 实现重建与回滚**

实现以下接口，不在日志中输出 `Config.Env`：

```python
def build_run_args(inspect, env_file, image):
    config, host = inspect["Config"], inspect["HostConfig"]
    args = ["run", "-d", "--name", inspect["Name"].lstrip("/"),
            "--restart", host["RestartPolicy"]["Name"] or "no",
            "--network", host["NetworkMode"], "--env-file", str(env_file),
            "--workdir", config["WorkingDir"]]
    for mount in inspect["Mounts"]:
        mode = "ro" if mount.get("Mode") == "ro" else "rw"
        args += ["-v", f"{mount['Source']}:{mount['Destination']}:{mode}"]
    for key, value in config.get("Labels", {}).items():
        args += ["--label", f"{key}={value}"]
    if config.get("Entrypoint"):
        args += ["--entrypoint", config["Entrypoint"][0]]
    args.append(image)
    args += config.get("Cmd") or []
    return args


def is_live_deployment(inspect):
    for mount in inspect["Mounts"]:
        if mount["Destination"].rstrip("/").endswith("/conf/controllers"):
            for path in Path(mount["Source"]).glob("*.yml"):
                if "_paper_trade" in path.read_text():
                    return False
    return True
```

主流程必须满足：

```python
# dry-run: 只打印名称、原/目标镜像、挂载数、网络、启动命令和 live 状态
# --yes 且无 --live 且 is_live_deployment() 为 True：拒绝执行
# inspect 备份目录权限 0700，环境文件权限 0600
# env 缺少 HEADLESS_MODE 时追加 HEADLESS_MODE=true
# docker rm -f 后运行自定义镜像；失败时运行原镜像
# finally 删除临时 env 文件
# 启动后要求 State.Running=true，且最新策略日志包含 strategy execution started，
# 不包含 loss_exit_recovery 缺失、Input is not a terminal 或失败退出。
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_condor_recreate.py -q`
Expected: 参数保留、镜像、无界面和敏感信息测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add scripts/condor_recreate.py tests/test_condor_recreate.py
git commit -m "feat: add safe Condor instance recreation"
```

---

### Task 3: README 全量重写与最终验证

**Files:**
- Rewrite: `README.md`

**Interfaces:**
- 使用 Task 1 和 Task 2 的真实命令，不保留官方 Hummingbot 介绍。

- [ ] **Step 1: 重写 README**

包含以下真实命令：

```bash
git clone https://github.com/At-EC/HummingBirds.git
cd HummingBirds
chmod +x package_release.sh install_loss_exit.sh scripts/setup_condor.sh
docker build -t hummingbot/pmm-mister-loss-exit:v2.17.0 .
./scripts/setup_condor.sh
python3 scripts/condor_recreate.py --container BOT_NAME
python3 scripts/condor_recreate.py --container BOT_NAME --yes --live
bash scripts/test_release_scripts.sh
TEST_IMAGE=hummingbot/pmm-mister-loss-exit:v2.17.0 bash scripts/test_overlay_container.sh
```

文档章节固定为：策略与风险、文件结构、构建镜像、发布包与独立安装、Condor 导入、通用重建、核心参数、验证、故障排查、实盘检查清单。明确 `Runtime files: 11`，不再写 9。

- [ ] **Step 2: 检查文档内容**

Run:

```bash
python -c "from pathlib import Path; text=Path('README.md').read_text(); assert 'Runtime files: 11' in text; assert 'condor_recreate.py' in text; assert 'binance_paper_trade' in text; assert 'HEADLESS_MODE=true' in text; assert 'Sponsor' not in text; assert 'Getting Started' not in text"
```

Expected: exit 0。

- [ ] **Step 3: 运行全部验证**

Run:

```bash
bash tests/test_setup_condor.sh
python -m pytest tests/test_condor_recreate.py tests/order_budget_regression.py tests/order_budget_controller_regression.py tests/order_budget_executor_regression.py -q
bash scripts/test_release_scripts.sh
```

Expected: 全部 PASS；随后运行服务器独立安装与 Paper Trade 健康检查，不重建当前实盘 Bot。

- [ ] **Step 4: 提交并直接推送**

```bash
git add README.md scripts/setup_condor.sh scripts/condor_recreate.py tests/test_setup_condor.sh tests/test_condor_recreate.py
git commit -m "docs: rewrite deployment and recovery guide"
# 通过 GitHub 集成直接更新 main，不创建 PR
```
