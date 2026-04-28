from concurrent.futures import ThreadPoolExecutor
import threading
import time

from openbbq.storage import migration_runner


def test_run_schema_migrations_serializes_alembic_commands(tmp_path, monkeypatch):
    active_commands = 0
    max_active_commands = 0
    counter_lock = threading.Lock()
    first_command_started = threading.Event()

    def fake_table_names(_path):
        return set()

    def fake_upgrade(_config, _revision, *, tag):
        nonlocal active_commands, max_active_commands
        assert tag == "project"
        with counter_lock:
            active_commands += 1
            max_active_commands = max(max_active_commands, active_commands)
        first_command_started.set()
        time.sleep(0.05)
        with counter_lock:
            active_commands -= 1

    monkeypatch.setattr(migration_runner, "_table_names", fake_table_names)
    monkeypatch.setattr(migration_runner.command, "upgrade", fake_upgrade)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run_project_migrations, tmp_path / "one.db")
        assert first_command_started.wait(timeout=1)
        second = executor.submit(run_project_migrations, tmp_path / "two.db")
        first.result()
        second.result()

    assert max_active_commands == 1


def run_project_migrations(path):
    migration_runner.run_schema_migrations(path, "project")
