"""把本地 SQLite 库整体搬进虾米伙伴主站库的 stocks schema。

**逐表搬，逐表核对条数。** 搬完不核对等于没搬 —— 少了一张表、少了一半行，
在页面上看起来只是"数据怎么少了点"，而那时原库可能已经被当成旧文件删掉了。
所以这里每张表都打印 源→目标 的条数，任何一处对不上就整体判失败。

**搬之前不删目标表的数据**（除非 --replace）：默认是"往空库里搬"，
目标表非空就停下来问，不给"以为在补数据、其实在灌重复"的机会。

用法：
    python scripts/migrate_to_pg.py --check        只看两边条数，不写
    python scripts/migrate_to_pg.py                空库搬迁
    python scripts/migrate_to_pg.py --replace      先清空目标表再搬（重跑用）
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from stock_decision import database, pgbackend  # noqa: E402

# 有外键指向别人的表要后搬、先清。
#
# **不能只按 sqlite_master 顺序**：它是建表顺序，而 v30 的隔离迁移把 companies 等
# 七张表原地重建过——重建的表排到了末尾，于是 theses 会先于 companies 被搬，
# PG 的外键当场拒收。父表用显式优先序钉死，其余仍按原顺序。
_PARENTS_FIRST = ("companies", "theses", "portfolios", "research_tasks")


def ordered_tables(conn) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
    ).fetchall()
    names = [r["name"] for r in rows]
    return [t for t in _PARENTS_FIRST if t in names] + [t for t in names if t not in _PARENTS_FIRST]


def columns_of(conn, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只比对条数，不写入")
    parser.add_argument("--replace", action="store_true", help="先清空目标表（重跑用）")
    parser.add_argument("--source", default=None, help="源 SQLite 文件，默认取 var/stock_decision.db")
    args = parser.parse_args()

    source = Path(args.source) if args.source else database.database_path()
    if not source.exists():
        print(f"找不到源库：{source}")
        return 1
    print(f"源：{source}")
    print(f"目标：{pgbackend.dsn()['host']}:{pgbackend.dsn()['port']}/"
          f"{pgbackend.dsn()['dbname']} · schema {pgbackend.SCHEMA}\n")

    lite = database.sqlite_connection(source)
    tables = ordered_tables(lite)

    # 目标结构必须已存在（由 initialize_database 建）
    os.environ["STOCK_DB_BACKEND"] = "postgres"
    pg = pgbackend.connect()

    def pg_count(table: str) -> int:
        row = pg.execute(f"SELECT count(*) AS c FROM {pgbackend.SCHEMA}.{table}").fetchone()
        return int(row["c"])

    if args.check:
        bad = 0
        for table in tables:
            src = int(lite.execute(f"SELECT count(*) AS c FROM {table}").fetchone()["c"])
            try:
                dst = pg_count(table)
            except Exception as exc:
                print(f"  ❌ {table:<32} 目标表读不到：{exc}")
                pg.rollback()
                bad += 1
                continue
            mark = "✅" if src == dst else "❌"
            if src != dst:
                bad += 1
            print(f"  {mark} {table:<32} 源 {src:>7} → 目标 {dst:>7}")
        print("\n" + ("两边一致 ✅" if bad == 0 else f"{bad} 张表不一致 ❌"))
        return 0 if bad == 0 else 1

    if args.replace:
        # 反序 TRUNCATE：先清指向别人的那些。CASCADE 会连带清掉引用行，
        # 这正是我们要的（整体重灌），但因此绝不能对生产库随手跑。
        print("清空目标表…")
        for table in reversed(tables):
            pg.execute(f"TRUNCATE {pgbackend.SCHEMA}.{table} CASCADE")
        pg.commit()
    else:
        nonempty = [t for t in tables if pg_count(t) > 0]
        if nonempty:
            print(f"目标里这些表已经有数据：{'、'.join(nonempty)}")
            print("默认只往空库搬，避免灌成重复。确要重灌请加 --replace。")
            return 1

    total = 0
    for table in tables:
        cols = columns_of(lite, table)
        rows = lite.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
        if rows:
            placeholders = ", ".join(["%s"] * len(cols))
            sql = (f"INSERT INTO {pgbackend.SCHEMA}.{table} ({', '.join(cols)}) "
                   f"VALUES ({placeholders})")
            # 走原始游标：这条 SQL 已经是 PG 方言，不需要再翻译
            with pg._raw.cursor() as cur:
                cur.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
        # 自增序列要跟着最大 id 走，否则下一次 INSERT 会撞主键
        if "id" in cols and rows:
            pg.execute(
                f"SELECT setval(pg_get_serial_sequence('{pgbackend.SCHEMA}.{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {pgbackend.SCHEMA}.{table}), 1))")
        pg.commit()
        dst = pg_count(table)
        mark = "✅" if dst == len(rows) else "❌"
        print(f"  {mark} {table:<32} {len(rows):>7} 行 → 目标 {dst:>7}")
        if dst != len(rows):
            print("     条数对不上，停在这里。")
            return 1
        total += len(rows)

    print(f"\n共搬迁 {total} 行，逐表条数一致 ✅")
    print("现在把 .env 里的 STOCK_DB_BACKEND 改成 postgres 即可切过去。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
