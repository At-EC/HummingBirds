import argparse
import json
import os
import pathlib
import subprocess
import tempfile
import time

DEFAULT_IMAGE = "hummingbot/pmm-mister-loss-exit:v2.17.0"
BACKUP_ROOT = pathlib.Path(os.environ.get("CONDOR_BACKUP_ROOT", "/root/condor-backups/recreated-bots"))
ENV_ROOT = pathlib.Path(os.environ.get("CONDOR_ENV_ROOT", "/root/condor-recreate-env"))


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout.strip()


def build_run_args(inspect, env_file, image):
    config, host = inspect["Config"], inspect["HostConfig"]
    args = [
        "run", "-d", "--name", inspect["Name"].lstrip("/"),
        "--restart", host["RestartPolicy"]["Name"] or "no",
        "--network", host["NetworkMode"],
        "--env-file", str(env_file),
        "--workdir", config["WorkingDir"],
    ]
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
        destination = mount["Destination"].rstrip("/")
        source = pathlib.Path(mount["Source"])
        if destination.endswith("/conf/controllers"):
            config_paths = list(source.glob("*.yml"))
        elif "/conf/controllers/" in destination and destination.endswith(".yml"):
            config_paths = [source]
        else:
            continue
        for path in config_paths:
            if "_paper_trade" in path.read_text(encoding="utf-8"):
                return False
    return True


def write_environment(inspect, env_file, keep_open_orders=False):
    lines = [
        line for line in (inspect["Config"].get("Env") or [])
        if not line.startswith("HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN=")
    ]
    if not any(line.startswith("HEADLESS_MODE=") for line in lines):
        lines.append("HEADLESS_MODE=true")
    if keep_open_orders:
        lines.append("HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN=true")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(env_file, 0o600)


def stop_keep_open_orders(container_name):
    state = json.loads(docker("inspect", container_name))[0]["State"]
    if not state.get("Running"):
        return
    try:
        docker(
            "exec", container_name, "/opt/conda/envs/hummingbot/bin/hbot", "stop",
            "--keep-open-orders", "--timeout", "60",
        )
    except subprocess.CalledProcessError as error:
        if error.returncode != 137:
            raise
        state = json.loads(docker("inspect", container_name))[0]["State"]
        if state.get("Running"):
            raise


def recovery_supported(container_name):
    paths = [
        "/home/hummingbot/hummingbot/strategy_v2/controllers/executor_recovery.py",
        "/home/hummingbot/hummingbot/connector/exchange/binance/binance_order_recovery.py",
    ]
    try:
        with tempfile.TemporaryDirectory(prefix="condor-recovery-probe-") as directory:
            for path in paths:
                docker("cp", f"{container_name}:{path}", directory)
                if not (pathlib.Path(directory) / pathlib.Path(path).name).is_file():
                    return False
        return True
    except subprocess.CalledProcessError:
        return False


def image_supports_recovery(image):
    paths = [
        "/home/hummingbot/hummingbot/strategy_v2/controllers/executor_recovery.py",
        "/home/hummingbot/hummingbot/connector/exchange/binance/binance_order_recovery.py",
    ]
    try:
        for path in paths:
            docker("run", "--rm", image, "test", "-f", path)
        return True
    except subprocess.CalledProcessError:
        return False


def health_check(inspect):
    state = json.loads(docker("inspect", inspect["Name"].lstrip("/")))[0]["State"]
    if not state.get("Running"):
        return False, f"container is not running (exit={state.get('ExitCode')})"
    name = inspect["Name"].lstrip("/")
    try:
        stdout = docker("logs", "--since", state["StartedAt"], name)
        if "Input is not a terminal" in stdout or "Failed to start strategy" in stdout:
            return False, "strategy startup failed"
        if "strategy execution started" in stdout:
            return True, "healthy"
    except (subprocess.CalledProcessError, KeyError):
        pass
    for mount in inspect["Mounts"]:
        if mount["Destination"].rstrip("/") != "/home/hummingbot/logs":
            continue
        files = sorted(
            pathlib.Path(mount["Source"]).glob("logs_*.log"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return False, "no strategy log found"
        lines = files[0].read_text(encoding="utf-8").splitlines()
        startup_lines = [
            index for index, line in enumerate(lines)
            if "strategy execution started" in line
        ]
        if not startup_lines:
            return False, "strategy did not start"
        text = "\n".join(lines[startup_lines[-1]:])
        if "Input is not a terminal" in text or "Failed to start strategy" in text:
            return False, "strategy startup failed"
        return True, "healthy"
    return False, "log mount not found"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Recreate a Condor bot while preserving its configuration and data.")
    parser.add_argument("--container", required=True)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--keep-open-orders", action="store_true")
    args = parser.parse_args(argv)

    name = args.container
    inspect = json.loads(docker("inspect", name))[0]
    original_image = inspect["Config"]["Image"]
    live = is_live_deployment(inspect)
    print(f"CONTAINER={name}")
    print(f"CURRENT_IMAGE={original_image}")
    print(f"TARGET_IMAGE={args.image}")
    print(f"MOUNTS={len(inspect['Mounts'])}")
    print(f"NETWORK={inspect['HostConfig']['NetworkMode']}")
    print(f"CMD={inspect['Config'].get('Cmd') or []}")
    print(f"LIVE_DEPLOYMENT={live}")
    if not args.yes:
        print("DRY_RUN=true")
        return 0
    if live and not args.live:
        print("Refusing live deployment without --live")
        return 2
    if args.keep_open_orders:
        if not recovery_supported(name):
            print("Refusing keep-open-orders: current container lacks recovery support")
            return 2
        if not image_supports_recovery(args.image):
            print("Refusing keep-open-orders: target image lacks recovery support")
            return 2
        stop_keep_open_orders(name)

    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    ENV_ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUP_ROOT, 0o700)
    os.chmod(ENV_ROOT, 0o700)
    (BACKUP_ROOT / f"{name}.json").write_text(json.dumps(inspect, indent=2), encoding="utf-8")
    env_file = ENV_ROOT / f"{name}.env"
    write_environment(inspect, env_file, keep_open_orders=args.keep_open_orders)
    docker("rm", "-f", name)
    try:
        container_id = docker(*build_run_args(inspect, env_file, args.image))
        print(f"RECREATED={name} ID={container_id[:12]}")
    except subprocess.CalledProcessError as error:
        print(f"CUSTOM_IMAGE_FAILED={error.stderr[:500]}")
        rollback_id = docker(*build_run_args(inspect, env_file, original_image))
        print(f"ROLLBACK={rollback_id[:12]} IMAGE={original_image}")
        return 1
    finally:
        env_file.unlink(missing_ok=True)

    time.sleep(5)
    healthy, detail = health_check(inspect)
    print(f"HEALTH={detail}")
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
