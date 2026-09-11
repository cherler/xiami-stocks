"""给虾米看股建一个**不绕过 RLS** 的专用数据库角色。

## 为什么需要它

行级安全有一个很容易踩的坑：策略建好了、`ENABLE`/`FORCE` 也开了，
但只要连库的角色带 `BYPASSRLS`（超级用户默认就带，云数据库的主账号通常也带），
**策略一条都不生效，而从应用这边完全看不出来**——查询照常返回，只是返回了所有人的行。

实测：本地 docker 的 `xiamimate` 是超级用户，线上 RDS 的主账号 `rolbypassrls = True`，
两边都是这样。所以必须换一个角色连。

## 为什么让它当属主，而不是只给 DML 权限

本模块自己要建表、加列、装策略（每次启动都跑一遍 initialize_database）。
只给 DML 的话这些全做不了，就得维护两套凭据、两条代码路径。
让它当 `stocks` schema 的属主更简单——而属主默认会绕过自己表上的策略，
这正是 `FORCE ROW LEVEL SECURITY` 存在的意义，代码里已经对每张表都加了 FORCE。

## 用法

    # 本地
    python scripts/setup_rls_role.py --password <给新角色的密码>

    # 线上（在服务器上跑，用当前 .env 里的主账号去建）
    python scripts/setup_rls_role.py --password <密码> --schema stocks

跑完把 .env 的 PG_USER / PG_PASSWORD 换成新角色，重启服务。
主账号仍然保留，用于运维和跨 schema 的操作。
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

ROLE = "xiamimate_stocks"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--password", required=True, help=f"给 {ROLE} 设的密码")
    parser.add_argument("--schema", default=None, help="要移交的 schema，默认取 STOCK_PG_SCHEMA")
    parser.add_argument("--check", action="store_true", help="只看现状，不改")
    args = parser.parse_args()

    os.environ["STOCK_DB_BACKEND"] = "postgres"
    from stock_decision import pgbackend

    schema = args.schema or pgbackend.SCHEMA
    conn = pgbackend.connect()

    current = conn.execute(
        "SELECT current_user AS name, rolsuper, rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user").fetchone()
    print(f"当前连接身份：{current['name']}  "
          f"超级用户={current['rolsuper']}  绕过RLS={current['rolbypassrls']}")

    exists = conn.execute(
        "SELECT rolbypassrls FROM pg_roles WHERE rolname = %s", (ROLE,)).fetchone()
    print(f"目标角色 {ROLE}：{'已存在' if exists else '不存在'}"
          + (f"（绕过RLS={exists['rolbypassrls']}）" if exists else ""))

    owned = conn.execute(
        "SELECT count(*) AS n FROM pg_tables WHERE schemaname = %s AND tableowner = %s",
        (schema, ROLE)).fetchone()["n"]
    total = conn.execute(
        "SELECT count(*) AS n FROM pg_tables WHERE schemaname = %s", (schema,)).fetchone()["n"]
    print(f"schema {schema}：{owned}/{total} 张表已归 {ROLE}")

    if args.check:
        return 0

    dbname = pgbackend.dsn()["dbname"]

    if not exists:
        conn.execute(f"CREATE ROLE {ROLE} LOGIN PASSWORD %s", (args.password,))
    else:
        conn.execute(f"ALTER ROLE {ROLE} PASSWORD %s", (args.password,))
    # 显式关掉，别依赖默认值：这一条就是整个方案成立的前提。
    conn.execute(f"ALTER ROLE {ROLE} NOBYPASSRLS NOSUPERUSER")
    conn.commit()

    # 主账号要能管理这个角色（RDS 上建角色后通常已自动如此，重复授予无害）
    try:
        conn.execute(f"GRANT {ROLE} TO CURRENT_USER")
        conn.commit()
    except Exception:
        conn.rollback()

    conn.execute(f"GRANT CONNECT ON DATABASE {dbname} TO {ROLE}")
    # 首次初始化要自己建 schema（CREATE SCHEMA IF NOT EXISTS），没这条权限起不来。
    conn.execute(f"GRANT CREATE ON DATABASE {dbname} TO {ROLE}")
    conn.execute(f"ALTER SCHEMA {schema} OWNER TO {ROLE}")
    conn.commit()

    tables = [r["tablename"] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = %s", (schema,)).fetchall()]
    for table in tables:
        conn.execute(f"ALTER TABLE {schema}.{table} OWNER TO {ROLE}")
    sequences = [r["sequencename"] for r in conn.execute(
        "SELECT sequencename FROM pg_sequences WHERE schemaname = %s", (schema,)).fetchall()]
    for sequence in sequences:
        conn.execute(f"ALTER SEQUENCE {schema}.{sequence} OWNER TO {ROLE}")
    conn.commit()

    print(f"✅ {len(tables)} 张表、{len(sequences)} 个序列已归 {ROLE}")
    print(f"\n下一步：把 .env 的 PG_USER 改成 {ROLE}、PG_PASSWORD 改成刚才那个密码，重启服务。")
    print("主账号保留不动，运维与跨 schema 操作仍用它。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
