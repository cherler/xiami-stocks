"""**接口函数体里用到的名字，导入了没有？** 少一个，那条接口在被调用之前一直是好的。

## 踩到的那一次

2026-08-16：加甘特图时把 `company_timeline` 从 main.py 的导入清单里换成了
`company_schedule`，而现成的 `/timeline` 接口的函数体里还在用前者。

- 模块照常 import（函数体里的名字是调用时才解析的）
- 应用照常启动、路由照常注册、`/health` 照常 200
- **只有真去调 `/api/v1/companies/1/timeline` 的时候才 NameError → 500**

同一场里还差点撞上另一半：新接口的路径也写成了 `/timeline`。
两个同路径的 `@app.get` 不报错，FastAPI 只认先注册的那个 ——
后写的那条接口静悄悄地永远不会被调用。

## 这条守卫查两件事

1. 每个路由处理函数体里引用的全局名字，在 main 的命名空间里都找得到
2. 同一个 (路径, 方法) 不许注册两次

用语法树查，不需要真去调每条接口 —— 那要造几十份夹具数据。
"""

import ast
import builtins
import pathlib

import pytest

from stock_decision import main

API = pathlib.Path(main.__file__)
TREE = ast.parse(API.read_text(encoding="utf-8"))


def _handlers() -> list[ast.FunctionDef]:
    """带 @app.<method>(...) 装饰器的函数。"""
    out = []
    for node in ast.walk(TREE):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            func = deco.func if isinstance(deco, ast.Call) else deco
            if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                    and func.value.id == "app"):
                out.append(node)
                break
    return out


def _args_of(args: ast.arguments) -> set[str]:
    names = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def _local_names(func) -> set[str]:
    """函数自己绑定的名字：参数、赋值、for、with、except、import、嵌套定义。

    **嵌套函数的参数也要算。** 第一版漏了，于是 `post_task_auto_review` 里那个
    内层 `def work(job_id)` 的参数被当成"没导入的全局名"报了出来 ——
    一条只会误报的守卫，比没有守卫更糟：真出问题时它已经被人关掉了。
    """
    names = _args_of(func.args)
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            names |= _args_of(node.args)
        elif isinstance(node, ast.Lambda):
            names |= _args_of(node.args)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.comprehension,)):
            for sub in ast.walk(node.target):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
    return names


def test_the_scan_actually_finds_the_handlers():
    """守卫要先证明自己在工作 —— 一条都扫不到的守卫永远是绿的。"""
    handlers = _handlers()
    assert len(handlers) >= 80, f"只扫到 {len(handlers)} 个路由处理函数，形状变了"
    assert any(f.name == "get_company_schedule" for f in handlers)


def test_every_name_a_route_uses_is_actually_imported():
    """**函数体里的名字是调用时才解析的。**

    导入清单里少一个，模块照常 import、应用照常启动、`/health` 照常 200，
    只有真去调那条接口时才 NameError → 500。
    """
    known = set(vars(main)) | set(dir(builtins))
    missing: list[str] = []
    for func in _handlers():
        local = _local_names(func)
        for node in ast.walk(func):
            if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                continue
            if node.id in local or node.id in known:
                continue
            missing.append(f"  main.py:{node.lineno}  {func.name}() 用了 `{node.id}`，而它没被导入")
    assert not missing, (
        "这些名字在接口函数体里被用到，而 main 的命名空间里没有：\n"
        + "\n".join(sorted(set(missing)))
        + "\n\n  这类错**不会在启动时暴露** —— 只有真去调那条接口时才 500。"
    )


def test_no_two_routes_claim_the_same_path_and_method():
    """**两个同路径同方法的 `@app.get` 不报错**，FastAPI 只认先注册的那个 ——
    后写的那条接口静悄悄地永远不会被调用。加甘特图时差点这么干（`/timeline`）。"""
    seen: dict[tuple[str, str], str] = {}
    clashes: list[str] = []
    for route in main.app.routes:
        for method in getattr(route, "methods", set()) or set():
            key = (getattr(route, "path", ""), method)
            name = getattr(route, "name", "?")
            if key in seen:
                clashes.append(f"  {method} {key[0]} —— {seen[key]}() 和 {name}()")
            else:
                seen[key] = name
    assert not clashes, (
        "这些路径注册了两次，后一个永远不会被调用：\n" + "\n".join(clashes))


@pytest.mark.parametrize("path", ["/api/v1/companies/{company_id}/timeline",
                                  "/api/v1/companies/{company_id}/schedule"])
def test_both_timelines_still_exist(path):
    """一个是估值走势 + 事件时点，一个是承诺与解禁的区间。**两件事，两条路径。**
    合并过一次（同名同路径），结果是后者把前者盖掉了。"""
    assert any(getattr(r, "path", "") == path for r in main.app.routes), f"{path} 没了"
