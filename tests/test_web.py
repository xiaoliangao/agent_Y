"""web 工具的解析器（纯函数，不依赖真网络）+ 工具标志。"""
from __future__ import annotations

from core.tools.web import (
    WebFetchInput,
    WebFetchTool,
    WebSearchInput,
    WebSearchTool,
    html_to_text,
    parse_bing,
    parse_ddg,
)


def test_parse_bing():
    html = (
        '<li class="b_algo"><h2><a href="https://e.com/x">标题A</a></h2><div><p>摘要A</p></div></li>'
        '<li class="b_algo b_algoBig"><h2><a href="https://e.com/y" h="ID">B 标题</a></h2><p>snip B</p></li>'
    )
    rows = parse_bing(html)
    assert rows[0] == ("标题A", "https://e.com/x", "摘要A")
    assert rows[1][0] == "B 标题" and rows[1][1] == "https://e.com/y"


def test_parse_ddg_extracts_title_url_snippet():
    html = '''
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=x">示例 <b>标题</b></a>
      <a class="result__snippet" href="x">这是一段 <b>摘要</b> 文本</a>
    </div>'''
    out = parse_ddg(html)
    assert out[0][0] == "示例 标题"
    assert out[0][1] == "https://example.com/a"  # 解出真实 url
    assert "摘要" in out[0][2]


def test_html_to_text_strips_tags_and_scripts():
    html = "<html><head><style>x{}</style></head><body><h1>标题</h1><script>bad()</script><p>正文一</p><p>正文二</p></body></html>"
    t = html_to_text(html)
    assert "标题" in t and "正文一" in t and "正文二" in t
    assert "bad()" not in t and "x{}" not in t


async def test_web_tools_are_read_only():
    assert WebSearchTool().is_read_only(WebSearchInput(query="x")) is True
    assert WebFetchTool().is_read_only(WebFetchInput(url="https://x.com")) is True


async def test_web_fetch_validates_url(tmp_path):
    from tests.helpers import make_ctx

    vr = await WebFetchTool().validate_input(WebFetchInput(url="ftp://x"), make_ctx(tmp_path))
    assert vr.ok is False
    ok = await WebFetchTool().validate_input(WebFetchInput(url="https://x.com"), make_ctx(tmp_path))
    assert ok.ok is True
