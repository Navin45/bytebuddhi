from pathlib import Path

from app.infrastructure.config.log_rotation import rotate_log_file


def test_no_rotation_under_size(tmp_path: Path) -> None:
    log = tmp_path / "gateway.log"
    log.write_text("hello log", encoding="utf-8")
    rotate_log_file(log, max_bytes=1000)
    assert log.exists()
    assert not (tmp_path / "gateway.log.1").exists()


def test_rotation_over_size(tmp_path: Path) -> None:
    log = tmp_path / "gateway.log"
    log.write_text("x" * 200, encoding="utf-8")
    rotate_log_file(log, max_bytes=100, max_files=3)
    assert not log.exists()
    assert (tmp_path / "gateway.log.1").exists()
    assert (tmp_path / "gateway.log.1").read_text(encoding="utf-8") == "x" * 200


def test_rotation_cascades_and_prunes(tmp_path: Path) -> None:
    # Set up existing rotated files .1 and .2
    (tmp_path / "gateway.log.2").write_text("old2", encoding="utf-8")
    (tmp_path / "gateway.log.1").write_text("old1", encoding="utf-8")
    log = tmp_path / "gateway.log"
    log.write_text("current", encoding="utf-8")

    rotate_log_file(log, max_bytes=5, max_files=3)
    # .2 should be deleted because max_files is 3 (so .1, .2 are max backups)
    assert (tmp_path / "gateway.log.1").read_text(encoding="utf-8") == "current"
    assert (tmp_path / "gateway.log.2").read_text(encoding="utf-8") == "old1"
