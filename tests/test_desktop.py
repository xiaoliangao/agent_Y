"""桌面外壳：build_app 构造 + 数据目录覆盖（不起真窗口/真服务，那些需 GUI）。"""
from __future__ import annotations


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTY_DATA", str(tmp_path / "data"))
    from desktop.main import _data_dir

    assert _data_dir() == str(tmp_path / "data")


def test_build_app(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTY_DATA", str(tmp_path / "data"))
    from desktop.main import build_app

    app = build_app()
    assert app.title == "Agent Y"
    assert (tmp_path / "data").exists()  # create_app 已建数据目录


def test_mode_default_and_window(monkeypatch):
    import desktop.main as dm

    monkeypatch.delenv("AGENTY_MODE", raising=False)
    assert dm._mode() == "host"
    monkeypatch.setenv("AGENTY_MODE", "window")
    assert dm._mode() == "window"


def test_window_argv_dev(monkeypatch):
    import sys

    import desktop.main as dm

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert dm._window_argv() == [sys.executable, "-m", "desktop.main"]
