"""模型跑在请求里的路由，前端必须给它长超时。

## 为什么要有这条

前端的超时是一张**手工维护的路径子串表**（apps/web/src/api.ts 的 SLOW_PATHS）：
默认 20 秒，命中表里的走 240 秒。20 秒是按"本地一条 SQL + 一次外部行情"给的，
而模型调用动辄几十秒。表里漏一条，用户点下去就是「请求超时，稍后再试」。

2026-08-18 线上撞到：「自动整理收件箱」（POST /api/v1/inbox/tidy）不在表里，
它一次要跑五批模型分级 —— 必然超时，而且这个按钮从上线起就没成功过。
顺着查出同一类的还有三条。

所以这里从**后端的真实调用图**出发：每个路由处理函数能不能走到 `llm.call`。
名单写死在下面，新增一条会红，逼人回去看前端那张表。

前端那一侧由 apps/web/src/api.timeout.test.ts 用**真的 timeoutFor** 验档位 ——
这里不重新实现一遍它的匹配规则，那样测的就是我对它的印象了。
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "stock_decision"

# 模型跑在**请求里**、因此前端必须给长超时的路由。
#
# 不含返回 BackgroundJob 的那些：它们把活丢给后台任务，请求本身立刻返回，
# 前端是轮询进度，20 秒够用。
SYNCHRONOUS_MODEL_ROUTES = {
    "POST /api/v1/companies/{company_id}/evidence-direction",
    "POST /api/v1/counter-hits/check",
    "POST /api/v1/inbox/classify",
    "POST /api/v1/inbox/tidy",
    "POST /api/v1/companies/{company_id}/assessment",
    "POST /api/v1/value-candidates",
}


def _analyse() -> set[str]:
    """按模块和作用域建调用图，返回「模型跑在请求里」的路由。

    两处踩过的坑，别改回去：
    · 只看 `ast.Call` 会漏掉 `asyncio.to_thread(tidy_inbox, x)` —— 那里函数是
      **参数**不是调用。所以被引用的名字也算边。
    · 函数名不能只按模块存：main.py 里有一堆同名的嵌套 `def work`，
      并成一个节点之后，建档接口会"走到"简报的模型调用（假阳性）。
    """
    defs: dict[tuple[str, str], set[str]] = {}
    imports: dict[str, dict[str, str]] = collections.defaultdict(dict)
    defined_in: dict[str, set[str]] = collections.defaultdict(set)
    routes: list[tuple[str, str, str, bool]] = []

    def scan(mod: str, node: ast.AST, prefix: str) -> None:
        names: set[str] = set()
        nested: list[ast.AST] = []

        def walk(current: ast.AST) -> None:
            for child in ast.iter_child_nodes(current):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nested.append(child)
                    continue
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    names.add(child.id)
                elif isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                    names.add(f"{child.value.id}.{child.attr}")
                walk(child)

        walk(node)
        qual = f"{prefix}.{node.name}" if prefix else node.name  # type: ignore[attr-defined]
        defs[(mod, qual)] = names
        if not prefix:
            defined_in[node.name].add(mod)  # type: ignore[attr-defined]
        for child in nested:
            scan(mod, child, qual)

    for path in sorted(PKG.glob("*.py")):
        mod = path.stem
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                src = node.module.split(".")[-1]
                for alias in node.names:
                    imports[mod][alias.asname or alias.name] = src
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            scan(mod, node, "")
            if mod != "main":
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app"
                        and dec.args and isinstance(dec.args[0], ast.Constant)):
                    continue
                returns = ast.unparse(node.returns) if node.returns else ""
                background = "BackgroundJob" in returns or "BackgroundJob" in ast.unparse(dec)
                routes.append((dec.func.attr.upper(), dec.args[0].value, node.name, background))

    def resolve(mod: str, qual: str, name: str):
        if name == "llm.call":
            return "LLM"
        if "." in name:
            head, attr = name.split(".", 1)
            src = imports[mod].get(head, head)
            return (src, attr) if (src, attr) in defs else None
        scope = qual
        while scope:
            if (mod, f"{scope}.{name}") in defs:
                return (mod, f"{scope}.{name}")
            scope = scope.rsplit(".", 1)[0] if "." in scope else ""
        if (mod, name) in defs:
            return (mod, name)
        src = imports[mod].get(name)
        if src and (src, name) in defs:
            return (src, name)
        owners = defined_in.get(name, set())
        return (next(iter(owners)), name) if len(owners) == 1 else None

    def reaches_model(start: tuple[str, str]) -> bool:
        queue, seen = collections.deque([start]), {start}
        while queue:
            mod, qual = queue.popleft()
            for name in defs.get((mod, qual), ()):
                nxt = resolve(mod, qual, name)
                if nxt == "LLM":
                    return True
                if nxt and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return False

    return {
        f"{method} {path}"
        for method, path, handler, background in routes
        if not background and reaches_model(("main", handler))
    }


def test_没有新的模型路由被漏掉() -> None:
    found = _analyse()
    added = found - SYNCHRONOUS_MODEL_ROUTES
    assert not added, (
        "这几条路由的模型调用跑在请求里，前端默认只给 20 秒，点下去会超时：\n  "
        + "\n  ".join(sorted(added))
        + "\n\n把它们加进 apps/web/src/api.ts 的 SLOW_PATHS 或 SLOW_POST_ROUTES，"
          "再补进本文件的 SYNCHRONOUS_MODEL_ROUTES。"
    )


def test_名单里没有已经不存在的路由() -> None:
    """删掉的路由要从名单里去掉，否则名单会慢慢变成一份没人信的旧账。"""
    found = _analyse()
    gone = SYNCHRONOUS_MODEL_ROUTES - found
    assert not gone, "名单里这几条已经不再调模型（或路由没了），删掉：\n  " + "\n  ".join(sorted(gone))


def test_分析本身认得出报过错的那一条() -> None:
    """守卫要是把 inbox/tidy 也漏了，它就一点用都没有。"""
    assert "POST /api/v1/inbox/tidy" in _analyse()


def test_不把丢后台的路由算成慢请求() -> None:
    """返回 BackgroundJob 的接口请求本身很快，算进来会让前端白等四分钟。"""
    found = _analyse()
    assert "POST /api/v1/briefing" not in found
    assert "POST /api/v1/value-candidates/review" not in found
