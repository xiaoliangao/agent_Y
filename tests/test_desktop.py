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
