"""网络检索 + 取网页（助手工具，PRD F6.4）。见 docs/design.md §4.6。

web_search：DuckDuckGo HTML（无需 API key）→ 标题/链接/摘要。
web_fetch：取网页 → 转可读文本（带来源 URL）。
均为只读（不走审批）；直接用 httpx 联网（不经沙箱）。结果带来源，供模型核实/引用。
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Callable

import httpx
from pydantic import BaseModel, Field

from core.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
_STRIP = re.compile(r"<[^>]+>")


def _untag(s: str) -> str:
    s = _STRIP.sub("", s)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#x27;", "'"), ("&quot;", '"')):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def parse_ddg(html: str) -> list[tuple[str, str, str]]:
    """从 DuckDuckGo HTML 抽 (标题, 链接, 摘要)。链接是 DDG 跳转，解出真实 url。"""
    titles = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
    out: list[tuple[str, str, str]] = []
    for i, (href, title) in enumerate(titles):
        url = href
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if "uddg" in qs:
            url = qs["uddg"][0]
        snip = _untag(snippets[i]) if i < len(snippets) else ""
        out.append((_untag(title), url, snip))
    return out


def parse_bing(html: str) -> list[tuple[str, str, str]]:
    """从 Bing(cn) HTML 抽 (标题, 链接, 摘要)。国内可直连，作 DDG（常被墙/需代理）的兜底。"""
    out: list[tuple[str, str, str]] = []
    for block in re.findall(r'<li class="b_algo[^"]*"[^>]*>(.*?)</li>', html, re.S):
        m = re.search(r'<h2>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url, title = m.group(1), _untag(m.group(2))
        sm = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        out.append((title, url, _untag(sm.group(1)) if sm else ""))
    return out


def html_to_text(html: str) -> str:
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</(p|div|h[1-6]|li|tr|section|article)>", "\n", html, flags=re.I)
    text = _STRIP.sub("", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(a, b)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


class WebSearchInput(BaseModel):
    query: str = Field(description="搜索关键词")
    max_results: int = Field(default=6, ge=1, le=15)


class WebSearchTool(BaseTool):
    """网络检索：返回相关网页的标题 + 链接 + 摘要（结果带来源，便于核实/引用）。"""

    name = "web_search"
    input_model = WebSearchInput

    def is_read_only(self, inp: WebSearchInput) -> bool:
        return True

    async def validate_input(self, inp: WebSearchInput, ctx: ToolContext) -> ValidationResult:
        if not inp.query.strip():
            return ValidationResult(ok=False, message="query 不能为空")
        return ValidationResult(ok=True)

    async def call(self, inp: WebSearchInput, ctx: ToolContext, on_progress: Callable) -> ToolResult:
        headers = {"User-Agent": _UA}
        results: list[tuple[str, str, str]] = []
        try:  # 首选 DuckDuckGo
            async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as c:
                r = await c.post("https://html.duckduckgo.com/html/", data={"q": inp.query})
            results = parse_ddg(r.text)
        except Exception:  # noqa: BLE001
            results = []
        if not results:  # DDG 不可用（被墙 / 打包后无代理）→ 退到 Bing（国内可直连）
            try:
                async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as c:
                    r = await c.get("https://cn.bing.com/search", params={"q": inp.query, "setlang": "zh-CN"})
                results = parse_bing(r.text)
            except Exception:  # noqa: BLE001
                results = []
        results = results[: inp.max_results]
        if not results:
            return ToolResult(data=f"没有找到 '{inp.query}' 的结果（搜索引擎暂时不可用）。")
        return ToolResult(data="\n\n".join(f"{i + 1}. {t}\n   {u}\n   {s}" for i, (t, u, s) in enumerate(results)))


class WebFetchInput(BaseModel):
    url: str = Field(description="要抓取的网页 URL")
    max_chars: int = Field(default=6000, ge=500, le=40000)


class WebFetchTool(BaseTool):
    """抓取一个网页并转成可读文本（带来源 URL），用于阅读/总结。"""

    name = "web_fetch"
    input_model = WebFetchInput

    def is_read_only(self, inp: WebFetchInput) -> bool:
        return True

    async def validate_input(self, inp: WebFetchInput, ctx: ToolContext) -> ValidationResult:
        if not inp.url.startswith(("http://", "https://")):
            return ValidationResult(ok=False, message="url 需以 http(s):// 开头")
        return ValidationResult(ok=True)

    async def call(self, inp: WebFetchInput, ctx: ToolContext, on_progress: Callable) -> ToolResult:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": _UA}) as c:
            r = await c.get(inp.url)
        text = html_to_text(r.text)[: inp.max_chars]
        return ToolResult(data=f"# 来源: {inp.url}\n\n{text}")
