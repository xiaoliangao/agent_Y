"""F5.1 diff 审阅：RecordingSandbox 记录改动 + file_change 帧 diff 计算。"""
from __future__ import annotations

from core.sandbox.local import LocalExecutor
from core.sandbox.recording import RecordingSandbox


async def test_recording_sandbox_records_old_and_new(tmp_path):
    (tmp_path / "a.txt").write_text("old line\n")
    sb = RecordingSandbox(LocalExecutor(str(tmp_path)))
    await sb.write_files({"a.txt": b"new line\n"})    # 改已有
    await sb.write_files({"b.txt": b"created\n"})      # 新建
    assert sb.changes["a.txt"] == {"old": "old line\n", "new": "new line\n"}
    assert sb.changes["b.txt"]["old"] == "" and sb.changes["b.txt"]["new"] == "created\n"
    await sb.write_files({"a.txt": b"newer\n"})         # 多次写：old 保最早
    assert sb.changes["a.txt"]["old"] == "old line\n" and sb.changes["a.txt"]["new"] == "newer\n"
    assert await sb.read_file("a.txt") == b"newer\n"    # 实际写入


def test_file_change_frames_diff():
    from server.app import _file_change_frames

    class FakeSb:
        changes = {"x.py": {"old": "a\nb\n", "new": "a\nc\n"}, "same.txt": {"old": "z", "new": "z"}}

    frames = _file_change_frames(FakeSb())
    assert len(frames) == 1  # same.txt 无变化跳过
    assert frames[0]["path"] == "x.py"
    assert "-b" in frames[0]["diff"] and "+c" in frames[0]["diff"]
    assert frames[0]["old"] == "a\nb\n"
