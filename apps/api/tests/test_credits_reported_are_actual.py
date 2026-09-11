"""调过模型之后报的积分必须是**实扣**，不是事前那个估价。

使用者报过这个 bug，原话：「弹窗显示这次大概花 约 17 分。但实际是冻结 7 积分、
花费 3 积分」。事前只能估（还没调模型，不知道它会写多长），**事后不该再估** ——
网关已经按真实 token 结过账，那个数就在 `completion.billing()` 里。

**两个数不一致会毁掉整个功能的可信度**：页面说「本次 6 分」而余额掉了 3 分，
读的人接下来会怀疑页面上每一个数字，包括那些从年报里读出来的。而读文档这一页
存在的全部理由就是"每个数都能核"。

这条只能在这里守：两个数都是合法的整数，接口 200，测试全绿，
**只有把页面和积分页并排看才会发现**——而那要人去做。
"""

from __future__ import annotations

import ast
import pathlib

MAIN = pathlib.Path(__file__).resolve().parents[1] / "stock_decision" / "main.py"


def _calls_the_model(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) \
                and child.func.id in {"call", "call_tools"}:
            return True
    return False


def _returns_credits_as(node: ast.AST) -> list[tuple[int, str]]:
    """收集这个函数里 `return {..., "credits": X, ...}` 的 X 长什么样。"""
    found: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Return) or not isinstance(child.value, ast.Dict):
            continue
        for key, value in zip(child.value.keys, child.value.values):
            if isinstance(key, ast.Constant) and key.value == "credits":
                found.append((child.lineno, ast.unparse(value)))
    return found


def test_every_endpoint_that_calls_the_model_reports_the_metered_number():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _calls_the_model(node):
            continue
        for lineno, expr in _returns_credits_as(node):
            # `dry_run` 那条分支在调模型之前就返回了，报估价是对的 ——
            # 它的返回里没有回答内容，认得出来：`"credits": cost` 且同一行带 chars。
            if expr == "cost":
                src = MAIN.read_text(encoding="utf-8").splitlines()
                near = "\n".join(src[max(0, lineno - 3):lineno + 1])
                assert "dry_run" in near or "chars" in near, (
                    f"main.py:{lineno} 在 {node.name} 里报的是估价 cost。"
                    f"模型已经调过了，这里要报实扣：charged(completion, cost)。\n{near}")
            checked += 1
    assert checked >= 6, f"只扫到 {checked} 处 credits 返回，这个测试自己瞎了"


def test_charged_prefers_the_metered_number_over_the_quote():
    """没走计量时才退回估价 —— 本地调试没配网关的情况。"""
    from stock_decision.main import charged

    class Fake:
        def __init__(self, billing: dict) -> None:
            self._billing = billing

        def billing(self) -> dict:
            return self._billing

    assert charged(Fake({"metered": True, "credits": 3}), 17) == 3, "实扣 3 就报 3，不报 17"
    assert charged(Fake({"metered": True, "credits": 0}), 17) == 0, "真的没扣就报 0"
    assert charged(Fake({"metered": False}), 17) == 17, "没计量才退回估价"
    assert charged(object(), 17) == 17, "拿不到账单也不许崩"
