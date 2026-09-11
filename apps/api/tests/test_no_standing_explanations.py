"""读文档那几屏上**不许常驻解释文字**。

## 使用者说过不止一次

  - 「删掉『用一句话选股』按钮里的解释文字『花积分』…草说了多少次就不听，
     不要加多余的解释文字」
  - 「解释一次还不行，还解释了两次，你是有多怕用户知道要花钱还是怎么」
  - 「你去掉这句不必要的解释」

这一轮删掉的四句（前三句在页面上真的显示着，第四句前端从来没渲染过、是死的）：

  1. 文件列表底下：「解析在本地做，不花积分；问答按命中的页数计费…」
     —— 讲的是我们内部分了几步，而且读起来像"读文档不花钱"，
     跟结果里的「本次 4 分」自相矛盾。我改写了一遍，他说去掉。
  2. 结果底下：「按…的清单读的，只用了上面那几页原文；每条后面的页码可以翻回去核；
     没找到的那几条也列出来了」—— **三件事全都摆在屏幕上看得见**，
     等于把界面又念了一遍。
  3. 追问底下：「回答只用了上面那几页的原文」—— 而 note 里就写着
     「从 N 页里挑了 M 页喂进去（第 …页）」，就在它上面一行。
  4. 抽募投底下：那句 boundary 前端从来没渲染过。

## 为什么用测试守

这类文字**加起来毫无阻力**：写的时候每一句都显得"对使用者负责"，
而它们的共同点是"替一个还没发生的疑问辩解"，代价是每一屏都被占掉几行。
价钱在结果里如实报一次（「本次 N 分」）就够了。
"""

from __future__ import annotations

import ast
import pathlib

MAIN = pathlib.Path(__file__).resolve().parents[1] / "stock_decision" / "main.py"

# 读文档那几个接口。它们的返回里不许再出现 boundary。
DOC_ROUTES = (
    "get_documents",
    "post_document_digest",
    "post_document_ask",
    "post_document_fundraising",
)


def _returned_keys(fn: ast.AST) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
    return keys


def test_the_document_routes_carry_no_standing_explanation():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in DOC_ROUTES:
            continue
        checked += 1
        keys = _returned_keys(node)
        assert "boundary" not in keys, (
            f"{node.name} 又开始返回 boundary 了。"
            f"那是一句常驻在页面上的解释 —— 使用者说过不止一次「不要加多余的解释文字」。"
            f"要说的话在结果里说一次（「本次 N 分」），不要占每一屏的版面。")
    assert checked == len(DOC_ROUTES), (
        f"只扫到 {checked} 个接口，少了的那个改了名 —— 这个守卫自己瞎了")


def test_the_pricing_is_reported_once_in_the_result_not_explained_up_front():
    """价钱**在结果里报一次**就够了：`credits` 还在，解释没了。

    这两件事要一起守：光删解释、结果里也不报，就成了偷偷扣分。

    ## 第一版这条是瞎的

    第一版查的是「函数里某处返回过 credits」。而 `post_document_digest` 有两条
    返回路径（写完的、被截断的），把其中一条的 credits 删掉照样绿 ——
    破坏验证时正是这么发现的。要查的是**调过模型之后的每一条返回**：
    模型一调，钱就花掉了，那之后任何一条出口都得报。
    """
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    for name in ("post_document_digest", "post_document_ask", "post_document_fundraising"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        called_at = min((node.lineno for node in ast.walk(fn)
                         if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                         and node.func.id in {"call", "call_tools"}), default=0)
        assert called_at, f"{name} 里找不到调模型那一行 —— 这个守卫自己瞎了"
        after = [node for node in ast.walk(fn)
                 if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
                 and node.lineno > called_at]
        assert after, f"{name} 在调模型之后没有任何返回 —— 不可能"
        for node in after:
            keys = {key.value for key in node.value.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            assert "credits" in keys, (
                f"{name} 在 main.py:{node.lineno} 这条出口上不报花了多少分。"
                f"模型已经调过了，钱花掉了 —— 不报就是偷偷扣。")


def test_no_leftover_render_of_a_boundary_on_that_page():
    """前端也不许留着渲染它的分支 —— 留着就是等下一个人再填上。"""
    page = (pathlib.Path(__file__).resolve().parents[3]
            / "apps" / "web" / "src" / "components" / "Documents.tsx")
    text = page.read_text(encoding="utf-8")
    assert "boundary" not in text, "Documents.tsx 里还留着 boundary 的渲染分支"
