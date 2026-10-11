"""本地研究库的备份、恢复与导出。

设计取舍：备份用 SQLite 自带的 backup API 做整库一致性拷贝，而不是复制文件；
恢复前一定先给当前库做一次安全备份，避免一次误操作抹掉不可再生的研究记录。
"""

import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .database import (
    SCHEMA_VERSION,
    connection,
    database_path,
    initialize_database,
    is_postgres,
    schema_version,
)
from . import pgbackend

BACKUP_SUFFIX = ".db"
MANIFEST_SUFFIX = ".json"

# 用户手写、或者要他逐条确认过才成立的记录；导出以它们为主。
#
# ## 2026-08-15：这张表少了十几张，而页面上写着「你手写的记录」
#
# 备份不受影响（SQLite 是整库副本、PG 走 pg_dump，两者都是全量）。
# 出问题的是**导出的那份 JSON**：它自称「你自己录入的研究记录」，
# 页面上还跟着一句「只包含你手写的记录与版本历史，来源数据不在其中」——
# 读起来是"少的只有能重新同步的东西"。
#
# 而线上这个账号当时的实际情况是：
#
#     产业链节点 231、边 148、阶段 67、主题 14   一条都没导
#     产业链条目（逐条确认过的）21              一条都没导
#     方法论自评 8、订阅源 7、分级纠正 2         一条都没导
#     研究报告 1（花钱生成的）、研究待办 5       一条都没导
#
# 承诺台账、复核记录、我的估值当时是 0 行，所以没显出来，但同样不在里面。
# **这些没有一样能重新同步回来。** 拿这份 JSON 当存档的人，丢的正是他手写的东西。
#
# 所以下面拆成两张明确的名单：导的、和不导的（各自写明理由）。
# test_export_completeness.py 会拿真实 schema 逐张比对——
# **新加一张用户表却两张名单都没进，测试就红**，逼人做一次决定，
# 而不是像这次一样静静地漏了十几张。
AUTHORED_TABLES = (
    "companies",
    "theses",
    "evidences",
    "research_events",
    "portfolios",
    "trades",
    "record_revisions",
    # ↓ 2026-08-15 补上的。上面七张是最早那一版，之后加的功能一张都没跟上。
    # 读进来的文件。**页也要一起导** —— 只导元信息的话，还原之后是一份
    # 问不了的文件列表；而原始 PDF 未必还在他手上（贴链接读的那些尤其）。
    "documents",
    "document_pages",
    # 募投进度：从专项报告里读出来的，重新读一次要再花钱，所以要导。
    "fundraising_projects",
    "thesis_reviews",            # 每次复核写下的结论
    "valuations",                # 我的估值：三情景假设
    "management_promises",       # 承诺台账，每条都要人确认才入账
    "counter_hits",              # 反证命中，连同「我处理过了」的状态
    "supply_chain_links",        # 产业链条目，逐条确认过
    "research_reports",          # 研究报告：重跑要再花钱，而且资料会变
    "research_tasks",
    "research_task_items",
    "industry_chain_themes",
    "industry_chain_stages",
    "industry_chain_nodes",
    "industry_chain_edges",
    "industry_chain_company_positions",
    "method_assessments",        # 方法论自评
    "screen_strategies",         # 自建的选股策略
    "rule_terms",                # 你教给分级器的词
    "inbox_corrections",         # 你纠正过的分级——教过一次的东西
    "news_feeds",                # 自己加的订阅源
    "user_settings",             # 偏好
    # 决策闭环。**卡片上的价格带与仓位计划全是手写的**，而且状态推进日志
    # 是"我当时怎么想的"唯一的记录——重新同步一万次也拿不回来。
    "decision_cards",
    "decision_transitions",
    # 成交登记。**重新同步一万次也拿不回来**：它记的是你真实的成交价和日期，
    # 而且是「计划内 / 计划外」唯一的原料——丢了它，整段纪律史就没了。
    "decision_fills",
    # 助手里的原话、修订回执、偏好和提醒条件不能靠重新同步找回。
    "assistant_actions",
    "assistant_memory",
    "assistant_subscriptions",
    "assistant_web_messages",
)

