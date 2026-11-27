import argparse
import json
import os
import pathlib
import subprocess
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
        if mount["Destination"].rstrip("/").endswith("/conf/controllers"):
            for path in pathlib.Path(mount["Source"]).glob("*.yml"):
                if "_paper_trade" in path.read_text(encoding="utf-8"):
                    return False
    return True


def write_environment(inspect, env_file):
    lines = list(inspect["Config"].get("Env") or [])
    if not any(line.startswith("HEADLESS_MODE=") for line in lines):
        lines.append("HEADLESS_MODE=true")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(env_file, 0o600)


def health_check(inspect):
    state = json.loads(docker("inspect", inspect["Name"].lstrip("/")))[0]["State"]
    if not state.get("Running"):
        return False, f"container is not running (exit={state.get('ExitCode')})"
    for mount in inspect["Mounts"]:
        if mount["Destination"].rstrip("/") != "/home/hummingbot/logs":
            continue
        files = sorted(
            pathlib.Path(mount["Source"]).glob("logs_bot_*.log"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return False, "no strategy log found"
        lines = files[0].read_text(encoding="utf-8").splitlines()[-100:]
        text = "\n".join(lines)
        if "Input is not a terminal" in text or "Failed to start strategy" in text:
            return False, "strategy startup failed"
        if "strategy execution started" not in text:
            return False, "strategy did not start"
        return True, "healthy"
    return False, "log mount not found"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Recreate a Condor bot while preserving its configuration and data.")
    parser.add_argument("--container", required=True)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--live", action="store_true")
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

    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    ENV_ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUP_ROOT, 0o700)
    os.chmod(ENV_ROOT, 0o700)
    (BACKUP_ROOT / f"{name}.json").write_text(json.dumps(inspect, indent=2), encoding="utf-8")
    env_file = ENV_ROOT / f"{name}.env"
    write_environment(inspect, env_file)
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
