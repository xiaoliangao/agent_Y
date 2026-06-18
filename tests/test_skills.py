"""技能：frontmatter 解析 / 存储 CRUD / 索引 / use_skill 工具（渐进披露）。见 design.md §4.6。"""
from __future__ import annotations

from core.skills.store import FileSkillStore, parse_skill_md
from core.tools.skill import UseSkillInput, UseSkillTool


def test_parse_skill_md():
    fm, body = parse_skill_md("---\nname: x\ndescription: d\nwhen_to_use: w\n---\n\nhello body")
    assert fm["name"] == "x" and fm["description"] == "d" and fm["when_to_use"] == "w"
    assert body.strip() == "hello body"
    fm2, body2 = parse_skill_md("no frontmatter")
    assert fm2 == {} and body2 == "no frontmatter"


def test_store_crud_and_index(tmp_path):
    st = FileSkillStore(str(tmp_path / "skills"))
    assert st.list() == []
    sk = st.add("PDF 提取", description="从 PDF 取文本", when_to_use="给 PDF 要读时", body="步骤一二三")
    assert sk.name == "PDF 提取" and sk.body == "步骤一二三"
    assert len(st.list()) == 1
    got = st.get("PDF 提取")
    assert got is not None and got.body == "步骤一二三"
    idx = st.index()
    assert "PDF 提取" in idx and "从 PDF 取文本" in idx and "何时用" in idx
    assert st.delete("PDF 提取") and st.list() == []
    assert not st.delete("nope")


async def test_use_skill_tool(tmp_path):
    st = FileSkillStore(str(tmp_path / "skills"))
    st.add("greet", description="打招呼", body="先说你好再问需求")
    tool = UseSkillTool(st)
    res = await tool.call(UseSkillInput(name="greet"), None, lambda *a: None)
    assert "先说你好再问需求" in str(res.data) and "greet" in str(res.data)
    miss = await tool.call(UseSkillInput(name="nope"), None, lambda *a: None)
    assert "没有名为" in str(miss.data)
