"""按表选对那个数据域过滤函数。

## 这条是线上 500 撞出来的

本仓有两个过滤函数，用错不会在本地被发现：

    _sw()   自己带 user_id 的表（companies、documents…）
    _swc()  挂在 companies 上、自身不带 user_id 的子表（evidences、events…）

我给 evidences 写查询时照抄了 `_sw()`，上线当场
`psycopg2.errors.UndefinedColumn: column "user_id" does not exist`。

**为什么本地测不出来**：测试库里只有一个用户，两个函数在"结果对不对"上
看不出差别；而 SQLite 那边 `evidences` 也确实没有 user_id ——
只是本地的用例没有一条会走到这个新函数。所以这不是"忘了跑测试"，
是**没有任何测试覆盖过这条 SQL**，而它只在真库上才炸。

所以这里用 AST + 表结构对照来查：拼了 `_sw()` 的 SQL，
它查的那张表必须真的有 user_id 列。
"""

from __future__ import annotations

import ast
import pathlib
import re

API = pathlib.Path(__file__).resolve().parents[1] / "stock_decision"


def _tables_with_user_id() -> set[str]:
    """从建表脚本里读出哪些表真的有 user_id 列。"""
    ddl = (API / "database.py").read_text(encoding="utf-8")
    out: set[str] = set()
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n            \);", ddl, re.S):
        if re.search(r"^\s*user_id\s", m.group(2), re.M):
            out.add(m.group(1))
    return out


def test_sw_is_only_used_on_tables_that_have_user_id():
    with_user = _tables_with_user_id()
    assert "companies" in with_user, "读建表脚本失败 —— 这个守卫自己瞎了"
    assert "evidences" not in with_user, "evidences 现在有 user_id 了？那这条守卫要重写"

    source = (API / "repository.py").read_text(encoding="utf-8")
    bad: list[str] = []

    def owner_of(at: int) -> str | None:
        r"""这个 _sw() 挂在哪张表上 —— **按括号深度回扫，拿不准就返回 None。**

        试过两版更简单的写法，都在误报：

          `FROM (\w+).*?\{_sw\(\)\}`  把
              DELETE FROM trades WHERE ... IN (SELECT id FROM portfolios ...{_sw()})
          判成"对 trades 用了 _sw()" —— 而它挂在子查询的 portfolios 上，是对的。

          「往回找最近的 FROM」 把
              SELECT name FROM companies WHERE id NOT IN (SELECT ... FROM theses){_sw()}
          判成 theses —— 而那个子查询已经闭合了，_sw() 属于外层的 companies。

        **一条会喊狼来了的守卫比没有守卫糟**：报错三次之后没人再看它。
        所以这里宁可漏报：深度对不上、或者 SQL 是拼出来的（窗口里没有 FROM），
        一律返回 None 跳过。
        """
        depth = 0
        i = at - 1
        window = max(0, at - 600)
        while i >= window:
            ch = source[i]
            if ch == ")":
                depth += 1
            elif ch == "(":
                if depth == 0:
                    return None       # 走出了当前这层，说不清了
                depth -= 1
            elif depth == 0 and ch in "MmEeOo":
                head = source[max(0, i - 6):i + 1]
                m2 = re.search(r"(?:FROM|UPDATE|INTO)$", head, re.I)
                if m2:
                    tail = re.match(r"\s+(\w+)", source[i + 1:])
                    if tail:
                        return tail.group(1)
            i -= 1
        return None

    for m in re.finditer(r"\{_sw\(\)\}", source):
        table = owner_of(m.start())
        if table and table not in with_user:
            line = source[:m.start()].count("\n") + 1
            bad.append(f"repository.py:{line} 对 {table} 用了 _sw()")
    assert not bad, (
        "这些表没有 user_id，却拼了 _sw()：\n  " + "\n  ".join(bad) +
        "\n挂在公司上的子表要用 _swc()。本地测试库只有一个用户，用错不会红 —— "
        "只有真库上才会 UndefinedColumn。")


def test_the_new_unverify_path_is_scoped_at_all():
    """**别为了绕开上面那条就干脆不过滤。** 不过滤 = 改到别人的数据。"""
    source = (API / "repository.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "unverify_bulk_archived_evidence")
    body = ast.unparse(fn)
    assert "_swc()" in body or "_sw(" in body, (
        "退回存量那条路一个数据域过滤都没有 —— 它会改到别的用户的证据")
