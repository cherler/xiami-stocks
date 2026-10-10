"""模型写到一半被掐断，要说出来，**不许 500，也不许存半份**。

## 这条是撞出来的

带表格的读文档上线后第一次重读研报，线上直接 500。日志里是
`stock_decision.jsonio.Truncated` 从 `post_document_digest` 一路冒到 uvicorn ——
**我给「输出没成形」写好了页面提示（`structured: false` 那一支），
却没让后端走得到那条路。** 这个仓里另外七个调用模型的地方全都显式接了
Truncated（deep_report / drafting / devils_advocate /
industry_chain_draft / promises / evidence_polarity），
只有读文档这两个接口没接。

## 为什么必须是 200 + 一句话，而不是 500

500 在页面上是「请求失败」—— 读的人的合理结论是"这个功能坏了"，
而实际情况是"这次写太长了，再点一次就好"。两种结论会让他做完全不同的事。

## 为什么不许存

`loads_lenient` 拒绝给没写完的 JSON 补外层括号，理由写在 jsonio 里：
补上就成了一段完美合法的 JSON，**而最后没写完的那几条被静静地丢掉了**。
同样的道理，半份结果一旦进了 digest 字段就成了缓存 —— 重开还是它，
而它看起来跟一份完整的结果一模一样。募投那边更贵：少一个项目，
甘特图上少一条泳道，跟"这次发行只有四个项目"分不出来。
"""

from __future__ import annotations

import ast
import pathlib

MAIN = pathlib.Path(__file__).resolve().parents[1] / "stock_decision" / "main.py"

# 读文档这两个接口：它们都用 loads_lenient 解模型输出
ENDPOINTS = ("post_document_digest", "post_document_fundraising")


def _func(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"main.py 里找不到 {name} —— 这个测试自己瞎了")


def _parse_calls_are_guarded(fn: ast.FunctionDef) -> list[str]:
    """返回没被 try/except Truncated 包住的 loads_lenient 调用（报行号）。"""
    guarded: set[int] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        catches = any(
            (isinstance(h.type, ast.Name) and h.type.id == "Truncated")
            or (isinstance(h.type, ast.Tuple)
                and any(isinstance(e, ast.Name) and e.id == "Truncated" for e in h.type.elts))
            for h in node.handlers)
        if not catches:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) \
                    and child.func.id in {"loads_lenient", "loads_or_reformat"}:
                guarded.add(child.lineno)

    naked: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in {"loads_lenient", "loads_or_reformat"} \
                and node.lineno not in guarded:
            naked.append(f"main.py:{node.lineno}")
    return naked


def test_document_endpoints_catch_truncated():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    for name in ENDPOINTS:
        fn = _func(tree, name)
        naked = _parse_calls_are_guarded(fn)
        assert not naked, (
            f"{name} 里的 {'、'.join(naked)} 没被 `except Truncated` 包住。"
            f"模型写到一半时它会抛异常，一路冒出去就是 500「请求失败」——"
            f"而实际情况是「这次写太长了，再点一次」。")


def test_a_truncated_digest_is_not_saved():
    """**掐断的结果不许进 digest 字段。** 存了就成了缓存，重开还是那半份。

    判据：`except Truncated` 那一支里不许出现 save_digest / save_fundraising。
    """
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    for name in ENDPOINTS:
        fn = _func(tree, name)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if not (isinstance(handler.type, ast.Name) and handler.type.id == "Truncated"):
                    continue
                for child in ast.walk(handler):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                        assert not child.func.id.startswith("save_"), (
                            f"{name} 在 Truncated 分支里调了 {child.func.id}() —— "
                            f"半份结果一旦存下来就成了缓存，重开还是它，"
                            f"而它看起来跟一份完整的结果一模一样。")


def test_the_digest_ceiling_is_high_enough_for_tables():
    """**光抬上限不是解法，但上限也确实不能太低。**

    实测：6000 token 的时候模型写到 2638 个中文字被掐断 —— MiniMax 的中文
    大约 2 token 一个字。十条清单项各带结论、数字和表格，三千字打不住。
    提示词那头同时限量（最多三张表、每张最多八行），两头都要有。
    """
    from stock_decision import documents as doc
    from stock_decision.main import DIGEST_MAX_TOKENS

    assert DIGEST_MAX_TOKENS >= 12_000, (
        f"上限 {DIGEST_MAX_TOKENS} 太低 —— 6000 那次实测在 2638 字就断了")
    # 只抬上限的话，模型会把多出来的额度全用掉，下次照样断
    assert "最多三张表" in doc.DIGEST_SYSTEM_PROMPT
    assert "每张最多八行" in doc.DIGEST_SYSTEM_PROMPT
    assert "原表还有" in doc.DIGEST_SYSTEM_PROMPT, "砍掉的行要报数，不能悄悄少几行"
