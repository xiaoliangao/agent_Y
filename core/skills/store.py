"""技能存储（渐进披露）。见 docs/design.md §4.6。

约定：`<root>/<name>/SKILL.md`，frontmatter `name/description/when_to_use` + 正文。
**列表只把 (name + 一句话) 放进 system prompt（占预算极小）；命中才由 `use_skill` 工具加载正文。**
这样用户可以「保存」一堆技能，agent 平时只看到简介，真正需要时才把完整步骤拉进上下文。
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field


@dataclass
class Skill:
    name: str
    description: str
    when_to_use: str
    body: str
    path: str = ""   # SKILL.md 路径
    dir: str = ""    # 技能目录（含 SKILL.md + 可能的脚本/资源）
    files: list[str] = field(default_factory=list)  # 目录内其它文件（SKILL.md 除外，如脚本/资源）


def parse_skill_md(text: str) -> tuple[dict, str]:
    """解析 `--- frontmatter ---` + 正文。frontmatter 用简单 `key: value`（够用、无 yaml 依赖）。"""
    fm: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end].strip()
            body = text[end + 4:].lstrip("\n")
            for line in block.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip()
    return fm, body


def _slug(name: str) -> str:
    """安全目录名：保留中英数字与连字符，其余转 -，去越界字符。"""
    s = re.sub(r"[^\w一-鿿-]+", "-", name.strip()).strip("-")
    return s or "skill"


class FileSkillStore:
    def __init__(self, root: str) -> None:
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, name: str) -> str:
        return os.path.join(self.root, name, "SKILL.md")

    def _load(self, name: str) -> Skill | None:
        p = self._path(name)
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as f:
            fm, body = parse_skill_md(f.read())
        d = os.path.dirname(p)
        files: list[str] = []
        for root_, dirs_, fns_ in os.walk(d):
            dirs_[:] = [x for x in dirs_ if not x.startswith(".") and x not in ("__pycache__", "node_modules")]
            for fn in fns_:
                if fn.startswith(".") or (fn == "SKILL.md" and root_ == d):
                    continue
                files.append(os.path.relpath(os.path.join(root_, fn), d))
        files.sort()
        return Skill(
            name=fm.get("name") or name, description=fm.get("description", ""),
            when_to_use=fm.get("when_to_use", ""), body=body.strip(), path=p, dir=d, files=files,
        )

    def list(self) -> list[Skill]:
        if not os.path.isdir(self.root):
            return []
        out: list[Skill] = []
        for name in sorted(os.listdir(self.root)):
            sk = self._load(name)
            if sk:
                out.append(sk)
        return out

    def get(self, name: str) -> Skill | None:
        return self._load(_slug(name)) or self._load(name)

    def add(self, name: str, *, description: str = "", when_to_use: str = "", body: str = "") -> Skill:
        slug = _slug(name)
        os.makedirs(os.path.join(self.root, slug), exist_ok=True)
        content = (
            f"---\nname: {name}\ndescription: {description}\nwhen_to_use: {when_to_use}\n---\n\n{body.strip()}\n"
        )
        with open(self._path(slug), "w", encoding="utf-8") as f:
            f.write(content)
        sk = self._load(slug)
        assert sk is not None
        return sk

    def install(self, src: str) -> Skill:
        """安装一个技能「包」：把含 SKILL.md 的文件夹（或单个 SKILL.md）整体拷进技能库。

        类似 Claude Desktop 装 skill —— 连同里面的脚本/资源一起装好；之后 agent 检测到相关任务，
        会按 SKILL.md 的说明（可引用同目录脚本）自动调用。
        """
        src = os.path.realpath(os.path.expanduser(src.strip()))
        if os.path.isfile(src) and os.path.basename(src) == "SKILL.md":
            src_dir = os.path.dirname(src)
        elif os.path.isdir(src) and os.path.isfile(os.path.join(src, "SKILL.md")):
            src_dir = src
        else:
            raise ValueError("未找到 SKILL.md（请选一个含 SKILL.md 的技能文件夹）")
        with open(os.path.join(src_dir, "SKILL.md"), encoding="utf-8") as f:
            fm, _ = parse_skill_md(f.read())
        slug = _slug(fm.get("name") or os.path.basename(src_dir))
        dest = os.path.join(self.root, slug)
        if os.path.isdir(dest):
            shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(src_dir, dest, ignore=shutil.ignore_patterns(".*", "__pycache__", "node_modules"))
        sk = self._load(slug)
        assert sk is not None
        return sk

    def delete(self, name: str) -> bool:
        d = os.path.join(self.root, _slug(name))
        if not os.path.isdir(d):
            d = os.path.join(self.root, name)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            return True
        return False

    def index(self) -> str:
        """system prompt 用的技能清单（只名字+简介+何时用，渐进披露的"目录")。"""
        items = self.list()
        if not items:
            return ""
        lines = []
        for s in items:
            line = f"- **{s.name}**：{s.description}"
            if s.when_to_use:
                line += f"（何时用：{s.when_to_use}）"
            lines.append(line)
        return "\n".join(lines)
