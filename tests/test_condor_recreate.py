import json
import subprocess

from scripts.condor_recreate import build_run_args, health_check, is_live_deployment, main, write_environment


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
        Result(stdout=""),
        subprocess.CalledProcessError(1, ["docker", "run"], stderr="failed"),
        Result(stdout="original-id"),
    ]
    def fake_run(*args, **kwargs):
        calls.append(args)
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert main(["--container", "demo", "--image", "custom:image", "--yes", "--live"]) != 0
    run_images = [call[0][-2] for call in calls if call[0][1] == "run"]
    assert run_images == ["custom:image", "hummingbot/hummingbot:latest"]


def test_paper_trade_is_not_live(tmp_path):
    controllers = tmp_path / "controllers"
    controllers.mkdir()
    (controllers / "sample.yml").write_text("connector_name: binance_paper_trade\n")
    inspect = make_inspect()
    inspect["Mounts"] = [{"Source": str(controllers), "Destination": "/home/hummingbot/conf/controllers", "Mode": "rw"}]
    assert not is_live_deployment(inspect)


def test_environment_adds_headless_without_overwriting(tmp_path):
    env_file = tmp_path / "bot.env"
    inspect = make_inspect()
    write_environment(inspect, env_file)
    assert "HEADLESS_MODE=true" in env_file.read_text()
    inspect["Config"]["Env"] = ["HEADLESS_MODE=false"]
    write_environment(inspect, env_file)
    assert "HEADLESS_MODE=true" not in env_file.read_text()


def test_health_check_rejects_failed_strategy(monkeypatch, tmp_path):
    (tmp_path / "logs_bot_demo.log").write_text("Failed to start strategy\n")
    inspect = make_inspect()
    inspect["Mounts"] = [{"Source": str(tmp_path), "Destination": "/home/hummingbot/logs", "Mode": "rw"}]

    class Result:
        stdout = json.dumps([{"State": {"Running": True, "ExitCode": 0}}])
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())
    healthy, _ = health_check(inspect)
    assert not healthy



def test_environment_keep_open_orders_is_opt_in_and_removed_by_default(tmp_path):
    from scripts.condor_recreate import write_environment
    env_file = tmp_path / "bot.env"
    inspect = make_inspect()
    inspect["Config"]["Env"] = ["HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN=true"]
    write_environment(inspect, env_file, keep_open_orders=False)
    assert "HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN" not in env_file.read_text()
    write_environment(inspect, env_file, keep_open_orders=True)
    assert "HBOT_SKIP_ORDER_CANCELLATION_ON_SHUTDOWN=true" in env_file.read_text()


def test_keep_open_orders_refuses_incompatible_original(monkeypatch):
    from scripts import condor_recreate
    calls = []

    class Result:
        stdout = json.dumps([make_inspect()])
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args) or Result())
    monkeypatch.setattr(condor_recreate, "recovery_supported", lambda _: False)
    assert main([
        "--container", "demo", "--keep-open-orders", "--yes", "--live",
    ]) == 2
    assert all(call[0][1] != "rm" for call in calls)



def test_paper_trade_single_file_mount_is_not_live(tmp_path):
    config = tmp_path / "sample.yml"
    config.write_text("connector_name: binance_paper_trade\n")
    inspect = make_inspect()
    inspect["Mounts"] = [{
        "Source": str(config),
        "Destination": "/home/hummingbot/conf/controllers/sample.yml",
        "Mode": "rw",
    }]
    assert not is_live_deployment(inspect)



def test_keep_stop_accepts_137_only_when_container_stopped(monkeypatch):
    from scripts import condor_recreate
    calls = []

    states = iter([True, False])

    class Result:
        def __init__(self, running):
            self.stdout = json.dumps([{"State": {"Running": running}}])
            self.stderr = ""

    def fake_docker(*args):
        calls.append(args)
        if args[0] == "exec":
            raise subprocess.CalledProcessError(137, args, stderr="container exited")
        return Result(next(states)).stdout

    monkeypatch.setattr(condor_recreate, "docker", fake_docker)
    condor_recreate.stop_keep_open_orders("demo")
    assert calls[-1] == ("inspect", "demo")


def test_keep_stop_rejects_137_while_container_is_running(monkeypatch):
    from scripts import condor_recreate

    class Result:
        stdout = json.dumps([{"State": {"Running": True}}])
        stderr = ""

    def fake_docker(*args):
        if args[0] == "exec":
            raise subprocess.CalledProcessError(137, args, stderr="container exited")
        return Result().stdout

    monkeypatch.setattr(condor_recreate, "docker", fake_docker)
    try:
        condor_recreate.stop_keep_open_orders("demo")
    except subprocess.CalledProcessError:
        pass
    else:
        raise AssertionError("running container was accepted as stopped")



def test_recovery_support_check_uses_docker_cp_for_stopped_container(monkeypatch):
    from scripts import condor_recreate
    calls = []

    def fake_docker(*args):
        calls.append(args)
        source = args[1].split(":", 1)[1]
        from pathlib import Path
        target = Path(args[-1])
        (target / source.rsplit("/", 1)[-1]).touch()
        return ""

    monkeypatch.setattr(condor_recreate, "docker", fake_docker)
    assert condor_recreate.recovery_supported("demo")
    assert all(call[0] == "cp" for call in calls)
    assert all(call[1].startswith("demo:") for call in calls)



def test_keep_stop_is_noop_when_container_already_stopped(monkeypatch):
    from scripts import condor_recreate
    calls = []

    def fake_docker(*args):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([{"State": {"Running": False}}])
        raise AssertionError("stop must not be executed for a stopped container")

    monkeypatch.setattr(condor_recreate, "docker", fake_docker)
    condor_recreate.stop_keep_open_orders("demo")
    assert calls == [("inspect", "demo")]
