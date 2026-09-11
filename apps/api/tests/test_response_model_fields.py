"""**后端算了、响应模型没声明 —— 那一栏就永远不会出去，而且不报错。**

## 这是本仓复发率最高的一个坑

`schemas.py` 自己的注释记着它被踩过四次；我在这一场里踩了第五次
（`covered_years` / `coverage_note` 算好了、`ValuationWindow` 没声明，
线上显示 undefined），后来又在 `promises_due`、`viewer_is_guest`、
`needs_attention` 三处各钉了一条一次性的断言。

## 为什么它不报错

pydantic 2 的默认是 `extra="ignore"`：

    DashboardSummary(..., 不存在的字段=42)   →  不报错
    model_dump() 里有这个字段吗              →  没有

也就是说构造那一行**照常执行、照常返回**，只是那个值凭空消失了。
页面上的表现是"这一栏永远是 undefined"，而没有任何一层会响。

## 所以不再一条条钉，改成扫

这个文件用语法树把 repository/main 里**所有** `XxxSummary(...)` 这类
构造调用找出来，逐个关键字参数跟模型声明的字段比。
新加一栏而忘了在 schemas 里声明，这里当场红 —— 不需要有人想起来加断言。

## ⚠️ 它只盖得住一半，另一半在 test_response_models.py

这个坑有**两种形状**，只有一种能静态查：

    repository.py:1983  DashboardSummary(..., promises_due=...)   ← 关键字构造，这里能扫
    main.py             response_model=SyncJobStatus              ← 函数返回 dict，扫不到

第二种里模型压根不在源码里被构造（FastAPI 拿它去过滤返回的字典），
返回什么取决于运行时数据 —— 那一半只能靠 `test_response_models.py` 里那份
**手维护的清单**。实测：SyncJobStatus 和 ValuationWindow 在整个源码里
一次都没有被直接构造过，也就是说这个文件对它们完全无能为力。

**两条守卫谁也替不了谁。** 删任何一条之前先回来读这一段。
"""

import ast
import pathlib

import pytest

from stock_decision import schemas

API = pathlib.Path(__file__).resolve().parents[1] / "stock_decision"

# 只查 schemas 里真正的 pydantic 模型
MODELS = {
    name: obj for name, obj in vars(schemas).items()
    if isinstance(obj, type) and hasattr(obj, "model_fields")
}


def _construction_sites() -> list[tuple[str, str, str, int]]:
    """(模型名, 关键字参数, 文件, 行号) —— 源码里每一次带关键字的模型构造。"""
    out: list[tuple[str, str, str, int]] = []
    for path in sorted(API.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                     # noqa: PERF203 —— 解析不了就跳过，不是这条守卫的事
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            model = MODELS.get(node.func.id)
            if model is None:
                continue
            for keyword in node.keywords:
                if keyword.arg is None:         # **kwargs 展开，静态查不了
                    continue
                out.append((node.func.id, keyword.arg, path.name, node.lineno))
    return out


def test_the_scan_actually_finds_something():
    """守卫本身要先证明它在工作 —— 一条都扫不到的守卫永远是绿的。"""
    sites = _construction_sites()
    assert len(sites) >= 20, f"只扫到 {len(sites)} 处模型构造，形状变了，这条守卫要跟着改"
    assert any(m == "DashboardSummary" for m, *_ in sites), "连首页那个都没扫到"


def test_every_constructed_field_is_declared():
    """**传进去而模型没声明的字段会被静静吃掉。**

    pydantic 默认 extra="ignore"：构造那一行照常执行、照常返回，
    只是那个值凭空消失。页面上表现为"这一栏永远是 undefined"，没有任何一层会响。

    **一条测试跑完全部，不做 parametrize。** 拆成一百多个用例会让整套慢
    八十秒（每个用例都要过一遍 conftest 的建库夹具），而它们查的是同一件事；
    真出问题时也应该**一次把缺的都列出来**，而不是修一个跑一次。
    """
    missing = [
        f"  {file}:{line}  {model}.{field}"
        for model, field, file, line in _construction_sites()
        if field not in MODELS[model].model_fields
    ]
    assert not missing, (
        "这些字段传进了模型，而 schemas 里没有声明：\n"
        + "\n".join(missing)
        + "\n\n  pydantic 会**静静吃掉**它们：不报错、不出现在响应里，"
        "\n  页面上只表现为「这一栏永远是 undefined」。"
        "\n  → 去 schemas.py 对应的模型里补上（顺手写一句它是干什么的）。"
    )


def test_the_trap_still_works_the_way_we_think():
    """把前提钉住：哪天 pydantic 改成默认报错，这条会红 ——
    那时候上面那套扫描就可以删了，而不是继续养着。"""
    class Tiny(schemas.BaseModel):  # type: ignore[name-defined]
        a: int = 0

    model = Tiny(a=1, b=2)          # b 没声明
    assert model.model_dump() == {"a": 1}, (
        "pydantic 现在会拒绝未声明的字段了 —— 那这个文件可以删掉。")
