"""文件夹授权 + realpath 前缀校验。见 docs/design.md §5.2、PRD F6。

助手文件操作**绝不给整机访问**：用户显式授权目录白名单 + realpath 前缀校验
（解析符号链接后比对，挡 `..` 与软链越界）。授权列表持久化到 JSON。
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Literal

Mode = Literal["read_only", "read_write"]


def _is_within(path: Path, base: Path) -> bool:
    if path == base:
        return True
    try:
        return path.is_relative_to(base)  # py3.9+
    except AttributeError:  # pragma: no cover
        return str(path).startswith(str(base) + os.sep)


class FolderAccess:
    def __init__(self, store_path: str | None = None) -> None:
        self._store_path = store_path
        self._folders: dict[str, dict] = {}  # id -> {id, path, mode}
        self._load()

    def _load(self) -> None:
        if self._store_path and os.path.exists(self._store_path):
            try:
                data = json.loads(Path(self._store_path).read_text(encoding="utf-8"))
                self._folders = {f["id"]: f for f in data}
            except Exception:
                self._folders = {}

    def _save(self) -> None:
        if self._store_path:
            Path(self._store_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self._store_path).write_text(
                json.dumps(list(self._folders.values()), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def authorize(self, path: str, mode: Mode = "read_write") -> dict:
        real = str(Path(path).expanduser().resolve())
        for f in self._folders.values():  # 同 realpath 去重
            if f["path"] == real:
                f["mode"] = mode
                self._save()
                return f
        rec = {"id": "fold_" + uuid.uuid4().hex[:10], "path": real, "mode": mode}
        self._folders[rec["id"]] = rec
        self._save()
        return rec

    def revoke(self, folder_id: str) -> bool:
        if folder_id in self._folders:
            del self._folders[folder_id]
            self._save()
            return True
        return False

    def list(self) -> list[dict]:
        return list(self._folders.values())

    def resolve(self, path: str, *, need_write: bool = False, must_exist: bool = False) -> Path:
        """解析 path 为 realpath 并校验落在某授权目录内；越界/越权 → PermissionError。"""
        real = Path(path).expanduser().resolve()  # strict=False：不存在也尽量解析(挡软链)
        for f in self._folders.values():
            if _is_within(real, Path(f["path"])):
                if need_write and f["mode"] == "read_only":
                    raise PermissionError(f"目录为只读，不可写：{path}")
                if must_exist and not real.exists():
                    raise FileNotFoundError(path)
                return real
        raise PermissionError(f"路径未在授权目录内：{path}")
