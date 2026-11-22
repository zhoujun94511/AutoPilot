"""自检测试调度回归：执行方式、进度、超时退出及完整失败日志。"""

from __future__ import annotations

import importlib.util
import ast
from pathlib import Path
import sys
import time


def _load_runner():
    path = Path(__file__).resolve().parents[1] / "skills" / "autopilot-lint" / "autocheck.py"
    spec = importlib.util.spec_from_file_location("autocheck_runner_test_target", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_command_runs_pytest_only_modules(tmp_path):
    runner = _load_runner()
    script = tmp_path / "script.py"
    script.write_text('if __name__ == "__main__":\n    raise SystemExit(0)\n', encoding="utf-8")
    pytest_module = tmp_path / "test_fixture.py"
    pytest_module.write_text('def test_value(tmp_path):\n    assert tmp_path.is_dir()\n',
                             encoding="utf-8")
    assert runner._test_command(sys.executable, str(script)) == [
        sys.executable, "-u", str(Path(runner.__file__).with_name("run_test_suite.py")), str(script),
    ]
    assert runner._test_command(sys.executable, str(pytest_module)) == [
        sys.executable, "-u", "-m", "pytest", "-p", "no:xonsh", "-q", str(pytest_module),
    ]


def test_timeout_keeps_logs_and_continues(tmp_path, monkeypatch, capsys):
    runner = _load_runner()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    scripts = {
        "test_blocked": (
            'import time\n'
            'if __name__ == "__main__":\n'
            '    print("entered blocking test", flush=True)\n'
            '    time.sleep(60)\n'
        ),
        "test_failed": (
            'import sys\n'
            'if __name__ == "__main__":\n'
            '    print("failure stdout", flush=True)\n'
            '    print("failure stderr", file=sys.stderr, flush=True)\n'
            '    raise SystemExit(7)\n'
        ),
        "test_passed": (
            'if __name__ == "__main__":\n'
            '    print("completed after timeout", flush=True)\n'
        ),
    }
    for name, source in scripts.items():
        (tests_dir / f"{name}.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", str(tmp_path))
    monkeypatch.setattr(runner, "_venv_python", lambda _root: sys.executable)
    monkeypatch.setattr(runner, "discover_test_suites", lambda: list(scripts))
    started = time.monotonic()
    result = runner.run_tests(timeout=1.0, heartbeat=0.1)
    assert result == (1, 2, 0, False)
    assert time.monotonic() - started < 10
    output = capsys.readouterr().out
    assert "仍在运行：test_blocked" in output
    assert "超时 1s" in output
    assert "PASS: test_passed" in output
    assert "failure stdout" in output and "failure stderr" in output
    log_dirs = list((tmp_path / "logs" / "autocheck").iterdir())
    assert len(log_dirs) == 1
    logs = log_dirs[0]
    assert "entered blocking test" in (logs / "test_blocked.log").read_text(encoding="utf-8")
    assert "completed after timeout" in (logs / "test_passed.log").read_text(encoding="utf-8")


def test_invalid_timeout_rejected():
    runner = _load_runner()
    for timeout in (0, -1, float("inf"), float("nan")):
        try:
            runner.run_tests(timeout=timeout)
        except ValueError as exc:
            assert "必须大于 0" in str(exc)
        else:
            raise AssertionError("an unbounded test timeout must not be accepted")


def test_shadow_checker_respects_nonlocal_and_global():
    runner = _load_runner()
    tree = ast.parse(
        "def outer():\n"
        "    budget_exhausted = False\n"
        "    vision_shot_used = False\n"
        "    actual_local = 0\n"
        "    def attempt():\n"
        "        nonlocal budget_exhausted, vision_shot_used\n"
        "        global shared_state\n"
        "        budget_exhausted = True\n"
        "        vision_shot_used = True\n"
        "        shared_state = 1\n"
        "        actual_local = 2\n"
    )
    outer = tree.body[0]
    assert isinstance(outer, ast.FunctionDef)
    inner = outer.body[-1]
    assert set(runner._scope_binds(inner)) == {"actual_local"}


def test_pytest_assertions_are_executed(tmp_path, monkeypatch):
    runner = _load_runner()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_real_assertion.py").write_text(
        'def test_assertion():\n    assert 1 == 2, "must be executed"\n', encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", str(tmp_path))
    monkeypatch.setattr(runner, "_venv_python", lambda _root: sys.executable)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    result = runner.run_tests(timeout=30, suite_names=["test_real_assertion"])
    assert result == (0, 1, 0, False)
    logs = list((tmp_path / "logs" / "autocheck").glob("*/test_real_assertion.log"))
    assert len(logs) == 1
    assert "1 failed" in logs[0].read_text(encoding="utf-8")


def test_selected_suites_only(tmp_path, monkeypatch):
    runner = _load_runner()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_passed.py").write_text(
        'if __name__ == "__main__":\n    raise SystemExit(0)\n', encoding="utf-8")
    (tests_dir / "test_unselected.py").write_text(
        'if __name__ == "__main__":\n    raise SystemExit(7)\n', encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", str(tmp_path))
    monkeypatch.setattr(runner, "_venv_python", lambda _root: sys.executable)
    monkeypatch.setattr(runner, "discover_test_suites",
                        lambda: ["test_unselected", "test_passed"])
    assert runner.run_tests(suite_names=["test_passed", "test_passed"]) == (1, 0, 0, False)
    assert not list((tmp_path / "logs" / "autocheck").glob("*/test_unselected.log"))


def test_timeout_ends_descendant_process(tmp_path, monkeypatch):
    import psutil

    runner = _load_runner()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    pid_file = tmp_path / "descendant.pid"
    source = (
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        'if __name__ == "__main__":\n'
        '    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])\n'
        f"    Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "    time.sleep(60)\n"
    )
    (tests_dir / "test_spawns_child.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", str(tmp_path))
    monkeypatch.setattr(runner, "_venv_python", lambda _root: sys.executable)
    assert runner.run_tests(timeout=2, suite_names=["test_spawns_child"]) == (0, 1, 0, False)
    assert pid_file.is_file(), "the child must have started before testing its cleanup"
    child_pid = int(pid_file.read_text())
    assert not psutil.pid_exists(child_pid) or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE


def test_script_harness_stubs_dialogs_and_preserves_local_patches(tmp_path, monkeypatch):
    runner = _load_runner()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_dialog_flow.py").write_text(
        'from PyQt6.QtWidgets import QInputDialog, QMessageBox\n'
        'if __name__ == "__main__":\n'
        '    assert QInputDialog.getItem(None, "test", "platform", []) == ("通用", True)\n'
        '    assert QMessageBox.information(None, "test", "notice") == QMessageBox.StandardButton.Ok\n'
        '    QInputDialog.getItem = staticmethod(lambda *a, **k: ("local override", True))\n'
        '    assert QInputDialog.getItem(None, "test", "platform", []) == ("local override", True)\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "ROOT", str(tmp_path))
    monkeypatch.setattr(runner, "_venv_python", lambda _root: sys.executable)
    assert runner.run_tests(timeout=10, suite_names=["test_dialog_flow"]) == (1, 0, 0, False)
