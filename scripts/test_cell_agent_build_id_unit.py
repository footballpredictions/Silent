"""Улей и сота обязаны отдавать один и тот же agent_build_id."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.hive_provision_service import cell_agent_build_id  # noqa: E402
from app.services import hive_provision_service as provision  # noqa: E402


def _cell_build_id(folder: Path) -> str:
    path = folder / "build_id.py"
    namespace = {"__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace["agent_build_id"](folder)


def _fake_ssh(folder: Path):
    client = Mock()
    sftp = client.open_sftp.return_value
    uploaded: set[str] = set()

    def putfo(stream, remote):
        if remote.startswith("/opt/silent-vpn/cell-agent/"):
            name = remote.rsplit("/", 1)[-1]
            (folder / name).write_bytes(stream.read())
            uploaded.add(name)

    sftp.putfo.side_effect = putfo
    return client, uploaded


def test_upgrade_replaces_old_build_formula_and_missing_modules() -> None:
    """Повторяем реальный баг: старая формула учитывает оставшийся queen_apply.py."""
    for missing_modules in (False, True):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for path in (ROOT / "cell-agent").glob("*.py"):
                (folder / path.name).write_bytes(path.read_bytes())
            build = folder / "build_id.py"
            old = build.read_text(encoding="utf-8").replace(
                '    "main.py",', '    "main.py",\n    "queen_apply.py",',
            )
            build.write_text(old, encoding="utf-8")
            (folder / "queen_apply.py").write_text("# legacy module\n", encoding="utf-8")
            if missing_modules:
                (folder / "standby_online.py").unlink()
                (folder / "status_cache.py").unlink()
            assert _cell_build_id(folder) != cell_agent_build_id()
            client, uploaded = _fake_ssh(folder)
            with ExitStack() as stack:
                stack.enter_context(patch.object(provision, "_ssh_connect", return_value=client))
                stack.enter_context(patch.object(provision, "_ensure_remote_dir"))
                remote_run = stack.enter_context(patch.object(provision, "_run", return_value=(0, "ok", "")))
                provision.upgrade_cell_agent_via_ssh("93.184.216.34", "test-password")
            assert _cell_build_id(folder) == cell_agent_build_id(), "upgrade leaves build mismatch and repeats restart"
            assert {"agent_http.py", "build_id.py", "main.py", "standby_online.py", "standby_runtime.py", "status_cache.py"} <= uploaded
            command = remote_run.call_args.args[1]
            assert "systemctl restart silent-cell-agent" in command
            assert "-m agent_http" in command, "upgrade leaves the unbounded legacy HTTP listener"
            assert "systemctl restart wdtt" not in command
            assert (folder / "queen_apply.py").is_file(), "legacy modules must not be deleted"
            client.close.assert_called_once()


def test_provision_ships_complete_agent_for_first_start() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        client, uploaded = _fake_ssh(folder)
        with ExitStack() as stack:
            stack.enter_context(patch.object(provision, "_ssh_connect", return_value=client))
            stack.enter_context(patch.object(provision, "_ensure_remote_dir"))
            stack.enter_context(patch.object(provision, "_load_wdtt_binary", return_value=b"test-binary"))
            stack.enter_context(patch.object(provision, "_run", return_value=(0, "WG_PUB=" + "a" * 43 + "=\n", "")))
            provision.provision_cell_via_ssh(
                "93.184.216.34", "test-password", cell_agent_secret="test-secret",
                hive_public_ip="93.184.216.35", hive_api_base="http://93.184.216.35:8000",
                wdtt_master_password="test-master", cell_id="test-cell",
            )
        assert {"agent_http.py", "build_id.py", "main.py", "standby_online.py", "standby_runtime.py", "status_cache.py"} <= uploaded
        assert _cell_build_id(folder) == cell_agent_build_id()


def test_missing_source_aborts_before_ssh_or_restart() -> None:
    original_load = provision._load_cell_agent_file

    def load(name):
        if name == "status_cache.py":
            raise RuntimeError("missing status_cache.py")
        return original_load(name)

    with patch.object(provision, "_load_cell_agent_file", side_effect=load), patch.object(provision, "_ssh_connect") as ssh:
        try:
            provision.upgrade_cell_agent_via_ssh("93.184.216.34", "test-password")
        except RuntimeError as error:
            assert "missing status_cache.py" in str(error)
        else:
            raise AssertionError("incomplete agent bundle must not restart running agent")
        ssh.assert_not_called()


def test_same_id_on_hive_and_cell() -> None:
    cell_path = ROOT / "cell-agent" / "build_id.py"
    spec = importlib.util.spec_from_file_location("silent_cell_build_id_test", cell_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hive_id = cell_agent_build_id()
    cell_id = mod.agent_build_id(cell_path.parent)
    assert hive_id == cell_id
    assert len(hive_id) == 16


if __name__ == "__main__":
    test_same_id_on_hive_and_cell()
    test_upgrade_replaces_old_build_formula_and_missing_modules()
    test_provision_ships_complete_agent_for_first_start()
    test_missing_source_aborts_before_ssh_or_restart()
    print("ok")
