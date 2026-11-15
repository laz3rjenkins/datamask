import os
import time

from datamask.core.session import UNLOCKED_GRACE_SECONDS, Session, cleanup_stale


def test_session_dir_is_private(tmp_path) -> None:
    s = Session.create(tmp_path / "base")
    try:
        assert s.path.stat().st_mode & 0o777 == 0o700
        assert (tmp_path / "base").stat().st_mode & 0o077 == 0
    finally:
        s.close()


def test_close_removes_everything(tmp_path) -> None:
    base = tmp_path / "base"
    s = Session.create(base)
    (s.path / "f.csv").write_text("x")
    s.close()
    assert list(base.iterdir()) == []


def test_cleanup_stale(tmp_path) -> None:
    base = tmp_path / "base"
    live = Session.create(base)

    dead_with_lock = base / "dead1"
    dead_with_lock.mkdir()
    (base / "dead1.lock").touch()  # никто не держит блокировку

    old_without_lock = base / "dead2"
    old_without_lock.mkdir()
    old = time.time() - UNLOCKED_GRACE_SECONDS - 1
    os.utime(old_without_lock, (old, old))

    young_without_lock = base / "starting"
    young_without_lock.mkdir()

    (base / "orphan.lock").touch()

    assert cleanup_stale(base) == 2
    names = {p.name for p in base.iterdir()}
    assert names == {live.path.name, live.path.name + ".lock", "starting"}
    live.close()
