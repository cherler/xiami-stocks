"""SQLite 也要自动补列 —— 不能只有 PG 会。

## 这条是怎么来的

`CREATE TABLE IF NOT EXISTS` 对已存在的表什么都不做，所以往一张已有的表
加列时，光改建表脚本在老库上不会生效。

  PG      `_add_missing_columns()` 拿"应有的列"跟库里实际的列逐个对，自动补
  SQLite  一直**靠人手写** `ALTER TABLE ... ADD COLUMN`：38 条，覆盖 16 张表

忘写不会报错、不会有测试变红，只在某次还原老备份时冒出一句 `no such column`。
**今天加 documents.tags 我就忘了。**

而备份文件永远是 SQLite（见 backup.py），还原代码里写着
「initialize_database()  # 老版本备份恢复后补齐结构」——
那句注释在 PG 上是真的，**在 SQLite 上一直是假的**。

## 实现里踩的两个坑（都写在守卫里，别再踩）

1. 第一版喂 `_SCHEMA_SQL`，结果 documents / document_pages /
   fundraising_projects 一列都没解析出来 —— 它们的建表语句写在
   `_initialize_sqlite` 函数体里的另外几段 executescript 里（全仓四段）。
2. 改成喂 `derive_schema_sql()` 之后当场无限递归 ——
   那个函数内部会调 `_initialize_sqlite()`，而补列正是从那里调的。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("STOCK_TEST_SQLITE", "").lower() not in {"1", "true", "yes", "on"},
    reason="这条只在 SQLite 后端下有意义（PG 那边本来就自动补）")


def _snapshot(connection) -> dict[str, set[str]]:
    with connection() as conn:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: {r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')} for t in tables}


def test_a_missing_column_is_added_back(tmp_path: Path):
    from stock_decision.database import configure_database, connection, initialize_database

    configure_database(tmp_path / "old.db")
    initialize_database()
    before = _snapshot(connection)
    assert "tags" in before["documents"], "新建库本来就该有 tags —— 这个测试自己瞎了"

    # 模拟一份老备份：几张不同的表各缺一列
    missing = [("documents", "tags"), ("companies", "exchange"), ("evidences", "verification")]
    with connection() as conn:
        for table, column in missing:
            conn.execute(f'ALTER TABLE "{table}" DROP COLUMN {column}')
    gone = _snapshot(connection)
    for table, column in missing:
        assert column not in gone[table], f"{table}.{column} 没删掉，测试前提不成立"

    # 还原路径就是靠它补结构
    initialize_database()
    after = _snapshot(connection)
    for table, column in missing:
        assert column in after[table], (
            f"{table}.{column} 没被补回来 —— 还原一份老备份之后会报 no such column")
    # **按列名比，不按顺序。** ALTER ADD COLUMN 只能追加，补回来的列排在末尾；
    # 而全仓没有一条 `INSERT INTO 表 VALUES(...)` 不写列名，备份还原也按列名取。
    assert after == before, "补完之后每张表的列集合应该跟新建库完全一致"


def test_initializing_twice_changes_nothing(tmp_path: Path):
    """**幂等。** 补列跑在每次启动的路径上，第二次不许再动结构。"""
    from stock_decision.database import configure_database, connection, initialize_database

    configure_database(tmp_path / "twice.db")
    initialize_database()
    once = _snapshot(connection)
    initialize_database()
    assert _snapshot(connection) == once


def test_the_backfill_reads_the_derived_schema_not_one_constant():
    """应有的列要从 `derive_schema_sql()` 来。

    喂 `_SCHEMA_SQL` 的话会漏掉三张表 —— 它们的建表语句在别的 executescript 里。
    """
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "stock_decision" / "database.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_sqlite_add_missing_columns")
    body = ast.unparse(fn)
    assert "derive_schema_sql()" in body, (
        "补列的依据不是派生结构 —— 喂 _SCHEMA_SQL 会漏掉 documents 那几张表")
    # 派生那一趟会回调进来，必须有再入保护，否则无限递归
    assert "_DERIVING_SCHEMA" in body, (
        "没有再入保护 —— derive_schema_sql() 内部会调 _initialize_sqlite()，"
        "而补列正是从那里调的，会当场无限递归")