# **明确不导的用户表，各写一条理由。**
#
# 「不导」必须是一个被写下来的决定，不能是"忘了加"——这两件事在代码里
# 长得一模一样，而后者正是上面那十几张表的来历。
NOT_EXPORTED = {
    "assistant_cloud_jobs": "云端任务调度流水，聊天原文另行导出",
    "assistant_cloud_accounts": "飞书绑定凭据不得进入个人研究导出",
    "assistant_cloud_budget": "服务用量限制台账，不是研究内容",
    "background_jobs": "后台任务流水，重跑就有",
    "news_items": "抓回来的资讯，重抓就有",
    "daily_briefings": "每日简报，可以重新生成",
    "screen_runs": "选股的运行流水，不是你写的东西",
    "candidate_review_runs": "候选复核的运行流水",
    "candidate_review_targets": "候选复核的目标清单，跟着上面那条走",
    "assistant_watch_state": "助理盯盘的「在不在区间里」，下一轮盯盘就重新算出来",
    "assistant_alerts": "助理发过的提醒流水，里面的数都来自决策卡和行情，不是你写的东西",
    "assistant_watch_runs": "助理每一轮盯盘的运行记录",
}

# 自己带 user_id 的表 vs 挂在 company_id 上的子表。
# 判法跟 repository 里的 _sw / _swc 是同一套。
_SCOPED_BY_USER = frozenset({
    "companies", "portfolios", "valuations", "management_promises", "counter_hits",
    "decision_cards",
    "research_tasks", "method_assessments", "screen_strategies", "rule_terms",
    "inbox_corrections", "news_feeds", "user_settings", "documents",
    "fundraising_projects",
    "assistant_actions", "assistant_memory", "assistant_subscriptions", "assistant_web_messages",
    "industry_chain_themes", "industry_chain_stages", "industry_chain_nodes",
    "industry_chain_edges", "industry_chain_company_positions",
})
_SCOPED_BY_COMPANY = frozenset({
    "theses", "evidences", "research_events", "trades",
    "thesis_reviews", "supply_chain_links", "research_reports",
    "decision_transitions", "decision_fills",
})

# 可以重新同步回来的来源数据；只统计条目数，不进入 JSON 导出。
SOURCE_TABLES = (
    "market_snapshots",
    "price_bars",
    "financial_periods",
    "valuation_points",
    "company_profiles",
    "company_calendar_events",
    # 公告正文。**是来源数据不是你的东西**：丢了重新抓一遍就有，
    # 而它比其他几张都大（一份正文几千字），塞进 JSON 导出只会让备份变笨重。
    "announcement_texts",
    "provider_syncs",
    # 产业链环节的同行：从 earth-atlas 重导一次就有，不是手写的东西。
    "chain_segment_members",
)


class BackupError(RuntimeError):
    pass


def backup_dir() -> Path:
    return database_path().parent / "backups"


