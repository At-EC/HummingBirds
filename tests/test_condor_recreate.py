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