def _existing_tables(conn, sqlite_file: bool = False) -> set[str]:
    """两个后端问同一个问题的两种问法。

    sqlite_file=True 时强制走 SQLite 问法：备份**文件**永远是 SQLite，
    与当前后端无关——PG 模式下清点一个 .db 备份文件，拿 pg_tables 去问
    sqlite3 连接会当场崩（实测踩过）。
    """
    if is_postgres() and not sqlite_file:
        rows = conn.execute(
            "SELECT tablename AS name FROM pg_tables WHERE schemaname = %s", (pgbackend.SCHEMA,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def table_columns(conn, table: str) -> set[str]:
    """这张表有哪几列。两个后端问法不同，问题是同一个。"""
    if is_postgres():
        rows = conn.execute(
            "SELECT column_name AS name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s", (pgbackend.SCHEMA, table)).fetchall()
        return {row["name"] for row in rows}
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _has_id(conn, table: str) -> bool:
    return "id" in table_columns(conn, table)


def _table_counts(conn, sqlite_file: bool = False) -> dict[str, int]:
    existing = _existing_tables(conn, sqlite_file=sqlite_file)
    counts: dict[str, int] = {}
    for table in (*AUTHORED_TABLES, *SOURCE_TABLES):
        if table in existing:
            counts[table] = int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
    return counts


def _counts_of(path: Path) -> tuple[dict[str, int], int]:
    # 要设超时：没有 manifest 的备份文件每次列表都会被打开清点，
    # 两个进程同时读时裸 connect 会立刻抛 database is locked（间歇性 500，极难复现）。
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        # 备份文件永远是 SQLite，与当前后端无关
        return _table_counts(conn, sqlite_file=True), int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def local_data_summary() -> dict[str, Any]:
    path = database_path()
    with connection() as conn:
        counts = _table_counts(conn)
        version = schema_version(conn)
    backups = list_backups()
    if is_postgres():
        params = pgbackend.dsn()
        where = f"{params['host']}:{params['port']}/{params['dbname']} · schema {pgbackend.SCHEMA}"
        size = 0            # 库是共享的，报「本模块占多少」需要另算，先如实给 0 而不是给个错的数
    else:
        where = str(path)
        size = path.stat().st_size if path.exists() else 0
    # 「代码在写但库里没有」的列。**这一项要跟条目数并排显示**：
    # 表里 102 期财报、5535 只股票，数量看着很齐全，缺的是列——
    # 而列缺了不会报错，只会让下游判断悄悄失去依据。
    from .freshness import check as freshness_check

    try:
        freshness = freshness_check()
    except Exception:
        freshness = {"stale": False, "findings": [], "actions": [], "note": "检查未能完成"}

    return {
        "freshness": freshness,
        "database_path": where,
        "database_size": size,
        "schema_version": version,
        "expected_schema_version": SCHEMA_VERSION,
        "authored_counts": {table: counts.get(table, 0) for table in AUTHORED_TABLES},
        "source_counts": {table: counts.get(table, 0) for table in SOURCE_TABLES},
        "backup_count": len(backups),
        "latest_backup_at": backups[0]["created_at"] if backups else None,
        "backup_directory": str(backup_dir()),
    }


def create_backup(note: str = "", reason: str = "手动备份") -> dict[str, Any]:
    """整库一致性备份。

    SQLite 走自带的 backup API（而不是复制文件——写到一半的文件复制出来是坏的）；
    PostgreSQL 走 pg_dump，只导 stocks schema：主站的 app schema 不归本模块管，
    连它一起备份等于把别人的用户数据拷进本模块的备份目录。
    """
    if is_postgres():
        return _create_backup_pg(note, reason)
    source = database_path()
    if not source.exists():
        raise BackupError("本地数据库尚未建立，无法备份")
    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now().replace(microsecond=0)
    name = f"stock_decision-{created_at.strftime('%Y%m%d-%H%M%S')}"
    target = directory / f"{name}{BACKUP_SUFFIX}"
    index = 1
    while target.exists():
        index += 1
        name = f"stock_decision-{created_at.strftime('%Y%m%d-%H%M%S')}-{index}"
        target = directory / f"{name}{BACKUP_SUFFIX}"

    with connection() as src:
        destination = sqlite3.connect(target)
        try:
            src.backup(destination)
        finally:
            destination.close()

    counts, version = _counts_of(target)
    manifest = {
        "name": name,
        "created_at": created_at.isoformat(),
        "schema_version": version,
        "size": target.stat().st_size,
        "note": note.strip(),
        "reason": reason,
        "counts": counts,
    }
    (directory / f"{name}{MANIFEST_SUFFIX}").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _pg_binary(name: str) -> str:
    """挑一个大版本和服务端一致的 pg_dump / psql。

    **不能只信 PATH。** Ubuntu 的 pg_wrapper 会把 `pg_dump` 指向"默认集群"的版本：
    服务器上明明装了 client 16，`pg_dump --version` 报的还是 14，于是备份照旧失败，
    而现象是"我装了啊，怎么还不行"。所以先按版本号直接找二进制，找不到再退回 PATH。
    """
    try:
        server = _server_major()
    except Exception:
        return name
    candidates = [
        f"/usr/lib/postgresql/{server}/bin/{name}",              # Debian / Ubuntu
        f"/opt/homebrew/opt/postgresql@{server}/bin/{name}",     # macOS arm
        f"/usr/local/opt/postgresql@{server}/bin/{name}",        # macOS intel
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return name


def _client_major(binary: str) -> int | None:
    import re
    import subprocess

    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    m = re.search(r"(\d+)\.", out.stdout or "")
    return int(m.group(1)) if m else None


def _server_major() -> int:
    with connection() as conn:
        return int(conn.execute("SHOW server_version_num").fetchone()["server_version_num"]) // 10000


def _require_matching_client(binary: str) -> None:
    """pg_dump / psql 的大版本必须和服务端一致，不一致就别开始。

    **这是「备份看起来成功、真要用的时候才发现用不了」的经典来源。**
    两个方向都会坏，而且坏法不一样：

    · 客户端旧于服务端：pg_dump 直接拒绝跑（线上就是这样——服务器上是 14，
      RDS 是 16，于是线上一份备份都没建成，而页面上看不出来）。
    · 客户端新于服务端：dump 能生成，但里面带着老服务端不认的 SET（实测是
      `transaction_timeout`），要还原的时候才报错——那时你正指望这份备份。

    所以在动手之前就挡住，并说清楚该装哪个包。
    """
    client = _client_major(binary)
    if client is None:
        raise BackupError(
            f"找不到 {binary} —— PostgreSQL 后端的备份需要 postgresql-client。")
    server = _server_major()
    if client != server:
        raise BackupError(
            f"{binary} 是 {client} 版，数据库是 {server} 版，大版本必须一致才能备份/还原。"
            f"请安装 postgresql-client-{server}（否则备份要么建不出来，要么建出来还不回去）。")


def _create_backup_pg(note: str, reason: str) -> dict[str, Any]:
    import subprocess

    pg_dump_bin = _pg_binary("pg_dump")
    _require_matching_client(pg_dump_bin)
    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now().replace(microsecond=0)
    name = f"stock_decision-{created_at.strftime('%Y%m%d-%H%M%S')}"
    target = directory / f"{name}.sql"
    index = 1
    while target.exists():
        index += 1
        name = f"stock_decision-{created_at.strftime('%Y%m%d-%H%M%S')}-{index}"
        target = directory / f"{name}.sql"

    # 用管理员凭据：开了行级安全之后，应用角色只看得见当前数据域的行，
    # pg_dump 出来的自然也只有那一份 —— 备份成功、大小正常、内容残缺，
    # 而这种坏法要等到真去恢复的那天才会发现。
    params = pgbackend.admin_dsn()
    env = {**os.environ, "PGPASSWORD": params["password"]}
    command = [
        pg_dump_bin, "-h", params["host"], "-p", str(params["port"]),
        "-U", params["user"], "-d", params["dbname"],
        "--schema", pgbackend.SCHEMA, "--no-owner", "--no-privileges",
        "-f", str(target),
    ]
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=600)
    except FileNotFoundError as exc:
        raise BackupError("找不到 pg_dump —— PostgreSQL 后端的备份要装 postgresql-client。") from exc
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        raise BackupError(f"pg_dump 失败：{result.stderr.strip()[:300]}")

    with connection() as conn:
        counts = _table_counts(conn)
    manifest = {
        "name": name,
        "created_at": created_at.isoformat(),
        "schema_version": SCHEMA_VERSION,
        "size": target.stat().st_size,
        "note": note.strip(),
        "reason": reason,
        "counts": counts,
        "backend": "postgres",
    }
    (directory / f"{name}{MANIFEST_SUFFIX}").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


# 两种后端产出两种文件：SQLite 是 .db 整库副本，PG 是 pg_dump 出来的 .sql。
PG_BACKUP_SUFFIX = ".sql"


def _data_path(name: str) -> Path | None:
    """找这个备份名对应的数据文件，两种后缀都认。"""
    directory = backup_dir()
    for suffix in (BACKUP_SUFFIX, PG_BACKUP_SUFFIX):
        candidate = directory / f"{name}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _backend_of(path: Path) -> str:
    return "postgres" if path.suffix == PG_BACKUP_SUFFIX else "sqlite"


def list_backups() -> list[dict[str, Any]]:
    """列出目录里的全部备份。

    **以数据文件为准枚举，而不是只 glob 一种后缀。** 之前这里只找 `.db`，
    于是 PG 后端建出来的 `.sql` 备份一个都看不见——而列表里照样列着迁移前
    留下的旧 SQLite 文件。结果是页面显示"你有两份备份"，其实一份都不是当前
    后端的、也一份都还原不了。备份功能坏成这样还显示正常，比直接报错更危险。
    """
    directory = backup_dir()
    if not directory.exists():
        return []
    paths = sorted(
        [*directory.glob(f"*{BACKUP_SUFFIX}"), *directory.glob(f"*{PG_BACKUP_SUFFIX}")],
        reverse=True)
    backups: list[dict[str, Any]] = []
    for path in paths:
        manifest_path = path.with_suffix(MANIFEST_SUFFIX)
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        elif path.suffix == BACKUP_SUFFIX:
            # 手工放进目录的 SQLite 备份也要能看到，条目数直接从文件里读。
            counts, version = _counts_of(path)
            manifest = {
                "name": path.stem,
                "created_at": datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat(),
                "schema_version": version,
                "size": path.stat().st_size,
                "note": "",
                "reason": "外部文件",
                "counts": counts,
            }
        else:
            # .sql 是纯文本，读不出条目数，不猜。
            manifest = {
                "name": path.stem,
                "created_at": datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat(),
                "schema_version": SCHEMA_VERSION,
                "size": path.stat().st_size,
                "note": "",
                "reason": "外部文件",
                "counts": {},
            }
        manifest["size"] = path.stat().st_size
        manifest["backend"] = manifest.get("backend") or _backend_of(path)
        # 当前后端还不还得了它。列表里说清楚，比点下去才报错好。
        manifest["restorable"] = manifest["backend"] == ("postgres" if is_postgres() else "sqlite")
        backups.append(manifest)
    backups.sort(key=lambda item: item["created_at"], reverse=True)
    return backups


def backup_file(name: str) -> Path:
    if "/" in name or "\\" in name or name.startswith("."):
        raise BackupError("备份名称不合法")
    path = _data_path(name)
    if path is None:
        raise BackupError(f"未找到备份 {name}")
    return path


def restore_backup(name: str) -> dict[str, Any]:
    path = backup_file(name)

    # **不允许跨后端还原。** .db 是 SQLite 整库副本，.sql 是 pg_dump 文本，
    # 两者互相灌不进去。以前这里没检查，PG 模式下会走到 shutil.copy2，
    # 把一个 .sql 文本盖到 SQLite 文件路径上——库当场废掉，而且是在
    # 「恢复数据」这个动作里废的，正是最不该出事的地方。
    source_backend = _backend_of(path)
    current_backend = "postgres" if is_postgres() else "sqlite"
    if source_backend != current_backend:
        raise BackupError(
            f"这份备份是 {source_backend} 的，当前后端是 {current_backend}，不能直接还原。"
            "跨后端要走迁移脚本，不是还原。")

    if is_postgres():
        return _restore_backup_pg(name, path)

    backup_counts, backup_version = _counts_of(path)
    if backup_version > SCHEMA_VERSION:
        raise BackupError(f"备份的结构版本 {backup_version} 高于当前程序支持的 {SCHEMA_VERSION}，请先升级程序再恢复")

    with connection() as conn:
        before_counts = _table_counts(conn)
    safety = create_backup(note=f"恢复 {name} 前的自动备份", reason="恢复前自动备份")

    target = database_path()
    for suffix in ("-wal", "-shm"):
        stale = target.with_name(target.name + suffix)
        if stale.exists():
            stale.unlink()
    shutil.copy2(path, target)
    initialize_database()  # 老版本备份恢复后补齐结构

    with connection() as conn:
        after_counts = _table_counts(conn)
        after_version = schema_version(conn)
    mismatched = {
        table: {"backup": backup_counts.get(table, 0), "restored": after_counts.get(table, 0)}
        for table in backup_counts
        if backup_counts.get(table, 0) != after_counts.get(table, 0)
    }
    return {
        "restored_from": name,
        "safety_backup": safety["name"],
        "schema_version": after_version,
        "before_counts": before_counts,
        "restored_counts": after_counts,
        "mismatched": mismatched,
        "verified": not mismatched,
    }


def _reclaim_ownership() -> None:
    """把 schema 与表的属主交还给应用连库用的那个角色。

    **不做这一步，每还原一次就把服务弄坏一次。** 还原是拿管理员账号跑 psql
    （应用角色受行级安全限制，dump 不到全量），而 pg_dump 的脚本里带着
    CREATE SCHEMA —— 重建出来的 schema 归执行者所有，应用角色连 USAGE 都没有，
    下一次查询直接 permission denied。

    实测踩过：线上还原完，服务还“活着”、/health 也是 ok（它只读系统表），
    但任何一次真实查询都报权限不足。**健康检查不碰业务表就发现不了这种坏**。
    """
    import subprocess

    app_user = dsn_user()
    admin = pgbackend.admin_dsn()
    if app_user == admin["user"]:
        return                      # 没分离账号，本来就没这个问题

    psql_bin = _pg_binary("psql")
    env = {**os.environ, "PGPASSWORD": admin["password"]}
    base = ["-h", admin["host"], "-p", str(admin["port"]),
            "-U", admin["user"], "-d", admin["dbname"], "-v", "ON_ERROR_STOP=1"]
    script = f"""
        ALTER SCHEMA {pgbackend.SCHEMA} OWNER TO {app_user};
        DO $$ DECLARE r record; BEGIN
          FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = '{pgbackend.SCHEMA}' LOOP
            EXECUTE format('ALTER TABLE {pgbackend.SCHEMA}.%I OWNER TO {app_user}', r.tablename);
          END LOOP;
          FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname = '{pgbackend.SCHEMA}' LOOP
            EXECUTE format('ALTER SEQUENCE {pgbackend.SCHEMA}.%I OWNER TO {app_user}', r.sequencename);
          END LOOP;
        END $$;
    """
    result = subprocess.run([psql_bin, *base, "-c", script],
                            env=env, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise BackupError(
            "还原完成，但属主没能交还给应用角色，服务会读不到数据。"
            f"手动跑一次 scripts/setup_rls_role.py 可修复。原因：{result.stderr.strip()[:200]}")


def dsn_user() -> str:
    return pgbackend.dsn()["user"]


def _restore_backup_pg(name: str, path: Path) -> dict[str, Any]:
    """用 pg_dump 出来的 .sql 覆盖回 stocks schema。

    先做安全备份再动手：这个动作会 DROP 整个 schema，做错了没有回头路。
    安全备份失败就整个中止——没有退路的操作不该在没有退路的情况下执行。
    """
    import subprocess

    psql_bin = _pg_binary("psql")
    _require_matching_client(psql_bin)
    with connection() as conn:
        before_counts = _table_counts(conn)

    safety = create_backup(note=f"恢复 {name} 前的自动备份", reason="恢复前自动备份")

    # 用管理员凭据：开了行级安全之后，应用角色只看得见当前数据域的行，
    # pg_dump 出来的自然也只有那一份 —— 备份成功、大小正常、内容残缺，
    # 而这种坏法要等到真去恢复的那天才会发现。
    params = pgbackend.admin_dsn()
    env = {**os.environ, "PGPASSWORD": params["password"]}
    base = ["-h", params["host"], "-p", str(params["port"]),
            "-U", params["user"], "-d", params["dbname"]]

    # pg_dump 出来的文件里带 CREATE SCHEMA，所以先把旧的整个拿掉。
    drop = subprocess.run(
        [psql_bin, *base, "-v", "ON_ERROR_STOP=1", "-c",
         f"DROP SCHEMA IF EXISTS {pgbackend.SCHEMA} CASCADE"],
        env=env, capture_output=True, text=True, timeout=120)
    if drop.returncode != 0:
        raise BackupError(f"清空 schema 失败，已中止（安全备份 {safety['name']} 仍在）："
                          f"{drop.stderr.strip()[:300]}")

    load = subprocess.run(
        [psql_bin, *base, "-v", "ON_ERROR_STOP=1", "-f", str(path)],
        env=env, capture_output=True, text=True, timeout=900)
    if load.returncode != 0:
        raise BackupError(f"还原失败（安全备份 {safety['name']} 仍在，可用它退回）："
                          f"{load.stderr.strip()[:300]}")

    _reclaim_ownership()    # 还原会把属主换成执行还原的账号，得交还回去
    initialize_database()   # 老版本备份还原后补齐结构

    with connection() as conn:
        after_counts = _table_counts(conn)
        after_version = schema_version(conn)

    manifest_path = backup_dir() / f"{name}{MANIFEST_SUFFIX}"
    expected = {}
    if manifest_path.exists():
        expected = json.loads(manifest_path.read_text(encoding="utf-8")).get("counts") or {}
    mismatched = {
        table: {"backup": expected.get(table, 0), "restored": after_counts.get(table, 0)}
        for table in expected
        if expected.get(table, 0) != after_counts.get(table, 0)
    }
    return {
        "restored_from": name,
        "safety_backup": safety["name"],
        "schema_version": after_version,
        "before_counts": before_counts,
        "restored_counts": after_counts,
        "mismatched": mismatched,
        # 没有 manifest 就没有比对基准；这时不能报 True，那是"没验"不是"验过了"。
        "verified": bool(expected) and not mismatched,
    }


# 导出时每张表怎么限定成"我的那份"。
#
# **这个映射必须齐全**：漏一张表就是把别人的记录一起导出去，而且导出成功、
# 看起来一切正常。所以下面加了断言，宁可启动就报错，也不要静悄悄多给。
#
# companies / portfolios 自己带 user_id；其余是挂在它们下面的子表，
# 靠外键回溯（这跟 repository 里 _sw/_swc 的判法是同一套）。
def _export_filter(table: str) -> str:
    from .repository import _sw, _swc

    if table in _SCOPED_BY_USER:
        return f" WHERE 1=1{_sw()}"
    if table in _SCOPED_BY_COMPANY:
        return f" WHERE 1=1{_swc('company_id')}"
    if table == "research_task_items":
        # **不能按 company_id 过滤。** 这张表的 company_id 可空，而空的恰恰是
        # 还没建档的候选——也就是这张待办清单上大多数还没做的那几行。
        # 按它过滤等于"只导出已经做完的"。挂到它所属的研究任务上。
        return f" WHERE task_id IN (SELECT id FROM research_tasks WHERE 1=1{_sw()})"
    if table == "document_pages":
        # 页挂在文件上，文件才有 user_id。**不能按 company_id 回溯** ——
        # documents.company_id 可空（读一份还没建档的公司的研报是常事），
        # 按它过滤等于只导出已经归了公司的那些。
        return f" WHERE document_id IN (SELECT id FROM documents WHERE 1=1{_sw()})"
    if table == "record_revisions":
        # 通用修订日志，按 entity_type 分别回溯到各自的主体。
        # 出现新的 entity_type 而这里没跟上，结果是**多导**，不是少导——
        # 所以用白名单：不认识的类型一条都不导。
        thesis_scope = f"(entity_type = 'thesis' AND entity_id IN (SELECT id FROM theses WHERE 1=1{_swc('company_id')}))"
        trade_scope = f"(entity_type = 'trade' AND entity_id IN (SELECT id FROM trades WHERE 1=1{_swc('company_id')}))"
        return f" WHERE ({thesis_scope} OR {trade_scope})"
    raise AssertionError(f"导出表 {table} 没有对应的数据域过滤，拒绝导出以免泄漏他人记录")


def export_records() -> dict[str, Any]:
    """导出**当前用户自己**手写的研究记录。

    行情、财务、公告等来源数据可以重新同步，不进入导出，只报条目数。

    **每张表都要按数据域过滤。** 此前这里是 `SELECT * FROM {table}` 一把梭，
    也就是谁调它都能拿到全站的公司档案、投资逻辑和交易流水。在只对站主开放的
    姿态下看不出问题，但运营台上那个开关一勾就是多用户模式——实测过：
    用 user-7 的身份调用，导出的公司里有站主的票。
    """

    payload: dict[str, Any] = {
        "exported_at": datetime.now().replace(microsecond=0).isoformat(),
        "schema_version": schema_version(),
        # **这句话要跟 AUTHORED_TABLES / NOT_EXPORTED 说的是同一件事。**
        # 原来只说"来源数据未包含"，读起来是"少的只有能重新同步的东西"——
        # 而当时产业链、承诺台账、复核记录、我的估值一条都不在里面。
        "scope": ("你写的那些：公司、判断、证据、事件、交易、复核、估值、承诺、产业链、"
                  "研究报告、词表与偏好，连同版本历史。"
                  "行情、日线、财务、公司简况、公告等来源数据未包含（可重新同步）；"
                  "任务流水、每日简报、选股与复核的运行记录也未包含（重跑就有）。"),
        "records": {},
    }
    with connection() as conn:
        # 用 _existing_tables 而不是自己写一遍 sqlite_master：
        # PG 上没有 sqlite_master，直接 UndefinedTable，整个导出 500。
        existing = _existing_tables(conn)
        for table in AUTHORED_TABLES:
            if table not in existing:
                continue
            # **不是每张表都有 id。** user_settings 的主键是 (user_id, key)，
            # 一句写死的 ORDER BY id 会让整个导出 500 —— 而"导出坏了"这件事
            # 恰恰要等到他真的需要这份存档的那天才会知道。
            order = " ORDER BY id" if _has_id(conn, table) else ""
            rows = [dict(row) for row in conn.execute(
                f"SELECT * FROM {table}{_export_filter(table)}{order}").fetchall()]
            payload["records"][table] = rows
        # 来源数据只报条目数。它们不按用户分（全市场行情谁看都一样），照旧全量统计。
        payload["source_counts"] = {table: int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]) for table in SOURCE_TABLES if table in existing}
    payload["counts"] = {table: len(rows) for table, rows in payload["records"].items()}
    return payload
