"""数据层。默认单文件 SQLite，可切到虾米伙伴主站库的 stocks schema。

**为什么两个后端都留着。** 这是个人研究工作台，「一个文件、拷走就能带走」是它的本分；
接进平台是为了共享账号与积分，不是为了从此离不开一台 PostgreSQL。
`STOCK_DB_BACKEND=postgres` 切过去，两条路跑的是同一套 SQL（翻译见 pgbackend.py）。

**PG 的表结构不另写一份。** 建表脚本只有下面这一份 SQLite 版；PG 初始化时先把它
在内存 SQLite 里跑一遍（连同下面那串 ALTER 迁移），再把跑出来的最终结构翻译成 PG DDL。
手写第二份的话，哪天有人加了列却只加在迁移阶梯里，PG 那边就静静地少一列 ——
这种漂移要等到线上报 UndefinedColumn 才发现。派生出来的东西不会漂。
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from . import pgbackend

logger = logging.getLogger(__name__)

_default_path = Path(__file__).resolve().parents[3] / "var" / "stock_decision.db"
_database_path = Path(os.getenv("XIAMI_STOCK_DB", _default_path)).resolve()

# 结构版本随每次表结构变更递增；备份文件会记录它，恢复时用于判断兼容性。
SCHEMA_VERSION = 59


def backend() -> str:
    """postgres（默认）或 sqlite。环境变量优先，其次仓根 .env。

    **默认改成 PostgreSQL 是刻意的。** 线上跑的是 PG，而默认值一旦是 SQLite，
    本地和测试就会长期跑在另一个数据库上——今天为止已经因此漏了四个只在 PG 上
    才炸的 bug（INSERT OR REPLACE、row[0]、HAVING 引用别名、sqlite_master），
    每一个都是「本地全绿、上服务器才炸」。

    更要紧的是：**行级安全只有 PG 有**。跑在 SQLite 上时数据隔离全靠应用层那
    一百零一处过滤，漏一处就是静默泄漏——那正是我们刚从数据库层解决掉的问题。
    默认走 SQLite 等于默认放弃这层保护。

    SQLite 仍然保留，但只作为**建表结构的定义方式**（derive_schema_sql 在内存库里
    跑完整条迁移阶梯再 dump 出 PG 的 DDL，这样两边结构不会漂），不再是推荐的运行后端。
    """
    from . import llm

    configured = os.getenv("STOCK_DB_BACKEND") or llm.load_env().get("STOCK_DB_BACKEND") or "postgres"
    return "postgres" if configured.lower().startswith("p") else "sqlite"


def is_postgres() -> bool:
    return backend() == "postgres"


def configure_database(path: Path) -> None:
    """Override the database path for isolated tests."""

    global _database_path
    _database_path = path.resolve()


def database_path() -> Path:
    return _database_path


# 派生 PG 结构时把 connection() 临时指到一个内存 SQLite。只有 derive_schema_sql 会设它。
_forced_connection = None


class _NonClosing:
    """包住内存库连接：`with` 退出时提交，但**不关**——外面还要 dump 它的结构。

    sqlite3 的连接上下文管理器本来就不关连接，但 _initialize_sqlite 里有多个
    连续的 `with connection()`，每次都拿同一个内存库；一旦关掉，后面几段就建在
    一个空库上，dump 出来缺一半表。
    """

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False


def connection():
    """两个后端共用的入口。返回的对象在 `with` 里的语义一致：正常提交、异常回滚。"""

    if _forced_connection is not None:
        return _NonClosing(_forced_connection)
    if is_postgres():
        return pgbackend.connect()
    _database_path.parent.mkdir(parents=True, exist_ok=True)
    # 后台同步与页面请求会同时写库，锁等待放宽到 15 秒，避免偶发的 database is locked。
    conn = sqlite3.connect(_database_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def sqlite_connection(path: Path | str) -> sqlite3.Connection:
    """明确要一个 SQLite 连接（备份、导入导出、派生 PG 结构时用）。"""
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database() -> None:
    """建库/升级。PG 走派生路径，SQLite 走下面这条原路。"""

    if is_postgres():
        _initialize_postgres()
        return
    _initialize_sqlite()


def derive_schema_sql() -> str:
    """把当前的 SQLite 建表 + 迁移阶梯在内存库里跑一遍，dump 出最终结构。

    这样 PG 的表结构永远等于 SQLite 跑完所有迁移之后的样子，不需要有人记得
    「加了列也要去 PG 那边加一次」。派生出来的东西不会漂。
    """

    global _database_path
    saved = _database_path
    memory = sqlite3.connect(":memory:")
    memory.row_factory = sqlite3.Row
    try:
        # _initialize_sqlite 只认 connection()，临时把它指到这个内存库
        _override_connection(memory)
        _initialize_sqlite()
        rows = memory.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
            # 按 rowid 排 = 按建表顺序排：外键指向的表一定先建。
            # 按名字排会让 evidences 排在 theses 前面，PG 直接报 UndefinedTable。
            "AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, rowid"
        ).fetchall()
    finally:
        _override_connection(None)
        _database_path = saved
        memory.close()
    # dump 出来的是 CREATE TABLE / CREATE INDEX，补上 IF NOT EXISTS 让重复初始化安全
    statements = []
    for row in rows:
        sql = row["sql"].strip()
        sql = sql.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
        sql = sql.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)
        sql = sql.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1)
        statements.append(sql + ";")
    return "\n".join(statements)


def _override_connection(conn) -> None:
    """派生结构时把 connection() 临时指到内存库。只在 derive_schema_sql 内部用。"""
    global _forced_connection
    _forced_connection = conn


def _initialize_postgres() -> None:
    ddl_source = derive_schema_sql()
    body, tables, with_id = pgbackend.translate_ddl(ddl_source)
    pgbackend.register_tables(tables, with_id)
    conn = pgbackend.connect()
    try:
        # **每条 DDL 单独提交。** PostgreSQL 里一条语句出错，整个事务立刻进入 aborted，
        # 后续每条都会报 InFailedSqlTransaction，而结尾的 commit 等价于 ROLLBACK ——
        # 前面建好的表会一起消失。下面的重试要能在失败后继续，就不能共用一个事务。
        def run(statement: str) -> None:
            conn.executescript(statement)
            conn.commit()

        run(f"CREATE SCHEMA IF NOT EXISTS {pgbackend.SCHEMA}")
        # **必须排在建表建索引之前。** v32 的新索引建在 symbol 上，而老库里那一列
        # 还不存在——先建索引就会卡在「列不存在」，而且是在一个看起来跟迁移
        # 毫无关系的地方报错。新库上这一步是空操作（表都还没有）。
        _market_by_symbol_migration_pg(conn, run)
        # 建表顺序已按 rowid（= 实际建表顺序）排过，但迁移阶梯里的整表重建会打乱依赖，
        # 所以外键指向的表还没建时先记下来，等这一轮完了再试一遍。
        pending = _pg_statements(body, tables)
        for _ in range(4):
            deferred = []
            for statement in pending:
                try:
                    run(statement)
                except Exception as exc:
                    if "does not exist" not in str(exc):
                        raise
                    conn.rollback()
                    deferred.append(statement)
            if not deferred:
                break
            if len(deferred) == len(pending):
                raise RuntimeError(f"这些建表语句无论怎么排都建不出来：{deferred[:1]}")
            pending = deferred
        # **建表之后还要补列。** CREATE TABLE IF NOT EXISTS 对已存在的表什么都不做，
        # 所以后续版本新增的列（amount_mode、dividend_yield、method_key…）在已经建过的
        # 库上永远不会出现——直到搬数据时报一句 column does not exist。
        # SQLite 那边靠迁移阶梯里的 ALTER，PG 这边按「派生结构 vs 实际结构」逐列对齐。
        _add_missing_columns(conn, run, ddl_source)
        # 数据迁移（不是结构迁移）。**必须在这里也调一次**：只写在 SQLite 的
        # 迁移阶梯上，PG 这边就永远不会发生，而代码看起来是"已经修好了"。
        _canonicalise_task_item_status(conn)
        _split_model_note_from_user_note(conn)
        _backfill_thesis_price(conn)
        conn.commit()
        run(f"CREATE TABLE IF NOT EXISTS {pgbackend.SCHEMA}.schema_meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        run(f"INSERT INTO {pgbackend.SCHEMA}.schema_meta (key, value) VALUES ('version', '{SCHEMA_VERSION}') "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value")
        # 最后装行级安全。放在建表补列之后：策略要引用的表得先存在。
        # 每次初始化都重装一遍（DROP POLICY IF EXISTS + CREATE），
        # 这样改了策略表达式重启一次就生效，不需要记得手动去 ALTER。
        pgbackend.apply_row_level_security(conn)
    finally:
        conn.close()


def _columns_in_ddl(ddl_source: str) -> dict[str, list[tuple[str, str]]]:
    """从建表脚本里解析出每张表**应该有**哪些列。两个后端共用这一份。

    只解析，不决定怎么补 —— PG 走 information_schema、SQLite 走 PRAGMA，
    但"应该有哪些列"这件事只该有一个答案。
    """
    import re

    # **先剥掉 `-- 注释`。** sqlite_master 原样保存建表语句，包括注释；
    # 而本仓的建表脚本注释很多，一个「-- 这一列是干嘛的」会让它下面那列
    # 解析不出列名，于是那一列静静地没被补上——上一版就是这么漏了
    # portfolios.amount_mode 与 trades.cash_amount 的。
    ddl_source = re.sub(r"--[^\n]*", "", ddl_source)

    wanted: dict[str, list[tuple[str, str]]] = {}
    for statement in pgbackend._split_statements(ddl_source):
        m = re.match(r"\s*CREATE TABLE(?:\s+IF NOT EXISTS)?\s+([a-z_][a-z0-9_]*)\s*\((.*)\)\s*$",
                     statement, re.S | re.I)
        if not m:
            continue
        table, body = m.group(1).lower(), m.group(2)
        columns, depth, current = [], 0, ""
        for ch in body:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                columns.append(current)
                current = ""
            else:
                current += ch
        columns.append(current)
        for column in columns:
            column = column.strip()
            head = re.match(r"([a-z_][a-z0-9_]*)\s+(.+)", column, re.S | re.I)
            # 跳过表级约束（PRIMARY KEY (...)、UNIQUE (...)、FOREIGN KEY ...）
            if not head or head.group(1).upper() in {"PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT"}:
                continue
            wanted.setdefault(table, []).append((head.group(1).lower(), head.group(2).strip()))
    return wanted


def _add_missing_columns(conn, run, ddl_source: str) -> None:
    """把派生结构里有、PG 里还没有的列补上。只加列，不改也不删。

    只加列是刻意的：改类型与删列都可能丢数据，那种事必须有人看着做，
    不该由一个每次启动都跑的函数替你决定。
    """
    import re

    wanted = _columns_in_ddl(ddl_source)

    with conn._raw.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = %s",
            (pgbackend.SCHEMA,))
        have: dict[str, set[str]] = {}
        for row in cur.fetchall():
            have.setdefault(row["table_name"], set()).add(row["column_name"])

    for table, columns in wanted.items():
        existing = have.get(table)
        if existing is None:
            continue
        for name, definition in columns:
            if name in existing:
                continue
            # 只取类型与默认值；REFERENCES / PRIMARY KEY 这类留给建表时处理。
            kind = re.split(r"\s+REFERENCES\s+", definition, flags=re.I)[0].strip()
            kind = re.sub(r"\bPRIMARY\s+KEY\b", "", kind, flags=re.I).strip()
            translated, _, _ = pgbackend.translate_ddl(f"CREATE TABLE t (x {kind});")
            kind = re.search(r"x\s+(.*);", translated, re.S).group(1).rstrip(")").strip()
            run(f"ALTER TABLE {pgbackend.SCHEMA}.{table} ADD COLUMN IF NOT EXISTS {name} {kind}")


def _pg_statements(body: str, tables: set[str]) -> list[str]:
    """把派生出的 DDL 拆成单条，并把表名/索引名限定到 stocks schema。"""
    import re

    out = []
    for statement in pgbackend._split_statements(body):
        statement = statement.strip()
        if not statement:
            continue
        for name in sorted(tables, key=len, reverse=True):
            statement = re.sub(rf"(CREATE TABLE IF NOT EXISTS |REFERENCES |ON )\b{name}\b",
                               rf"\g<1>{pgbackend.SCHEMA}.{name}", statement)
        # 索引名**不加** schema 前缀：PG 的索引自动落在它所属表的 schema 里，
        # 写成 stocks.idx_x 是语法错误。
        out.append(statement)
    return out


# 建表脚本。**提成常量是为了让迁移能复用同一份定义**——重建表时手抄一份 DDL，
# 迟早跟真定义漂开，而漂开的表现是「迁移完少了一列」，要到用上那列时才发现。
_SCHEMA_SQL = """
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY,
                -- 数据域（见 access.py）：站主的存量数据 = '__owner__'，其他用户 = 各自的 user_id。
                -- symbol 的唯一性因此是**按用户**的：两个用户都可以研究茅台，各有各的档案。
                user_id TEXT NOT NULL DEFAULT '__owner__',
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT '待确认',
                industry TEXT NOT NULL,
                industry_source TEXT NOT NULL DEFAULT '待补充',
                description TEXT NOT NULL DEFAULT '',
                watch_group TEXT NOT NULL DEFAULT '观察池',
                is_watched INTEGER NOT NULL DEFAULT 1,
                valuation_percentile INTEGER,
                roe_trend TEXT NOT NULL DEFAULT '待补充',
                -- 这一条是不是预置的示例。**新用户不该看见一个空产品**——
                -- 承诺台账那一屏之所以显得啰嗦，一大半原因是它是空的：
                -- 四段说明包着一句「还没有记录任何承诺」。
                --
                -- 标记而不是混进去装作真的：示例要看得出是示例，也要能一键删掉。
                -- **不能删的示例等于强塞。**
                is_sample INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (user_id, symbol)
            );

            -- theses.is_sample：预置的那条示例判断。**改过之后就清掉这个标记**——
            -- 使用者一旦动手改它，它就是他自己的判断了。
            CREATE TABLE IF NOT EXISTS theses (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                is_sample INTEGER NOT NULL DEFAULT 0,
                claim TEXT NOT NULL,
                counter_condition TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                next_review_trigger TEXT NOT NULL DEFAULT '手动复核',
                next_review_date TEXT,
                last_reviewed_at TEXT,
                -- 这条逻辑当初是按哪个方法写的。记下来才能在季度归因时回答
                -- 「我用某某方法写的逻辑，后来站住了几条」——方法库不记这个的话，
                -- 它永远只是一份读物，而不是一件会告诉你「你更适合哪套」的工具。
                method_key TEXT,
                method_name TEXT,
                -- 写下这条判断时的股价。**推不出来，所以必须当场记。**
                -- 归因时最要紧的一句是「我当时是在什么价位这么想的」——
                -- 没有它，"后来涨了/跌了"这句话没有起点。
                -- 老记录可以从日线回填（标成推算），新记录一律当场落。
                price_at_write REAL,
                price_source TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidences (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                thesis_id INTEGER REFERENCES theses(id) ON DELETE SET NULL,
                source_name TEXT NOT NULL,
                source_url TEXT,
                excerpt TEXT NOT NULL,
                polarity TEXT NOT NULL,
                -- 判成这个方向的依据。**没有理由的方向不算数**：
                -- 一个说不出为什么的「削弱」会让人白紧张一场，下次真的削弱时他就不信了。
                polarity_reason TEXT NOT NULL DEFAULT '',
                polarity_source TEXT NOT NULL DEFAULT '',   -- 人工 / 模型
                occurred_at TEXT NOT NULL,
                verification TEXT NOT NULL DEFAULT '待核验',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS research_events (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                thesis_id INTEGER REFERENCES theses(id) ON DELETE SET NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                importance TEXT NOT NULL,
                verification TEXT NOT NULL DEFAULT '待核验',
                created_at TEXT NOT NULL
            );

            -- 行情、财务、公司简况这几张按 **symbol** 存，全局共享一份。
            --
            -- 原来它们挂在 company_id 上，而 companies 是按用户隔离的（每人一份档案），
            -- 于是两个人关注同一只票，K线/估值/财报就各存一份、数据源也各拉一次。
            -- 一个人 34,849 行，十个人就是三十多万行 + 十倍的接口调用，而这些数据
            -- 客观上谁看都一样。
            --
            -- 私有的只剩「我关注了它」（companies）、「我的判断」（theses/evidences）、
            -- 「我的交易」（trades）。行情不设行级安全策略——它本来就是公开数据。
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                price REAL,
                prev_close REAL,
                change_percent REAL,
                pe REAL,
                pb REAL,
                high_52w REAL,
                low_52w REAL,
                total_market_cap REAL,
                market_timestamp TEXT,
                source TEXT NOT NULL,
                refreshed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_theses_company ON theses(company_id);
            CREATE INDEX IF NOT EXISTS idx_evidences_company ON evidences(company_id);
            CREATE INDEX IF NOT EXISTS idx_events_company ON research_events(company_id);
            CREATE INDEX IF NOT EXISTS idx_snapshots_symbol ON market_snapshots(symbol, refreshed_at DESC);

            CREATE TABLE IF NOT EXISTS provider_syncs (
                provider_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                category TEXT NOT NULL,
                last_status TEXT NOT NULL DEFAULT '未同步',
                last_attempt_at TEXT,
                last_success_at TEXT,
                last_error TEXT,
                refreshed_items INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS price_bars (
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                close REAL NOT NULL,
                -- 开盘价。**日内做 T 的模拟全靠它**：没有分时数据的情况下，
                -- 「开盘卖、收盘买回」是唯一一对能在日线上诚实定价的成交。
                -- 两个日线源都给了 open，只是这张表一直没存。
                -- 列名不写 open：OPEN 在 SQL 标准里是保留字，PG 现在容得下、
                -- 换个后端就不一定，为一个省两个字的列名冒这个险不值。
                open_price REAL,
                high REAL,
                low REAL,
                volume REAL,
                amount REAL,
                change_percent REAL,
                source TEXT NOT NULL,
                refreshed_at TEXT NOT NULL,
                PRIMARY KEY (symbol, trade_date, source)
            );

            CREATE INDEX IF NOT EXISTS idx_price_bars_symbol_date ON price_bars(symbol, trade_date DESC);

            CREATE TABLE IF NOT EXISTS financial_periods (
                symbol TEXT NOT NULL,
                report_date TEXT NOT NULL,
                revenue REAL,
                net_profit REAL,
                operating_cash_flow REAL,
                operating_cost REAL,
                rnd_expense REAL,
                capex REAL,
                receivables REAL,
                inventory REAL,
                interest_bearing_debt REAL,
                total_assets REAL,
                total_liabilities REAL,
                equity REAL,
                debt_ratio REAL,
                roe_estimate REAL,
                currency TEXT NOT NULL DEFAULT 'CNY',
                audit_status TEXT NOT NULL DEFAULT '待确认',
                announcement_date TEXT,
                source TEXT NOT NULL,
                refreshed_at TEXT NOT NULL,
                PRIMARY KEY (symbol, report_date, source)
            );

            CREATE INDEX IF NOT EXISTS idx_financial_periods_symbol_date ON financial_periods(symbol, report_date DESC);

            -- 报表原始科目。**存科目，不存算好的比率。**
            --
            -- 「白酒的合同负债、银行的净息差、地产的销售回款」这类真正能分辨生意的数，
            -- 通用的那十来个字段里一个都没有。而三张表本来就已经全下下来了
            -- （资产负债 147 列、利润 83 列、现金流 71 列），此前挑走十几个就全扔了。
            --
            -- 存原始科目而不是存比率：算术随时会改，改了之后老记录该跟着重算，
            -- 而不是背着一个按旧公式算出来的数。窄表也意味着**加一个指标不用迁移**。
            --
            -- 全局共享（按 symbol）：茅台的合同负债对谁都是同一个数。
            CREATE TABLE IF NOT EXISTS financial_line_items (
                symbol TEXT NOT NULL,
                report_date TEXT NOT NULL,
                item TEXT NOT NULL,
                value REAL,
                source TEXT NOT NULL,
                refreshed_at TEXT NOT NULL,
                PRIMARY KEY (symbol, report_date, item)
            );

            CREATE INDEX IF NOT EXISTS idx_line_items_symbol ON financial_line_items(symbol, report_date DESC);

            -- 管理层承诺兑现台账。
            --
            -- **公司说过的话，到期之后没有任何人回头看。** 「三年内分红比例不低于
            -- 30%」「拟回购不低于 5 亿元」「2026 年净利润不低于 X」——这些话说的时候
            -- 是利好、股价会涨，而到期日没有一个提醒、没有一处记录。
            -- 结果是：一家从不兑现承诺的公司，跟一家次次说到做到的公司，
            -- 在你的档案里长得一模一样。
            --
            -- 这张表就是那个记录本。它跟认错条件是同一个形状：
            -- **一句话 + 一个到期日 + 一个到期时能核对的条件。**
            --
            -- 能机器核的（净利润、营收、分红比例）到期自动比对；
            -- 核不了的（回购进度、项目达产）到期问你一句。
            -- **一条都不自动判"未兑现"** —— 那是判决，要人来下。
            CREATE TABLE IF NOT EXISTS management_promises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                -- 出处：哪条公告说的。没有出处的承诺不许进这张表。
                event_id INTEGER REFERENCES company_calendar_events(id) ON DELETE SET NULL,
                source_title TEXT NOT NULL DEFAULT '',
                source_url TEXT,
                promised_on TEXT NOT NULL,           -- 说这话的日期
                subject TEXT NOT NULL DEFAULT '公司', -- 谁承诺的：公司 / 控股股东 / 实控人 / 董监高
                statement TEXT NOT NULL,             -- 原文里那句话，抄下来不改写
                category TEXT NOT NULL DEFAULT '其他',
                due_date TEXT,                       -- 到期日。推不出来就留空，不猜
                -- 能机器核的条件：指标 · 比较 · 目标值 · 看哪个报告期
                check_metric TEXT NOT NULL DEFAULT '',
                check_op TEXT NOT NULL DEFAULT '',
                check_value REAL,
                check_period TEXT NOT NULL DEFAULT '',
                -- 待到期 / 已兑现 / 未兑现 / 部分兑现 / 无法核对 / 已放弃
                status TEXT NOT NULL DEFAULT '待到期',
                outcome_note TEXT NOT NULL DEFAULT '',
                settled_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (user_id, company_id, statement, promised_on)
            );

            CREATE INDEX IF NOT EXISTS idx_promises_company ON management_promises(company_id, due_date);

            -- 公告正文。**这张表存的是「关于股份回购进展情况的公告」那十四个字后面的东西。**
            --
            -- 承诺台账在 12 家公司上抽出 0 条，原因不是标准太严，是标题里根本没有承诺：
            -- 格力那条公告的「不低于 50 亿元」「不超过 12 个月」「不低于 70% 用于注销」
            -- 全在正文里。见 disclosure.py 开头。
            --
            -- 主键是巨潮的公告编号，**全局一份、不按用户隔离**：同一份公告谁下载都是
            -- 同一个 PDF，跟 K 线同理。所以它进 _GLOBAL_MARKET_TABLES。
            --
            -- 取不到的也写进来（status='取不到'）。不写的话，一条已撤下的公告
            -- 会在每次抽取时被重试一遍，而它永远不会成功。
            -- 产业链位置：年报里强制披露的客户与供应商集中度。
            --
            -- **这是「产业链地图」唯一可核对的那部分。** 原来那一页是模型凭
            -- 世界知识画的四个方框（实测中国平安的上游七条里三条是同一件事，
            -- 其中两条字面完全相同），而这两个数在年报里有确定答案：
            --
            --     前五名客户合计销售金额占年度销售总额比例   ← 下游有多集中
            --     前五名供应商合计采购金额占年度采购总额比例 ← 上游有多集中
            --
            -- 实测寒武纪 88.66% / 茅台 10.10%，是两种完全不同的生意。
            -- 纯正则解析，不经过模型（见 chain_position）。
            --
            -- 按 symbol 存、**全局一份**：年报披露谁看都一样，跟 K 线同理。
            -- 银行与保险不适用这项披露，那种情况存 NULL 并在 note 里说清楚，
            -- 而不是留空让人以为还没抓。
            CREATE TABLE IF NOT EXISTS chain_positions (
                symbol TEXT PRIMARY KEY,
                report_title TEXT NOT NULL DEFAULT '',
                report_date TEXT NOT NULL DEFAULT '',
                source_url TEXT,
                customer_ratio REAL,
                customer_amount REAL,
                supplier_ratio REAL,
                supplier_amount REAL,
                top_json TEXT NOT NULL DEFAULT '',
                excerpt TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                extracted_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS announcement_texts (
                announcement_id TEXT PRIMARY KEY,
                pdf_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,                -- 已取正文 / 取不到
                note TEXT NOT NULL DEFAULT '',       -- 取不到的原因，摆给人看
                char_count INTEGER NOT NULL DEFAULT 0,
                body TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL
            );

            -- 三情景估值。**存假设，不存算出来的价值**：算术是确定的，
            -- 公式改了应该让老记录跟着重算，而不是背着一个过期的数字。
            -- price_at_write 例外——它推不出来，而复盘时"我当时是在什么价位这么想的"
            -- 恰恰是最要紧的一条。
            --
            -- 不设 UNIQUE：每次保存插一行，最新的一行是当前值，其余是你假设的变迁史。
            -- 几行数据换一份复盘素材，很划算。
            CREATE TABLE IF NOT EXISTS valuations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                years INTEGER NOT NULL DEFAULT 5,
                discount_rate REAL NOT NULL DEFAULT 10,
                scenarios TEXT NOT NULL DEFAULT '[]',
                price_at_write REAL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_valuations_company ON valuations(company_id, id DESC);

            CREATE TABLE IF NOT EXISTS research_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                title TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '候选清单',
                strategy_key TEXT,
                strategy_name TEXT,
                rules TEXT NOT NULL DEFAULT '[]',
                data_note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '进行中',
                conclusion TEXT NOT NULL DEFAULT '',
                due_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT
            );

            -- 候选条目。note 是拼好的平文本（导出、旧页面还在读），
            -- reasons / concerns 是模型返回的原始结构 —— 页面按块渲染用这两列。
            -- 拼平之后再想拆回来是拆不干净的：结论里本来就有分号和换行。
            CREATE TABLE IF NOT EXISTS research_task_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES research_tasks(id) ON DELETE CASCADE,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                industry TEXT,
                evidence TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT '待看',
                note TEXT NOT NULL DEFAULT '',
                verdict TEXT NOT NULL DEFAULT '',
                -- 模型初筛写的结论。**跟 note 分开**：note 是你自己写的一句话，
                -- 两者共用一个字段的后果是模型那段几百字被塞进单行输入框里，
                -- 想看都看不到，而你自己想写点什么还得先把它删掉。
                conclusion TEXT NOT NULL DEFAULT '',
                -- 候选的方法体检结果。**存在这里而不是 method_assessments**：
                -- 那张表挂在 company_id 上（NOT NULL + 外键），而候选还没建档。
                -- 为了跑一次体检就自动建档，是把"要不要建档"这个决定替人做了，
                -- 而体检本来就是用来帮他做这个决定的。
                assessment TEXT NOT NULL DEFAULT '[]',
                assessed_at TEXT NOT NULL DEFAULT '',
                reasons TEXT NOT NULL DEFAULT '[]',
                concerns TEXT NOT NULL DEFAULT '[]',
                company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (task_id, symbol)
            );

            CREATE INDEX IF NOT EXISTS idx_task_items ON research_task_items(task_id, status);

            CREATE TABLE IF NOT EXISTS screen_strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                key TEXT NOT NULL,
                name TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                provenance TEXT NOT NULL DEFAULT '',
                biases TEXT NOT NULL DEFAULT '[]',
                rules TEXT NOT NULL,
                sort_field TEXT NOT NULL,
                sort_desc INTEGER NOT NULL DEFAULT 1,
                sort_label TEXT NOT NULL DEFAULT '',
                forked_from TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (user_id, key)
            );

            CREATE TABLE IF NOT EXISTS screen_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                strategy_key TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                rules TEXT NOT NULL,
                universe_total INTEGER NOT NULL DEFAULT 0,
                matched INTEGER NOT NULL DEFAULT 0,
                report_date TEXT,
                price_as_of TEXT,
                executed_at TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_screen_runs_time ON screen_runs(executed_at DESC);

            -- 模型复核结果：规则筛选是可重跑的，模型输出却是一次性的，必须单独留档。
            CREATE TABLE IF NOT EXISTS candidate_review_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                strategy_key TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                width INTEGER NOT NULL DEFAULT 0,
                rows TEXT NOT NULL DEFAULT '[]',
                note TEXT NOT NULL DEFAULT '',
                boundary TEXT NOT NULL DEFAULT '',
                estimated_credits INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_candidate_review_runs_time
                ON candidate_review_runs(user_id, created_at DESC);

            -- 找票页的后台复核目标。target_id 交给 background_jobs 使用，
            -- 用策略 + 宽度稳定定位同一份清单，切页回来还能继续轮询。
            CREATE TABLE IF NOT EXISTS candidate_review_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                strategy_key TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                width INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (user_id, strategy_key, width)
            );

            CREATE INDEX IF NOT EXISTS idx_candidate_review_targets_lookup
                ON candidate_review_targets(user_id, strategy_key, width);

            CREATE TABLE IF NOT EXISTS market_universe (
                symbol TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT '',
                board TEXT NOT NULL DEFAULT '',
                industry TEXT,
                price REAL,
                change_percent REAL,
                pe_ttm REAL,
                pb REAL,
                total_market_cap REAL,
                float_market_cap REAL,
                turnover_rate REAL,
                ytd_change REAL,
                change_60d REAL,
                report_date TEXT,
                revenue REAL,
                revenue_growth REAL,
                net_profit REAL,
                net_profit_growth REAL,
                roe REAL,
                gross_margin REAL,
                eps REAL,
                bps REAL,
                ocf_per_share REAL,
                annual_roe REAL,
                annual_gross_margin REAL,
                dividend_yield REAL,
                dividend_per_10 REAL,
                dividend_period TEXT,
                sw_level1 TEXT,
                sw_level2 TEXT,
                -- 趋势面。行情快照降级到新浪之后，change_60d / ytd_change / turnover_rate
                -- 全是 0% 覆盖（新浪只给价格和当日涨跌），东财那两条能给区间涨跌的路都被挡着。
                -- 所以趋势改用同花顺的榜单，存成普通列，规则筛就能直接用。
                -- **不在榜上记 0，不是记 NULL**：0 = 不在榜上（一个事实），
                -- NULL = 没同步过（数据源挂了）。混在一起的话数据源挂了没人知道。
                rising_days REAL,
                stage_gain REAL,
                stage_turnover REAL,
                above_ma60 REAL,
                new_high_level REAL,
                volume_days REAL,
                trend_source TEXT,
                trend_as_of TEXT,
                price_source TEXT,
                price_as_of TEXT,
                fundamental_source TEXT,
                fundamental_as_of TEXT,
                updated_at TEXT NOT NULL
            );

            -- 全市场情绪面。**这几个数要反着读**：人气高说明已经被充分讨论，
            -- 对长期研究者是减分项。attention_rank 越小越热，所以"排名靠后"才是好消息。
            -- comment_score 与 institution_participation 是东财自己算的，口径不公开，
            -- 只做展示、不进打分——把黑箱输出乘一个权重算进总分，那分数就没法解释了。
            CREATE TABLE IF NOT EXISTS market_sentiment (
                symbol TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                trade_date TEXT,
                main_cost REAL,
                institution_participation REAL,
                comment_score REAL,
                attention_rank REAL,
                rank_change REAL,
                attention_index REAL,
                turnover_rate REAL,
                xq_followers REAL,
                source TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sentiment_rank ON market_sentiment(attention_rank);

            CREATE TABLE IF NOT EXISTS universe_valuation_history (
                symbol TEXT NOT NULL,
                point_date TEXT NOT NULL,
                pe_ttm REAL,
                pb REAL,
                source TEXT NOT NULL,
                PRIMARY KEY (symbol, point_date)
            );

            CREATE INDEX IF NOT EXISTS idx_universe_valuation_symbol ON universe_valuation_history(symbol, point_date);

            CREATE INDEX IF NOT EXISTS idx_universe_board ON market_universe(board);
            CREATE INDEX IF NOT EXISTS idx_universe_roe ON market_universe(roe DESC);
            CREATE INDEX IF NOT EXISTS idx_universe_pe ON market_universe(pe_ttm);

            CREATE TABLE IF NOT EXISTS index_members (
                index_code TEXT NOT NULL,
                index_name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (index_code, symbol)
            );

            CREATE INDEX IF NOT EXISTS idx_index_members_symbol ON index_members(symbol);

            CREATE TABLE IF NOT EXISTS universe_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                price_rows INTEGER NOT NULL DEFAULT 0,
                fundamental_rows INTEGER NOT NULL DEFAULT 0,
                index_rows INTEGER NOT NULL DEFAULT 0,
                price_source TEXT,
                fundamental_source TEXT,
                report_date TEXT,
                degraded INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS thesis_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thesis_id INTEGER NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                verdict TEXT NOT NULL,
                note TEXT NOT NULL,
                previous_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                next_review_date TEXT,
                thesis_version INTEGER,
                support_evidence INTEGER NOT NULL DEFAULT 0,
                counter_evidence INTEGER NOT NULL DEFAULT 0,
                event_count INTEGER NOT NULL DEFAULT 0,
                price_at_review REAL,
                pe_percentile_at_review REAL,
                unrealized_at_review REAL,
                realized_at_review REAL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_thesis_reviews_thesis ON thesis_reviews(thesis_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_thesis_reviews_created ON thesis_reviews(created_at DESC);

            CREATE TABLE IF NOT EXISTS sync_schedules (
                job_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                category TEXT NOT NULL,
                interval_minutes INTEGER NOT NULL,
                weekdays_only INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                freshness_hours INTEGER NOT NULL,
                last_started_at TEXT,
                last_finished_at TEXT,
                last_status TEXT NOT NULL DEFAULT '未运行',
                last_error TEXT,
                last_items INTEGER NOT NULL DEFAULT 0,
                last_success_at TEXT,
                -- 使用者自己改过间隔吗。**代码管默认值，改过的不动。**
                --
                -- 没有这一列的后果实测到了：把 universe 从 1440 分钟改成 30，
                -- 部署完库里那一行还是 1440 —— 同一个概念写了两份（代码常量 +
                -- 库里的行），而库里那份赢了。改完、部署完、日志干净、什么都没报错，
                -- **只是没生效**。而反过来让代码一律覆盖，会把「PATCH /sync/jobs」
                -- 那个功能弄坏（间隔本来就是可改的）。所以要记下"是谁定的"。
                interval_overridden INTEGER NOT NULL DEFAULT 0,
                next_run_at TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                trigger TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                items INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                detail TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_sync_runs_job ON sync_runs(job_id, started_at DESC);

            CREATE TABLE IF NOT EXISTS valuation_points (
                symbol TEXT NOT NULL,
                metric TEXT NOT NULL,
                point_date TEXT NOT NULL,
                value REAL NOT NULL,
                source TEXT NOT NULL,
                refreshed_at TEXT NOT NULL,
                PRIMARY KEY (symbol, metric, point_date, source)
            );

            CREATE INDEX IF NOT EXISTS idx_valuation_points_lookup ON valuation_points(symbol, metric, source, point_date);

            CREATE TABLE IF NOT EXISTS record_revisions (
                id INTEGER PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                snapshot TEXT NOT NULL,
                changed_fields TEXT NOT NULL DEFAULT '',
                change_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE (entity_type, entity_id, version)
            );

            CREATE INDEX IF NOT EXISTS idx_record_revisions_entity ON record_revisions(entity_type, entity_id, version DESC);

            CREATE TABLE IF NOT EXISTS company_profiles (
                symbol TEXT PRIMARY KEY,
                full_name TEXT,
                english_name TEXT,
                industry TEXT,
                market TEXT,
                legal_representative TEXT,
                registered_capital REAL,
                founded_date TEXT,
                listed_date TEXT,
                website TEXT,
                registered_address TEXT,
                office_address TEXT,
                main_business TEXT,
                product_type TEXT,
                business_scope TEXT,
                introduction TEXT,
                total_shares REAL,
                circulating_shares REAL,
                share_structure_date TEXT,
                share_change_reason TEXT,
                issue_price REAL,
                raised_net REAL,
                underwriter TEXT,
                latest_dividend_period TEXT,
                latest_dividend_plan TEXT,
                latest_dividend_progress TEXT,
                latest_dividend_payout_ratio TEXT,
                latest_dividend_record_date TEXT,
                latest_dividend_ex_date TEXT,
                missing_sections TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL,
                refreshed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS company_calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                event_date TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                url TEXT,
                source TEXT NOT NULL,
                refreshed_at TEXT NOT NULL,
                inbox_status TEXT NOT NULL DEFAULT '待核验',
                archived_as TEXT,
                archived_ref_id INTEGER,
                handled_at TEXT,
                relevance TEXT,
                relevance_reason TEXT,
                relevance_source TEXT,
                -- 比对过认错条件的时间。**跟 counter_hits 分开记**：
                -- 那张表只存命中，而"比过了没命中"同样是已经花过钱的事实。
                counter_checked_at TEXT,
                relevance_topic TEXT,
                summary TEXT,
                classified_at TEXT,
                UNIQUE (company_id, category, event_date, title)
            );

            CREATE INDEX IF NOT EXISTS idx_company_calendar_date ON company_calendar_events(company_id, event_date DESC);

            CREATE TABLE IF NOT EXISTS portfolios (
                id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                name TEXT NOT NULL,
                objective TEXT NOT NULL DEFAULT '',
                -- 记到什么程度：full = 股数与价格都记（能算真实盈亏）；
                -- ratio = 只记仓位占比，不落任何金额。见 schemas.AmountMode 的说明。
                amount_mode TEXT NOT NULL DEFAULT 'full',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (user_id, name)
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY,
                portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                thesis_id INTEGER REFERENCES theses(id) ON DELETE SET NULL,
                -- buy/sell/dividend/bonus/rights。后三种不是「决定」而是「发生在你身上的事」，
                -- 但它们同样改变持仓与收益，不记就等于账本长期偏离事实。
                side TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                -- ratio 模式下 shares/price 为空，改用 weight_percent 记仓位占比
                shares REAL,
                price REAL,
                fee REAL NOT NULL DEFAULT 0,
                weight_percent REAL,
                -- 现金分红的税后到账金额（分红行专用；ratio 模式下留空）
                cash_amount REAL,
                rationale TEXT NOT NULL,
                expectation TEXT NOT NULL DEFAULT '',
                review_due TEXT,
                thesis_claim_snapshot TEXT NOT NULL DEFAULT '',
                thesis_status_snapshot TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_trades_portfolio ON trades(portfolio_id, trade_date, id);
            CREATE INDEX IF NOT EXISTS idx_trades_company ON trades(company_id, trade_date, id);
            """


_DERIVING_SCHEMA = False


def _sqlite_add_missing_columns(conn) -> None:
    """把建表脚本里有、SQLite 库里还没有的列补上。**只加列，不改也不删。**

    跟 PG 那边 `_add_missing_columns` 是同一个道理、同一份解析
    （`_columns_in_ddl`），差别只在怎么问库里现有的列：
    PG 查 information_schema，SQLite 用 PRAGMA table_info。

    加不上的那一列**不许静默跳过**：SQLite 不接受给已有表加
    `NOT NULL` 且无默认值的列，那种情况要让人看见，而不是留下一张缺列的表
    等着以后报 `no such column`。

    ## 补回来的列会排在末尾，这是可以的

    `ALTER TABLE ADD COLUMN` 只能追加，SQLite 没有插入位置的语法。
    所以补过列的表，列顺序跟新建的库不一样。查过三处、确认无害：

      · 全仓没有一条 `INSERT INTO 表 VALUES(...)` 不写列名的（那种才怕顺序）
      · 备份还原按**列名**取（backup.table_columns）
      · 二十处 `row[0]` 都是 `SELECT count(*)` 这类单列查询，跟表结构无关
    """
    import logging

    # **应有的列从 `derive_schema_sql()` 来，不是从 `_SCHEMA_SQL`。**
    #
    # 第一版喂的是 _SCHEMA_SQL，结果 documents / document_pages /
    # fundraising_projects 这几张表一列都没解析出来 —— 因为它们的建表语句
    # 写在 `_initialize_sqlite` 函数体里的另外几段 executescript 里，
    # 根本不在那个常量中（全仓一共四段）。
    #
    # `derive_schema_sql()` 是在内存库里把整套建表加迁移阶梯跑一遍再 dump 出来的，
    # **那是"这个版本的结构应该长什么样"的唯一真源** —— PG 那边用的也是它。
    #
    # **但它内部会调 `_initialize_sqlite()`**，而这个函数正是从那里被调的 ——
    # 第二版直接调它，当场无限递归。所以派生那一趟里要跳过补列：
    # 内存库是全新建的，本来也没有缺列这回事。
    global _DERIVING_SCHEMA
    if _DERIVING_SCHEMA:
        return
    _DERIVING_SCHEMA = True
    try:
        wanted = _columns_in_ddl(derive_schema_sql())
    finally:
        _DERIVING_SCHEMA = False
    have_tables = {row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    for table, columns in wanted.items():
        if table not in have_tables:
            continue
        present = {row["name"].lower() for row in conn.execute(
            f'PRAGMA table_info("{table}")').fetchall()}
        for name, definition in columns:
            if name in present:
                continue
            try:
                conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {name} {definition}')
            except sqlite3.OperationalError as exc:
                # 报出来，别咽掉。缺一列的表在以后某次查询时才会炸，
                # 而那时候没人记得是这里没补上。
                logging.getLogger(__name__).warning(
                    "SQLite 补列失败 %s.%s（%s）：%s", table, name, definition, exc)


def _initialize_sqlite() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA_SQL)
        company_columns = {row["name"] for row in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "industry_source" not in company_columns:
            conn.execute("ALTER TABLE companies ADD COLUMN industry_source TEXT NOT NULL DEFAULT '待补充'")
            conn.execute("UPDATE companies SET industry_source = '用户填写' WHERE industry NOT IN ('待补充', '')")
        if "exchange" not in company_columns:
            conn.execute("ALTER TABLE companies ADD COLUMN exchange TEXT NOT NULL DEFAULT '待确认'")
        if "is_sample" not in company_columns:
            conn.execute("ALTER TABLE companies ADD COLUMN is_sample INTEGER NOT NULL DEFAULT 0")
        thesis_columns = {row["name"] for row in conn.execute("PRAGMA table_info(theses)").fetchall()}
        if "is_sample" not in thesis_columns:
            conn.execute("ALTER TABLE theses ADD COLUMN is_sample INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            UPDATE companies
            SET exchange = CASE
                WHEN symbol GLOB '6*' THEN '上海证券交易所'
                WHEN symbol GLOB '8*' OR symbol GLOB '4*' THEN '北京证券交易所'
                WHEN symbol GLOB '0*' OR symbol GLOB '3*' THEN '深圳证券交易所'
                ELSE exchange
            END
            WHERE exchange = '待确认'
            """
        )
        conn.executescript(
            """
            -- 你改过的分级，以及由此学到的规则词。
            --
            -- 分级引擎每天要判几百条，判错一条你改一次，改完下次照错——
            -- 这是这套规则唯一没有的东西：它不会从你的纠正里学。
            --
            -- **但也不自动学。** 规则词表直接决定几百条公告的去向，一个学歪的词
            -- 会静悄悄地把一整类实质公告扔进程序性堆里。所以流程是：
            -- 记下纠错 → 从中提取候选词并给出证据 → **你确认之后才生效**。
            CREATE TABLE IF NOT EXISTS inbox_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                event_id INTEGER NOT NULL REFERENCES company_calendar_events(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                was_relevance TEXT NOT NULL,
                was_source TEXT NOT NULL DEFAULT '',
                now_relevance TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_corrections_at ON inbox_corrections(created_at DESC);

            -- 你确认过的规则词。优先于内置词表，因为它带着你自己的判断。
            CREATE TABLE IF NOT EXISTS rule_terms (
                user_id TEXT NOT NULL DEFAULT '__owner__',
                term TEXT NOT NULL,
                relevance TEXT NOT NULL,
                topic TEXT NOT NULL DEFAULT '自定义',
                note TEXT NOT NULL DEFAULT '',
                hits INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, term)
            );

            -- 方法体检：这家公司在某个投资方法下读出来是什么样。
            --
            -- **按用户存，不共享。** 行情可以共享（茅台的 K 线谁看都一样），但体检不行：
            -- 它要引用你自己写的判断（「你认为品牌定价权在增强，而毛利率连续两期下滑」），
            -- 那就天然是你的东西。代价是每人每家各算一次，一次约两分。
            --
            -- 存 data_fingerprint 是为了知道「这份结论是基于哪一版数据算的」：
            -- 财报换了期、价格过了几天，旧结论就该标成过期而不是继续显示。
            CREATE TABLE IF NOT EXISTS method_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                method_key TEXT NOT NULL,
                verdict TEXT NOT NULL,          -- 符合 / 不符合 / 数据不足 / 需人工
                summary TEXT NOT NULL DEFAULT '',
                evidence TEXT NOT NULL DEFAULT '[]',   -- [{fact, value, as_of}]
                gaps TEXT NOT NULL DEFAULT '[]',       -- 缺什么数据才能判
                data_fingerprint TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE (user_id, company_id, method_key)
            );

            CREATE INDEX IF NOT EXISTS idx_assessments_company
                ON method_assessments(user_id, company_id);

            -- 每个人自己的偏好。目前只有一项：要不要让后台每天替他调模型分级。
            --
            -- 用 key/value 而不是给每个偏好加一列：偏好会一个个冒出来，
            -- 每次都改表结构、写迁移，在两个后端上各来一遍，代价远大于收益。
            -- 值统一存文本，读的时候各自解释。
            -- 反证命中：这条公告有没有踩到你写下的反证条件。
            --
            -- **这是投资逻辑闭环里一直缺的那一环。** 反证条件写下来之后，
            -- 原本要靠人自己读每条公告、自己想「这算不算我说的那种情况」——
            -- 而人恰恰在这一步最容易放过自己（跌了就想长期看好）。
            -- 由模型逐条比对，命中了直接顶到决策总览最前面。
            CREATE TABLE IF NOT EXISTS counter_hits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                event_id INTEGER NOT NULL REFERENCES company_calendar_events(id) ON DELETE CASCADE,
                thesis_id INTEGER NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
                clause TEXT NOT NULL DEFAULT '',      -- 命中的是哪一条反证
                reason TEXT NOT NULL DEFAULT '',      -- 为什么算命中
                acknowledged INTEGER NOT NULL DEFAULT 0,   -- 你看过并处理了没有
                created_at TEXT NOT NULL,
                UNIQUE (user_id, event_id, thesis_id)
            );

            CREATE INDEX IF NOT EXISTS idx_counter_hits_open
                ON counter_hits(user_id, acknowledged);

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT NOT NULL DEFAULT '__owner__',
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            );

            CREATE TABLE IF NOT EXISTS daily_briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                as_of TEXT NOT NULL,
                headline TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '{}',
                actions TEXT NOT NULL DEFAULT '[]',
                gaps TEXT NOT NULL DEFAULT '[]',
                -- 生成这份简报时代码算好的那批数（涨跌家数、行业涨跌、持仓浮盈）。
                -- **页面靠它画图，不靠模型复述。** 模型抄一遍那些数字既浪费 token
                -- 又会抄错，而它们本来就是我们自己算的。
                context TEXT NOT NULL DEFAULT '{}',
                model TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE (user_id, as_of)
            );

            CREATE TABLE IF NOT EXISTS news_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                key TEXT NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                builtin INTEGER NOT NULL DEFAULT 0,
                last_ok_at TEXT,
                last_error TEXT NOT NULL DEFAULT '',
                item_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE (user_id, key)
            );

            -- 闸口不可用时的未计费台账。**没有 user_id**：它记的是"这个进程
            -- 有多少次调用没能计上费"，是运营账不是研究数据，站主对账时要看全部；
            -- 按用户切开反而会让熔断各算各的（见 billing_ledger.py 顶部）。
            -- 全市场资金流的本地快照。**原来这一屏是请求时现拉的**：
            -- 供应商抖一下，驾驶舱直接 503，而这块数据一天只变一次。
            -- 存下来之后，拉不到就给上一份并在页面上标明"截至什么时候"。
            CREATE TABLE IF NOT EXISTS market_fund_flow (
                date TEXT PRIMARY KEY,
                main_net_inflow REAL,
                main_net_inflow_percent REAL,
                super_large_net_inflow REAL,
                large_net_inflow REAL,
                medium_net_inflow REAL,
                small_net_inflow REAL,
                sh_close REAL,
                sh_change_percent REAL,
                sz_close REAL,
                sz_change_percent REAL,
                synced_at TEXT NOT NULL
            );

            -- 真实用户的首屏与报错。**只存数字和页面名，不存内容。**
            --
            -- 这一页上全是持仓成本、买卖理由、还没公开的判断。任何埋点都不该
            -- 把这些带走 —— 所以这张表里没有 URL 查询串、没有公司名、没有 IP，
            -- 页面名还要在服务端按白名单校一遍（见 main.py 的 post_rum_sample）。
            CREATE TABLE IF NOT EXISTS rum_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'nav',      -- nav（首屏）/ error（JS 报错）
                -- 毫秒。取不到的留 NULL，不要填 0——0 会被当成"很快"。
                ttfb_ms INTEGER,
                dom_ready_ms INTEGER,
                load_ms INTEGER,
                lcp_ms INTEGER,
                -- 报错只留类型与消息前 200 字，不留堆栈里的用户数据
                error_name TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                -- 设备只分大类：桌面 / 手机 / 平板。不存完整 UA（那是指纹）
                device TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS unbilled_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module TEXT NOT NULL DEFAULT '',
                task TEXT NOT NULL DEFAULT '',
                -- 为什么没计上：闸口不可达 / 冻结被拒。**未登录和本地单机不落账**
                reason TEXT NOT NULL DEFAULT '',
                estimated_tokens INTEGER NOT NULL DEFAULT 0,
                -- 实际用量在调用跑完之后回填，对账靠的就是这两个数
                tokens INTEGER NOT NULL DEFAULT 0,
                searches INTEGER NOT NULL DEFAULT 0,
                credits_estimate INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                -- 对过账就盖个时间戳，**不删行**：删了就查不回"那天到底漏了多少"
                reconciled_at TEXT,
                note TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS background_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                kind TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '排队中',
                progress INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                -- 这次后台 AI 调用花掉的积分与 token。任务跑完时 HTTP 响应早已返回，
                -- 花费只能落在这里，否则用户永远看不到简报/研报到底花了多少。
                credits INTEGER NOT NULL DEFAULT 0,
                tokens INTEGER NOT NULL DEFAULT 0,
                metered INTEGER NOT NULL DEFAULT 0,
                -- 任务的结构化产出。note 只有 800 字、是给人看的一句话，
                -- 而读图这类任务的产出是几十条待确认记录，必须有地方放。
                result_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_target ON background_jobs(kind, target_id, id DESC);

            CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                fingerprint TEXT NOT NULL,
                feed_key TEXT NOT NULL,
                feed_name TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL,
                company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
                match_confidence TEXT NOT NULL DEFAULT '未匹配',
                match_reason TEXT NOT NULL DEFAULT '',
                match_source TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '待确认',
                read_at TEXT,
                archived_ref_id INTEGER,
                fetched_at TEXT NOT NULL,
                handled_at TEXT,
                UNIQUE (user_id, fingerprint)
            );
            CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_news_company ON news_items(company_id, published_at DESC);

            CREATE TABLE IF NOT EXISTS supply_chain_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                relation TEXT NOT NULL,
                counterpart TEXT NOT NULL,
                segment TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                confidence TEXT NOT NULL DEFAULT '待证实',
                source TEXT NOT NULL DEFAULT '',
                evidence_id INTEGER REFERENCES evidences(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                UNIQUE(company_id, relation, counterpart)
            );
            CREATE INDEX IF NOT EXISTS idx_chain_company ON supply_chain_links(company_id, relation);

            -- 产业链底图：这是跨公司的研究资产，和上面的 supply_chain_links 不是一回事。
            --
            -- supply_chain_links 只记「某家公司可能和谁有经营关系」；这里则先描述
            -- 一个行业怎样把原料、产品或服务交付到客户，再把公司定位到具体节点。
            -- 四张子表都带 user_id，是为了让一张底图可以跨多家公司、同时仍服从
            -- 多用户隔离；不能靠 company_id 回溯归属。
            CREATE TABLE IF NOT EXISTS industry_chain_themes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                name TEXT NOT NULL,
                chain_type TEXT NOT NULL DEFAULT '制造链',
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, name)
            );

            CREATE TABLE IF NOT EXISTS industry_chain_stages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                theme_id INTEGER NOT NULL REFERENCES industry_chain_themes(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                stage_kind TEXT NOT NULL DEFAULT 'core',
                description TEXT NOT NULL DEFAULT '',
                stage_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, theme_id, name)
            );
            CREATE INDEX IF NOT EXISTS idx_industry_chain_stage_theme
                ON industry_chain_stages(user_id, theme_id, stage_order);

            CREATE TABLE IF NOT EXISTS industry_chain_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                theme_id INTEGER NOT NULL REFERENCES industry_chain_themes(id) ON DELETE CASCADE,
                stage_id INTEGER NOT NULL REFERENCES industry_chain_stages(id) ON DELETE CASCADE,
                parent_id INTEGER REFERENCES industry_chain_nodes(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                node_type TEXT NOT NULL DEFAULT '产品',
                description TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                verification TEXT NOT NULL DEFAULT '待补证',
                node_order INTEGER NOT NULL DEFAULT 0,
                -- 这一环的市场盘子（亿元人民币），用来算「环节拥挤度 = 这一环 A 股合计市值 ÷ 盘子」。
                -- 三列一起写：没有口径和出处的盘子不能用——全球还是中国、收入还是投资额，
                -- 换个口径这个比值能差一个数量级。填不上就三列都空着，前端据此不显示拥挤度。
                market_size_cny_yi REAL,
                market_size_basis TEXT NOT NULL DEFAULT '',
                market_size_source_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, theme_id, stage_id, name)
            );
            CREATE INDEX IF NOT EXISTS idx_industry_chain_node_stage
                ON industry_chain_nodes(user_id, theme_id, stage_id, node_order);

            CREATE TABLE IF NOT EXISTS industry_chain_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                theme_id INTEGER NOT NULL REFERENCES industry_chain_themes(id) ON DELETE CASCADE,
                from_node_id INTEGER NOT NULL REFERENCES industry_chain_nodes(id) ON DELETE CASCADE,
                to_node_id INTEGER NOT NULL REFERENCES industry_chain_nodes(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL DEFAULT '流向',
                detail TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                verification TEXT NOT NULL DEFAULT '待补证',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, theme_id, from_node_id, to_node_id, relation_type)
            );
            CREATE INDEX IF NOT EXISTS idx_industry_chain_edge_theme
                ON industry_chain_edges(user_id, theme_id);

            CREATE TABLE IF NOT EXISTS industry_chain_company_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                theme_id INTEGER NOT NULL REFERENCES industry_chain_themes(id) ON DELETE CASCADE,
                node_id INTEGER NOT NULL REFERENCES industry_chain_nodes(id) ON DELETE CASCADE,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                role TEXT NOT NULL DEFAULT '参与者',
                detail TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                verification TEXT NOT NULL DEFAULT '待补证',
                valid_from TEXT,
                valid_to TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, theme_id, node_id, company_id, role)
            );
            CREATE INDEX IF NOT EXISTS idx_industry_chain_position_theme
                ON industry_chain_company_positions(user_id, theme_id, node_id);
            CREATE INDEX IF NOT EXISTS idx_industry_chain_position_company
                ON industry_chain_company_positions(user_id, company_id);

            -- 主营构成：年报披露的分部收入/成本/毛利率，按产品、行业、地区三种口径。
            -- **这是真数据**，不是模型推断的——产业链那张表全部是「待证实」，
            -- 而这张表每一行都能在年报的分部附注里对上。
            -- 全局共享（按 symbol，不按 company_id）：茅台的分部构成对谁都是同一份。
            CREATE TABLE IF NOT EXISTS business_segments (
                symbol TEXT NOT NULL,
                report_date TEXT NOT NULL,
                dimension TEXT NOT NULL,          -- 产品 / 行业 / 地区
                segment TEXT NOT NULL,
                revenue REAL,
                revenue_share REAL,               -- %
                cost REAL,
                profit REAL,
                profit_share REAL,                -- %
                gross_margin REAL,                -- %
                updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, report_date, dimension, segment)
            );
            CREATE INDEX IF NOT EXISTS idx_segments_symbol ON business_segments(symbol, report_date DESC);

            -- 读进来的文件（年报、公告、研报、调研纪要）。
            --
            -- **一页一行存在 document_pages 里，不是整份存成一段文字。**
            -- 这一页的全部价值在于能翻回原文核对：摘要里每个数字要指得回页码，
            -- 否则跟随便找个模型问没有区别。整份存成一段之后页码就找不回来了。
            --
            -- 按用户隔离：上传的可能是未公开的调研纪要，跟公告正文（全局一份）不同。
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                -- 归到哪家公司。**可以为空**：读一份还没建档的公司的研报也是常事。
                company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
                -- **从第一页读出来的标题，不是文件名。** 贴链接读进来的原来叫
                -- `H3_AP202405221634315503_1.pdf` —— 对读的人零信息量，
                -- 两份研报并排放着分不出哪份是哪份。
                title TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT '文件',      -- 年报 / 公告 / 研报 / 调研纪要 / 文件
                -- 标题底下那几个标签：类型 · 是谁 · 哪一期。全部从第一页抽，
                -- **抽不到就不给** —— 猜错一个标签会让人打开错的那份文件。
                tags TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL,                  -- upload / url
                url TEXT NOT NULL DEFAULT '',
                page_count INTEGER NOT NULL DEFAULT 0,
                read_pages INTEGER NOT NULL DEFAULT 0, -- 真的读出字来的页数
                char_count INTEGER NOT NULL DEFAULT 0,
                table_count INTEGER NOT NULL DEFAULT 0,
                -- 读法分布与读不到的页，原样存 JSON：**这是摆给使用者的那份交代**，
                -- 「读了 108 页、2 页是扫描件」和「读了 110 页」是两个结论。
                modes TEXT NOT NULL DEFAULT '{}',
                unreadable TEXT NOT NULL DEFAULT '[]',
                note TEXT NOT NULL DEFAULT '',
                -- 读完自动出的那份结果。**存下来，重开不重付** ——
                -- 一份文件读一次就该出一次结果，翻回来看不该再花一次钱。
                digest TEXT NOT NULL DEFAULT '',
                digest_kind TEXT NOT NULL DEFAULT '',    -- 按哪张清单读的
                digest_pages TEXT NOT NULL DEFAULT '[]', -- 用了哪几页，能翻回去核
                digest_missed TEXT NOT NULL DEFAULT '[]',-- 清单里没找到的那几条
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS document_pages (
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                page INTEGER NOT NULL,
                mode TEXT NOT NULL,                    -- 表格 / 版面 / 双栏 / 扫描件 / 读不到
                text TEXT NOT NULL DEFAULT '',
                tables INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (document_id, page)
            );

            -- 募投进度：从「募集资金存放、管理与实际使用情况的专项报告」里抽出来的。
            --
            -- **这是第一条"读文档的结果喂给另一个功能"的链子。** 甘特图原来缺这条泳道，
            -- 理由是"库里没有这项数据"——那句话是对的（没有表），但**公告里有**，
            -- 而且是结构化的表格：承诺投资额、累计投入、进度%、预定可使用状态日期。
            -- 实测寒武纪那份 21 页的专项报告，两次发行五个项目全在里面，读一次 2 分钱。
            --
            -- 每一行都记着出处（哪份文件的第几页），**因为它是模型读出来的**：
            -- 核不回原文的数在这个产品里没有资格进库。
            CREATE TABLE IF NOT EXISTS fundraising_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
                batch TEXT NOT NULL DEFAULT '',       -- 哪一次发行（2022 年度向特定对象发行…）
                project TEXT NOT NULL,                -- 项目名
                committed REAL,                       -- 承诺投资额（万元）
                invested REAL,                        -- 累计投入（万元）
                progress REAL,                        -- 投入进度 %
                due_on TEXT,                          -- 预定可使用状态日期（可能只到月）
                settled INTEGER NOT NULL DEFAULT 0,   -- 已结项
                source_pages TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                UNIQUE (user_id, company_id, batch, project)
            );

            CREATE INDEX IF NOT EXISTS idx_fundraising_company
                ON fundraising_projects(company_id, due_on);

            CREATE TABLE IF NOT EXISTS research_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                -- 三节各存成一个短句数组。body 由它们拼出来（**拼平的方向只能有一个**），
                -- 老简报这三列是空的，页面回退到 body。
                business TEXT NOT NULL DEFAULT '[]',
                changes TEXT NOT NULL DEFAULT '[]',
                implications TEXT NOT NULL DEFAULT '[]',
                -- 深度报告（联网检索那一版）多出来的东西。老报告这几列是空的，
                -- 页面据此回落到旧版式，不显示空图框。
                kind TEXT NOT NULL DEFAULT 'local',   -- local（只用已归档证据）/ deep（联网）
                cards TEXT NOT NULL DEFAULT '[]',     -- 结论卡，整份报告最先被读到的部分
                sections TEXT NOT NULL DEFAULT '[]',  -- 分章正文
                themes TEXT NOT NULL DEFAULT '[]',    -- 主题与方向，图表靠它
                sources TEXT NOT NULL DEFAULT '[]',   -- 检索到的资料（带分级），引用要能点开
                queries TEXT NOT NULL DEFAULT '[]',   -- 搜了哪几个问题，便于判断是不是搜偏了
                facts TEXT NOT NULL DEFAULT '{}',     -- 生成时库里的那批数字，页面照它画图
                citations TEXT NOT NULL DEFAULT '[]',
                unknowns TEXT NOT NULL DEFAULT '[]',
                source_count INTEGER NOT NULL DEFAULT 0,
                model TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(company_id, version)
            );
            CREATE INDEX IF NOT EXISTS idx_reports_company ON research_reports(company_id, version DESC);

            -- ── 决策闭环 ───────────────────────────────────────────────────
            --
            -- 一家公司在闭环里只能停在**一个**状态上。这张表就是那个状态，
            -- 外加进入这个状态需要用到的两样东西：价格带与仓位计划。
            --
            -- **这张表不复制任何已有的事实。** 投资逻辑在 theses、估值在
            -- valuations、持仓在 trades —— 状态机只判断「这几样齐了没有」，
            -- 不另存一份。复制出来的第二份迟早会跟第一份说的不一样，而那时候
            -- 没人知道该信哪份。
            CREATE TABLE IF NOT EXISTS decision_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                state TEXT NOT NULL DEFAULT 'discovered',
                -- 进入当前状态的时间与当时写下的理由。**理由是必填的**：
                -- 一次说不出所以然的状态推进，复盘时读起来跟没推进一样。
                entered_at TEXT NOT NULL,
                entered_reason TEXT NOT NULL DEFAULT '',
                -- 为什么关注它。状态机的第一格（待研究）就只要这一句。
                watch_reason TEXT NOT NULL DEFAULT '',
                -- 价格带：观察 / 合理 / 理想 / 极端机会，记每一段的**上沿**，从高到低。
                -- 上沿的意思是「跌到这个价就算进了这一段」：写 300，300 算合理区、301 不算。
                -- 存成一个 JSON 是因为它们必须一起改：只改一段会让四段交叠或留空隙，
                -- 而交叠的价格带会让同一个价同时命中两段。
                bands TEXT NOT NULL DEFAULT '{}',
                -- 仓位计划：计划总仓位、首次、二次、三次加仓、暂停条件。
                -- 价格解决赔率，仓位解决判断错误 —— 两者分开存，也分开校验。
                position_plan TEXT NOT NULL DEFAULT '{}',
                -- **这一笔**打算买什么价、买多少。跟 position_plan 不是一回事：
                -- 那个是整只票的总规划，这个是「我现在决定下的这一单」。
                -- 分开是因为纪律判定要的正是后者：成交价离你写下的计划价多远。
                order_plan TEXT NOT NULL DEFAULT '{}',
                -- 最近一次价格触发：命中了哪一段、什么价、哪一天。
                -- **触发只是把它推进「触发检查」，从来不代表该买。**
                last_trigger_band TEXT NOT NULL DEFAULT '',
                last_trigger_price REAL,
                last_trigger_date TEXT,
                -- **每一块各自记自己是什么时候定的，以及依据是哪一期财报。**
                --
                -- 使用者的原话：「在过去正确的记录数字，放在现在就是错的」。
                -- 价格带没有自己的有效期 —— 它由基准每股价值推出，而那个数来自
                -- 某一期财报；那期被新的一期顶掉，这组价格带就跟着过时，
                -- **而它在页面上长得跟今天刚定的一模一样**。
                --
                -- 为什么不用 updated_at：那是整张卡的。今天改一下仓位计划，
                -- updated_at 就动了，而价格带其实还是去年那组 —— 于是唯一一个
                -- 能说明"这组数有多旧"的信号被抹掉了。
                --
                -- 形状 {块名: {set_at, ...出处}}，块名是 bands / position_plan / order_plan。
                -- 存 JSON 而不是三个列：出处字段每块都不一样（价格带要记
                -- base_report_date 和当时的每股价值，仓位计划不需要）。
                block_stamps TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (user_id, company_id)
            );

            -- 真的动手了那一刻记一次。**这不是记账，是决策的结果。**
            --
            -- 「计划内 / 计划外交易」是这整套闭环存在的唯一理由，而它原来查的是
            -- trades 里的 buy —— 2026-09-23 持仓改成「只记股数和成本价」之后，
            -- 账本里再也不会出现 buy，那个指标就**永久变成 0/0 且不报错**。
            --
            -- 所以成交登记挪到这里：你按下单的那一刻填一次实际成交价，
            -- 而不是事后去账本里补一笔流水。一个动作，发生在你真正动手的时候。
            --
            -- **计划价单独存一份快照**，不是事后去卡片上现查：卡片上的计划价
            -- 会被后来的修改改掉，而"我当时计划的是多少"是这条记录的全部意义。
            CREATE TABLE IF NOT EXISTS decision_fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                card_id INTEGER NOT NULL REFERENCES decision_cards(id) ON DELETE CASCADE,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                filled_on TEXT NOT NULL,
                price REAL NOT NULL,
                shares REAL,
                -- 下单那一刻卡上写着的计划，存快照
                planned_price REAL,
                planned_fraction TEXT NOT NULL DEFAULT '',
                -- 成交当时卡片处在哪一格。判"计划内"要用，而卡片状态之后会变。
                state_then TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_decision_fills_company
                ON decision_fills(user_id, company_id);

            CREATE INDEX IF NOT EXISTS idx_decision_cards_state ON decision_cards(user_id, state);

            -- 每一次状态推进都留一行。**退回也留**：把「我从等待买入退回研究中」
            -- 抹掉，等于把自己承认想错了的那一刻抹掉，而那正是复盘最值钱的部分。
            CREATE TABLE IF NOT EXISTS decision_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL REFERENCES decision_cards(id) ON DELETE CASCADE,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                from_state TEXT NOT NULL,
                to_state TEXT NOT NULL,
                -- 谁推的：人工 / 价格触发 / 账本（记了买卖流水）。
                actor TEXT NOT NULL DEFAULT '人工',
                reason TEXT NOT NULL DEFAULT '',
                price_at_move REAL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_decision_transitions_card
                ON decision_transitions(card_id, id DESC);

            -- ── 助理盯盘（assistant.py）───────────────────────────────────────
            --
            -- 每一档价位「现在在不在里面」。**进去那一刻推一次，出来才重新上膛**，
            -- 而出来要比门槛高出一点（回差，见 assistant.HYSTERESIS）——
            -- 否则价格在边上来回蹭，一天能推十次，任何一天响十次的提醒人都会关掉。
            --
            -- 门槛价也存下来：你改了计划价，那就是新的一档，要能重新提醒。
            CREATE TABLE IF NOT EXISTS assistant_watch_state (
                user_id TEXT NOT NULL DEFAULT '__owner__',
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                level TEXT NOT NULL,
                threshold REAL NOT NULL,
                inside INTEGER NOT NULL DEFAULT 0,
                changed_at TEXT NOT NULL,
                PRIMARY KEY (user_id, company_id, level)
            );

            -- 助理说过的每一句话，以及**有没有送到**。
            --
            -- 「以为提醒过了、其实没送到」是这个功能最坏的一种坏法：
            -- 微信那条通道就会接口报成功、人却什么都没收到。所以送不送得出去
            -- 必须落在库里，而不是只在日志里闪一下。
            CREATE TABLE IF NOT EXISTS assistant_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                levels TEXT NOT NULL DEFAULT '[]',
                price REAL,
                price_at TEXT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                delivery TEXT NOT NULL DEFAULT 'pending',
                delivery_error TEXT NOT NULL DEFAULT '',
                delivered_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_assistant_alerts_recent
                ON assistant_alerts(user_id, id DESC);

            -- 每一轮盯盘记一笔。**安静必须是「看过了，没事」，不能是「根本没看」**：
            -- 没有这张表，一个周都没推过消息的助理，你分不清它是真没事还是早就停了。
            CREATE TABLE IF NOT EXISTS assistant_watch_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                started_at TEXT NOT NULL,
                finished_at TEXT,
                watched INTEGER NOT NULL DEFAULT 0,
                priced INTEGER NOT NULL DEFAULT 0,
                alerts INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'running',
                detail TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_assistant_watch_runs_recent
                ON assistant_watch_runs(user_id, id DESC);

            -- 助理对话的动作和记忆：与正式研究共库，重启不丢，按用户隔离。
            CREATE TABLE IF NOT EXISTS assistant_web_messages (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                content TEXT NOT NULL,
                prompt TEXT NOT NULL,
                company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
                company_name TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'running',
                answer TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_assistant_web_recent ON assistant_web_messages(user_id, created_at);

            CREATE TABLE IF NOT EXISTS assistant_actions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                session_key TEXT NOT NULL,
                request_key TEXT NOT NULL,
                operation TEXT NOT NULL,
                company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                payload TEXT NOT NULL DEFAULT '{}',
                original_text TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'running',
                result TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, request_key)
            );
            CREATE TABLE IF NOT EXISTS assistant_memory (
                user_id TEXT NOT NULL DEFAULT '__owner__',
                memory_key TEXT NOT NULL,
                value TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, memory_key)
            );
            CREATE TABLE IF NOT EXISTS assistant_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                threshold REAL,
                direction TEXT NOT NULL DEFAULT 'below',
                reason TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                inside INTEGER NOT NULL DEFAULT 0,
                snapshot TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, company_id, kind, direction)
            );

            -- ── 产业链环节的同行 ───────────────────────────────────────────
            --
            -- 从 earth-atlas 导进来的「A 股代码 → 产业链环节」。
            --
            -- **它是公开参考资料，不按用户隔离**：宁德时代在不在「电芯」这个环节，
            -- 谁看都是同一件事，跟 price_bars、market_universe 同一类。
            --
            -- **跟 industry_chain_* 那五张表是两回事，别合并。** 那一套是使用者
            -- 自己画的底图（节点、连线、核验状态都由他确认），公司位置要 company_id，
            -- 也就是必须先建档；而这张表的用处恰恰是「同环节那几家我没建档的公司
            -- 最近涨跌如何」—— 对照组常常正是没建档的那些。
            CREATE TABLE IF NOT EXISTS chain_segment_members (
                symbol TEXT NOT NULL,
                chain TEXT NOT NULL,
                segment TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                chain_label TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT '',
                segment_label TEXT NOT NULL DEFAULT '',
                what TEXT NOT NULL DEFAULT '',
                -- 每条都带一手出处。**对照组也要能被追问「凭什么说它在这个环节」**。
                source_url TEXT NOT NULL DEFAULT '',
                source_title TEXT NOT NULL DEFAULT '',
                source_quote TEXT NOT NULL DEFAULT '',
                accessed TEXT NOT NULL DEFAULT '',
                imported_at TEXT NOT NULL,
                PRIMARY KEY (symbol, chain, segment)
            );

            CREATE INDEX IF NOT EXISTS idx_chain_members_segment
                ON chain_segment_members(chain, segment);
            """
        )
        # 决策卡：每块各自的时间戳与出处（见建表注释）。老卡片补空，
        # 页面会显示成「不知道什么时候定的」——**那比显示成今天定的诚实**。
        card_columns = {row["name"] for row in conn.execute("PRAGMA table_info(decision_cards)").fetchall()}
        if card_columns and "block_stamps" not in card_columns:
            conn.execute("ALTER TABLE decision_cards ADD COLUMN block_stamps TEXT NOT NULL DEFAULT '{}'")
        task_item_columns = {row["name"] for row in conn.execute("PRAGMA table_info(research_task_items)").fetchall()}
        for column in ("brief", "links", "reports", "brief_source"):
            if task_item_columns and column not in task_item_columns:
                conn.execute(f"ALTER TABLE research_task_items ADD COLUMN {column} TEXT")
        thesis_method_columns = {row["name"] for row in conn.execute("PRAGMA table_info(theses)").fetchall()}
        for column in ("method_key", "method_name"):
            if thesis_method_columns and column not in thesis_method_columns:
                conn.execute(f"ALTER TABLE theses ADD COLUMN {column} TEXT")
        universe_columns = {row["name"] for row in conn.execute("PRAGMA table_info(market_universe)").fetchall()}
        for column in ("ytd_change", "change_60d", "change_5d", "change_20d", "annual_net_profit", "total_shares"):
            if universe_columns and column not in universe_columns:
                conn.execute(f"ALTER TABLE market_universe ADD COLUMN {column} REAL")
        # 快照源被挡时 PE/PB/市值 要靠财务底座推算，推算口径必须留痕
        history_columns = {row["name"] for row in conn.execute("PRAGMA table_info(universe_valuation_history)").fetchall()}
        # 全市场没有可直接取到的区间涨跌，只能自己按日累积收盘价再算
        if history_columns and "close" not in history_columns:
            conn.execute("ALTER TABLE universe_valuation_history ADD COLUMN close REAL")
        for column in ("annual_report_date", "valuation_basis"):
            if universe_columns and column not in universe_columns:
                conn.execute(f"ALTER TABLE market_universe ADD COLUMN {column} TEXT")
        financial_columns = {row["name"] for row in conn.execute("PRAGMA table_info(financial_periods)").fetchall()}
        for column in ("operating_cost", "rnd_expense", "capex", "receivables", "inventory", "interest_bearing_debt"):
            if financial_columns and column not in financial_columns:
                conn.execute(f"ALTER TABLE financial_periods ADD COLUMN {column} REAL")
        thesis_columns = {row["name"] for row in conn.execute("PRAGMA table_info(theses)").fetchall()}
        if thesis_columns and "next_review_date" not in thesis_columns:
            # 复核触发条件原本只有自由文本，补一个可判定到期的日期列
            conn.execute("ALTER TABLE theses ADD COLUMN next_review_date TEXT")
            conn.execute("ALTER TABLE theses ADD COLUMN last_reviewed_at TEXT")
        calendar_columns = {row["name"] for row in conn.execute("PRAGMA table_info(company_calendar_events)").fetchall()}
        if calendar_columns and "id" not in calendar_columns:
            # 老版本的日历表以四字段联合主键存储；收件箱需要稳定的行标识，这里整表迁移一次。
            conn.executescript(
                """
                ALTER TABLE company_calendar_events RENAME TO company_calendar_events_legacy;

                CREATE TABLE company_calendar_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                    category TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    url TEXT,
                    source TEXT NOT NULL,
                    refreshed_at TEXT NOT NULL,
                    inbox_status TEXT NOT NULL DEFAULT '待核验',
                    archived_as TEXT,
                    archived_ref_id INTEGER,
                    handled_at TEXT,
                    UNIQUE (company_id, category, event_date, title)
                );

                INSERT INTO company_calendar_events (company_id, category, event_date, title, detail, url, source, refreshed_at)
                SELECT company_id, category, event_date, title, detail, url, source, refreshed_at FROM company_calendar_events_legacy;

                DROP TABLE company_calendar_events_legacy;

                CREATE INDEX IF NOT EXISTS idx_company_calendar_date ON company_calendar_events(company_id, event_date DESC);
                """
            )
        for column in ("relevance", "relevance_reason", "relevance_source", "relevance_topic", "summary", "classified_at"):
            if calendar_columns and "id" in calendar_columns and column not in calendar_columns:
                conn.execute(f"ALTER TABLE company_calendar_events ADD COLUMN {column} TEXT")
        if calendar_columns and "inbox_status" not in calendar_columns:
            conn.execute("ALTER TABLE company_calendar_events ADD COLUMN inbox_status TEXT NOT NULL DEFAULT '待核验'")
            conn.execute("ALTER TABLE company_calendar_events ADD COLUMN archived_as TEXT")
            conn.execute("ALTER TABLE company_calendar_events ADD COLUMN archived_ref_id INTEGER")
            conn.execute("ALTER TABLE company_calendar_events ADD COLUMN handled_at TEXT")
        thesis_method_columns = {row["name"] for row in conn.execute("PRAGMA table_info(theses)").fetchall()}
        for column in ("method_key", "method_name"):
            if thesis_method_columns and column not in thesis_method_columns:
                conn.execute(f"ALTER TABLE theses ADD COLUMN {column} TEXT")
        universe_columns = {row["name"] for row in conn.execute("PRAGMA table_info(market_universe)").fetchall()}
        # v43：趋势面的列。老库要补上，否则趋势那三套策略永远「暂不可用」，
        # 而原因看起来像"数据没同步"而不是"列不存在"。
        sentiment_columns = {row["name"] for row in conn.execute("PRAGMA table_info(market_sentiment)").fetchall()}
        if sentiment_columns and "turnover_rate" not in sentiment_columns:
            conn.execute("ALTER TABLE market_sentiment ADD COLUMN turnover_rate REAL")
        for column in ("rising_days", "stage_gain", "stage_turnover",
                       "above_ma60", "new_high_level", "volume_days"):
            if universe_columns and column not in universe_columns:
                conn.execute(f"ALTER TABLE market_universe ADD COLUMN {column} REAL")
        for column in ("trend_source", "trend_as_of"):
            if universe_columns and column not in universe_columns:
                conn.execute(f"ALTER TABLE market_universe ADD COLUMN {column} TEXT")
        for column, kind in (("annual_roe", "REAL"), ("annual_gross_margin", "REAL"),
                             ("dividend_yield", "REAL"), ("dividend_per_10", "REAL"),
                             ("dividend_period", "TEXT"), ("sw_level1", "TEXT"), ("sw_level2", "TEXT")):
            if universe_columns and column not in universe_columns:
                conn.execute(f"ALTER TABLE market_universe ADD COLUMN {column} {kind}")
        trade_columns = {row["name"] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
        for column in ("weight_percent", "cash_amount"):
            if trade_columns and column not in trade_columns:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {column} REAL")
        # **老库必须整表重建。** shares/price 上的 NOT NULL 会挡住现金分红
        # （没有股数与价格）和送股（没有价格）。SQLite 不能 ALTER COLUMN 放开约束，
        # 只能建新表搬过去。不做这一步的话，新增的三种记录类型在**任何已存在的库**上
        # 都直接报 IntegrityError —— 也就是对所有真实用户都是坏的，只有全新安装能用。
        trade_notnull = {row["name"] for row in conn.execute("PRAGMA table_info(trades)").fetchall()
                         if row["notnull"] and row["name"] in ("shares", "price")}
        if trade_notnull:
            conn.executescript(
                """
                ALTER TABLE trades RENAME TO trades_legacy;

                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY,
                    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
                    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                    thesis_id INTEGER REFERENCES theses(id) ON DELETE SET NULL,
                    side TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    shares REAL,
                    price REAL,
                    fee REAL NOT NULL DEFAULT 0,
                    weight_percent REAL,
                    cash_amount REAL,
                    rationale TEXT NOT NULL,
                    expectation TEXT NOT NULL DEFAULT '',
                    review_due TEXT,
                    thesis_claim_snapshot TEXT NOT NULL DEFAULT '',
                    thesis_status_snapshot TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                INSERT INTO trades (id, portfolio_id, company_id, thesis_id, side, trade_date,
                                    shares, price, fee, weight_percent, cash_amount, rationale,
                                    expectation, review_due, thesis_claim_snapshot,
                                    thesis_status_snapshot, created_at)
                SELECT id, portfolio_id, company_id, thesis_id, side, trade_date,
                       shares, price, fee, weight_percent, cash_amount, rationale,
                       expectation, review_due, thesis_claim_snapshot,
                       thesis_status_snapshot, created_at
                FROM trades_legacy;

                DROP TABLE trades_legacy;

                CREATE INDEX IF NOT EXISTS idx_trades_portfolio ON trades(portfolio_id, trade_date, id);
                CREATE INDEX IF NOT EXISTS idx_trades_company ON trades(company_id, trade_date, id);
                """
            )
        portfolio_columns = {row["name"] for row in conn.execute("PRAGMA table_info(portfolios)").fetchall()}
        if portfolio_columns and "amount_mode" not in portfolio_columns:
            conn.execute("ALTER TABLE portfolios ADD COLUMN amount_mode TEXT NOT NULL DEFAULT 'full'")
        # shares/price 由 NOT NULL 放开为可空：ratio 模式下它们本来就不该有值。
        # SQLite 不支持 ALTER COLUMN，老库靠整表重建；这里只对新库生效，
        # 老库继续按 full 模式跑（它们本来就都有值），不影响。
        job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(background_jobs)").fetchall()}
        for column in ("credits", "tokens", "metered"):
            if job_columns and column not in job_columns:
                conn.execute(f"ALTER TABLE background_jobs ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
        if job_columns and "result_json" not in job_columns:
            conn.execute("ALTER TABLE background_jobs ADD COLUMN result_json TEXT")
        news_columns = {row["name"] for row in conn.execute("PRAGMA table_info(news_items)").fetchall()}
        if news_columns and "read_at" not in news_columns:
            conn.execute("ALTER TABLE news_items ADD COLUMN read_at TEXT")
        snapshot_columns = {row["name"] for row in conn.execute("PRAGMA table_info(market_snapshots)").fetchall()}
        if "total_market_cap" not in snapshot_columns:
            conn.execute("ALTER TABLE market_snapshots ADD COLUMN total_market_cap REAL")
        # v35：候选初筛的结构落成列。模型返回的本来就是 verdict + reasons + concerns，
        # 老版本把后两个拼进 note 一个文本字段（拼平之后拆不回来），
        # 并把 verdict 塞进 status —— 塞的是「深入研究」「排除」，
        # 而全系统认的状态只有「待看/已建档/已排除」，于是下拉框对不上、计数也数不到。
        # 「值不值得花时间」是模型的判断，「我处理到哪一步」是人的动作，两件事各占一列。
        item_columns = {row["name"] for row in conn.execute("PRAGMA table_info(research_task_items)").fetchall()}
        briefing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(daily_briefings)").fetchall()}
        if briefing_columns and "context" not in briefing_columns:
            conn.execute("ALTER TABLE daily_briefings ADD COLUMN context TEXT NOT NULL DEFAULT '{}'")
        evidence_columns = {row["name"] for row in conn.execute("PRAGMA table_info(evidences)").fetchall()}
        for column in ("polarity_reason", "polarity_source"):
            if evidence_columns and column not in evidence_columns:
                conn.execute(f"ALTER TABLE evidences ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        report_columns = {row["name"] for row in conn.execute("PRAGMA table_info(research_reports)").fetchall()}
        for column in ("business", "changes", "implications",
                       "cards", "sections", "themes", "sources", "queries"):
            if report_columns and column not in report_columns:
                conn.execute(
                    f"ALTER TABLE research_reports ADD COLUMN {column} TEXT NOT NULL DEFAULT '[]'")
        if report_columns and "kind" not in report_columns:
            conn.execute("ALTER TABLE research_reports ADD COLUMN kind TEXT NOT NULL DEFAULT 'local'")
        if report_columns and "facts" not in report_columns:
            conn.execute("ALTER TABLE research_reports ADD COLUMN facts TEXT NOT NULL DEFAULT '{}'")
        for column, blank in (("verdict", "''"), ("reasons", "'[]'"), ("concerns", "'[]'"),
                              ("assessment", "'[]'"), ("assessed_at", "''"),
                              ("conclusion", "''")):
            if item_columns and column not in item_columns:
                conn.execute(
                    f"ALTER TABLE research_task_items ADD COLUMN {column} TEXT NOT NULL DEFAULT {blank}")
        _canonicalise_task_item_status(conn)
        _split_model_note_from_user_note(conn)
        _backfill_thesis_price(conn)
        # v56：**记下"这条公告已经比对过认错条件"，无论有没有命中。**
        #
        # 原来判断"比过没比过"是看它在不在 counter_hits 里 —— 而只有**命中**才会
        # 落一行。于是比对了 40 条、0 命中之后，那 40 条在库里跟没比过一模一样：
        #
        #   · 页面上那个「还有 N 条没比对过」永远不减（线上实测：跑完还是 103）
        #   · 定时任务每天拿同一批 40 条重跑一遍，**每天真金白银地烧一次积分**，
        #     而且永远不收敛
        #
        # 所以另记一列。命中与否是结论，比没比过是事实，两件事不能共用一个存放处。
        event_columns = {row["name"] for row in
                         conn.execute("PRAGMA table_info(company_calendar_events)").fetchall()}
        if event_columns and "counter_checked_at" not in event_columns:
            conn.execute("ALTER TABLE company_calendar_events ADD COLUMN counter_checked_at TEXT")
        _scope_migration(conn)
        # 这条索引只能建在 _scope_migration 之后：老库在迁移前还没有 user_id 列
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_user ON companies(user_id, name)")
        _remove_generated_demo_archive(conn)
        _market_by_symbol_migration(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.execute("PRAGMA journal_mode = WAL")  # 读写并发；备份仍走 SQLite 的 backup API

        # **自动补列：跟 PG 那边同一份判据。**
        #
        # `CREATE TABLE IF NOT EXISTS` 对已存在的表什么都不做，所以往一张
        # 已有的表加列时，光改建表脚本在老库上不会生效。PG 那边有
        # `_add_missing_columns` 自动对齐，而 SQLite 这边一直**靠人手写**
        # ——上面那 38 条 ALTER 就是，覆盖 16 张表。
        #
        # 忘写不会报错、不会有测试变红，只在某次还原老备份时冒出来一句
        # `no such column`。今天加 documents.tags 我就忘了。
        #
        # 备份文件永远是 SQLite（见 backup.py），而还原代码里写着
        # 「initialize_database()  # 老版本备份恢复后补齐结构」——
        # **那句注释在 PG 上是真的，在 SQLite 上一直是假的。** 现在它是真的了。
        #
        # 上面那些手写 ALTER 保留不动：它们除了加列还做数据回填
        # （比如 industry_source 要按 industry 的值回填），那不是自动补列该管的事。
        _sqlite_add_missing_columns(conn)

def _backfill_thesis_price(conn) -> None:
    """v45：给老的投资逻辑回填「写下时的股价」。

    **回填要标明是推算的。** 新记录是当场记的，老记录只能从日线里找写下那天
    最近的一根收盘价——两者可信度不一样，混在一起会让人以为老记录也是当场记的。
    归因页会把「推算」两个字带出去。

    **两条后端都要跑。** 只挂在 SQLite 的迁移阶梯上，PG 上就永远不会发生，
    而代码看起来是"已经修好了"——这个坑本仓踩过一次（_split_model_note_from_user_note）。
    """
    try:
        rows = conn.execute(
            "SELECT t.id, t.created_at, c.symbol FROM theses t "
            "JOIN companies c ON c.id = t.company_id "
            "WHERE t.price_at_write IS NULL").fetchall()
    except Exception as exc:                    # noqa: BLE001 — 只容忍"列还没建出来"
        if "price_at_write" not in str(exc):
            raise
        return
    for row in rows:
        # 取写下那天或之前最近的一根收盘价。**不用之后的**——
        # 那等于用你当时看不到的价格来评判你当时的判断。
        bar = conn.execute(
            "SELECT close FROM price_bars WHERE symbol = ? AND trade_date <= ? "
            "ORDER BY trade_date DESC LIMIT 1",
            (row["symbol"], str(row["created_at"])[:10])).fetchone()
        if bar and bar["close"] is not None:
            conn.execute(
                "UPDATE theses SET price_at_write = ?, price_source = ? WHERE id = ?",
                (bar["close"], "从日线回填（推算）", row["id"]))


def _canonicalise_task_item_status(conn) -> None:
    """把老库里的任务条目状态搬回系统认得的三个值。

    ## 症状：进度条永远是 0/30，而其中 11 项其实早就有结论了

    v35 之前，候选初筛把模型的 verdict 直接塞进了 status——塞的是「深入研究」
    「排除」，而全系统认的状态只有「待看 / 已建档 / 已排除」。代码那一侧后来
    改对了（见 repository 的 _VERDICT_STATUS），**但库里已经写下的行没人回填**，
    于是它们对谁都不存在：
      - 任务的三个计数一个也数不到它们（实测 30 项里有 11 项被算成 0）
      - 条目上的下拉框选不中当前值，显示成第一项
    而页面不会报任何错——它只是安静地少数了三分之一。

    ## 搬法

    「排除」和「已排除」是同一件事，直接换名。
    「深入研究」不是人的动作，是模型的判断——它属于 verdict 那一列。所以状态
    退回「待看」（人确实还没处理），同时把判断补进 verdict，免得搬完丢信息。
    """

    try:
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM research_task_items WHERE status IN ('深入研究', '排除')"
        ).fetchone()
    except Exception:
        return  # 老库还没有这张表
    if not rows or not rows["n"]:
        return
    conn.execute("UPDATE research_task_items SET status = '已排除' WHERE status = '排除'")
    conn.execute(
        "UPDATE research_task_items SET verdict = '值得深入' WHERE status = '深入研究' AND (verdict IS NULL OR verdict = '')"
    )
    conn.execute("UPDATE research_task_items SET status = '待看' WHERE status = '深入研究'")


def _split_model_note_from_user_note(conn) -> None:
    """v41：把模型写的初筛结论从 note 里搬到 conclusion。

    **两条后端都要跑。** 第一版只挂在 SQLite 的迁移阶梯上，而本地和线上都是
    PostgreSQL —— 迁移静静地没有发生，页面上模型那段还躺在输入框里，
    而代码看起来是"已经修好了"。数据迁移不能只写在建表那条路上。

    原来两者共用 note。存量数据里模型那段几百字就躺在「你自己写的结论」那一栏，
    页面上是个单行输入框——**内容看不到，想写自己的还得先删掉它**。

    认领判据是结尾那句「——由模型 X 初筛，未经人工确认」，那是写入时自己加的，
    人不会这么写。认不出来的一律不动：宁可漏搬，也不能把人手写的东西挪走。
    顺便按当初拼进去的「支持：」「待核实：」把结构拆回来，老条目也能按块渲染。
    """
    # **LIKE 的模式必须走参数，不能写成字面量。** 写成
    # `note LIKE '%——由模型%'` 在 PG 上会炸：pgbackend 把 `?` 翻成 `%s` 之后，
    # psycopg2 会把 SQL 里所有的 `%` 都当成参数占位符，于是报
    # 「tuple index out of range」——一个跟 LIKE 毫无关系的错。
    # 第一版还用 `except Exception: return` 把它吞了，结果是迁移静静地没发生，
    # 而代码看起来一切正常。
    try:
        rows = conn.execute(
            "SELECT id, note FROM research_task_items "
            "WHERE conclusion = '' AND note LIKE ?", ("%——由模型%",)).fetchall()
    except Exception as exc:     # noqa: BLE001 — 只容忍"列还没建出来"
        if "conclusion" not in str(exc):
            raise
        return
    for row in rows:
        text = str(row["note"])
        reasons: list[str] = []
        concerns: list[str] = []
        head: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("支持："):
                reasons = [x for x in line[3:].split("；") if x.strip()]
            elif line.startswith("待核实："):
                concerns = [x for x in line[4:].split("；") if x.strip()]
            elif line.startswith("——由模型"):
                continue
            elif line:
                head.append(line)
        conn.execute(
            "UPDATE research_task_items SET conclusion = ?, note = '', "
            "reasons = CASE WHEN reasons = '[]' THEN ? ELSE reasons END, "
            "concerns = CASE WHEN concerns = '[]' THEN ? ELSE concerns END "
            "WHERE id = ?",
            ("\n".join(head), json.dumps(reasons, ensure_ascii=False),
             json.dumps(concerns, ensure_ascii=False), row["id"]))


def _scope_migration(conn: sqlite3.Connection) -> None:
    """v30：数据按用户隔离。存量数据全部盖上站主域（'__owner__'）。

    简单表 ALTER ADD COLUMN 就够；带全局唯一约束的 7 张表必须整表重建——
    UNIQUE(symbol) 会挡住第二个用户研究茅台，而 SQLite 改不了约束。

    这里的 DDL 是**冻结的 v30 形状**，与上面的基础建表刻意重复：迁移要永远
    产出 v30，哪怕基础结构以后继续演进（那会是 v31+ 的迁移，不该影响这段）。

    RENAME 时开 legacy_alter_table：SQLite 3.25+ 的 RENAME 会顺手把子表外键
    引用改到新名字上——companies 有十来张子表，那样一改再 DROP 掉 legacy，
    子表的外键就全部指向一张不存在的表。legacy 模式保持子表引用原名不动，
    新表用回原名后引用自然接上，数据一行不搬。
    """

    probe = {row["name"] for row in conn.execute("PRAGMA table_info(companies)").fetchall()}
    if not probe or "user_id" in probe:
        return                                     # 新库或已迁移

    for table in ("research_tasks", "screen_runs", "inbox_corrections", "background_jobs"):
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if columns and "user_id" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT NOT NULL DEFAULT '__owner__'")

    rebuilds: tuple[tuple[str, str, str], ...] = (
        ("companies",
         """CREATE TABLE companies (
                id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT '待确认',
                industry TEXT NOT NULL,
                industry_source TEXT NOT NULL DEFAULT '待补充',
                description TEXT NOT NULL DEFAULT '',
                watch_group TEXT NOT NULL DEFAULT '观察池',
                is_watched INTEGER NOT NULL DEFAULT 1,
                valuation_percentile INTEGER,
                roe_trend TEXT NOT NULL DEFAULT '待补充',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (user_id, symbol)
            )""",
         "id, symbol, name, exchange, industry, industry_source, description, watch_group, "
         "is_watched, valuation_percentile, roe_trend, created_at, updated_at"),
        ("portfolios",
         """CREATE TABLE portfolios (
                id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                name TEXT NOT NULL,
                objective TEXT NOT NULL DEFAULT '',
                amount_mode TEXT NOT NULL DEFAULT 'full',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (user_id, name)
            )""",
         "id, name, objective, amount_mode, created_at, updated_at"),
        ("news_feeds",
         """CREATE TABLE news_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                key TEXT NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                builtin INTEGER NOT NULL DEFAULT 0,
                last_ok_at TEXT,
                last_error TEXT NOT NULL DEFAULT '',
                item_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE (user_id, key)
            )""",
         "id, key, name, url, enabled, builtin, last_ok_at, last_error, item_count, created_at"),
        ("news_items",
         """CREATE TABLE news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                fingerprint TEXT NOT NULL,
                feed_key TEXT NOT NULL,
                feed_name TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL,
                company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
                match_confidence TEXT NOT NULL DEFAULT '未匹配',
                match_reason TEXT NOT NULL DEFAULT '',
                match_source TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '待确认',
                read_at TEXT,
                archived_ref_id INTEGER,
                fetched_at TEXT NOT NULL,
                handled_at TEXT,
                UNIQUE (user_id, fingerprint)
            )""",
         "id, fingerprint, feed_key, feed_name, title, url, summary, published_at, company_id, "
         "match_confidence, match_reason, match_source, status, archived_ref_id, fetched_at, handled_at"),
        ("daily_briefings",
         """CREATE TABLE daily_briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                as_of TEXT NOT NULL,
                headline TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '{}',
                actions TEXT NOT NULL DEFAULT '[]',
                gaps TEXT NOT NULL DEFAULT '[]',
                model TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE (user_id, as_of)
            )""",
         "id, as_of, headline, body, actions, gaps, model, created_at"),
        ("rule_terms",
         """CREATE TABLE rule_terms (
                user_id TEXT NOT NULL DEFAULT '__owner__',
                term TEXT NOT NULL,
                relevance TEXT NOT NULL,
                topic TEXT NOT NULL DEFAULT '自定义',
                note TEXT NOT NULL DEFAULT '',
                hits INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, term)
            )""",
         "term, relevance, topic, note, hits, created_at"),
        ("screen_strategies",
         """CREATE TABLE screen_strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '__owner__',
                key TEXT NOT NULL,
                name TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                provenance TEXT NOT NULL DEFAULT '',
                biases TEXT NOT NULL DEFAULT '[]',
                rules TEXT NOT NULL,
                sort_field TEXT NOT NULL,
                sort_desc INTEGER NOT NULL DEFAULT 1,
                sort_label TEXT NOT NULL DEFAULT '',
                forked_from TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (user_id, key)
            )""",
         "id, key, name, summary, provenance, biases, rules, sort_field, sort_desc, "
         "sort_label, forked_from, created_at, updated_at"),
    )

    # **重建前必须：commit → 关外键 → 开 legacy_alter_table，并逐项验证。**
    #
    # 两个都是实测踩过的坑：
    # 1. 这两个 PRAGMA 在已开启的事务里都会被**静默忽略**——走到这里时连接上正压着
    #    前半段迁移的未提交事务，所以先 commit。
    # 2. `foreign_keys=ON 时，RENAME 会无条件改写子表的 REFERENCES 指向新名字`，
    #    legacy_alter_table 形同虚设（读回来是 1 也没用）。于是子表全指向 companies_v29，
    #    DROP 掉它之后外键悬空，下一张表 DROP 时要解析全部 schema，报
    #    「no such table: companies_v29」——报错处离出错处隔着一整张表，极难看出来。
    #    这正是 SQLite 官方「改表结构」流程要求先 PRAGMA foreign_keys=OFF 的原因。
    # 完事后 foreign_key_check 兜底，再把两个开关复原。
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 0:
        raise RuntimeError("foreign_keys 没能关闭（多半是还有未提交事务），中止迁移")
    conn.execute("PRAGMA legacy_alter_table = ON")
    if conn.execute("PRAGMA legacy_alter_table").fetchone()[0] != 1:
        raise RuntimeError("legacy_alter_table 没能开启，中止迁移")
    try:
        for table, create_sql, columns in rebuilds:
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if not existing or "user_id" in existing:
                continue
            conn.execute(f"ALTER TABLE {table} RENAME TO {table}_v29")
            conn.execute(create_sql)
            conn.execute(
                f"INSERT INTO {table} ({columns}, user_id) "
                f"SELECT {columns}, '__owner__' FROM {table}_v29")
            conn.execute(f"DROP TABLE {table}_v29")
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.commit()                                   # 外键开关也要在事务外才拨得动
        conn.execute("PRAGMA foreign_keys = ON")

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"隔离迁移后外键校验不过：{[tuple(v) for v in violations[:5]]}")

    # 重建会带走同表的索引，补回来
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_companies_user ON companies(user_id, name);
        CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_news_company ON news_items(company_id, published_at DESC);
        """
    )


def schema_version(conn=None) -> int:
    """库的结构版本；备份与恢复据此判断是否兼容。

    SQLite 用 PRAGMA user_version（存在文件头里，随文件一起拷走，正是备份需要的）；
    PG 没有这个东西，存在 stocks.schema_meta 里。
    """

    if is_postgres():
        owned = conn or connection()
        try:
            row = owned.execute(
                f"SELECT value FROM {pgbackend.SCHEMA}.schema_meta WHERE key = 'version'").fetchone()
            return int(row["value"]) if row else 0
        finally:
            if conn is None:
                owned.close()
    if conn is not None:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    with connection() as owned:
        return int(owned.execute("PRAGMA user_version").fetchone()[0])


def integrity_errors() -> tuple[type[Exception], ...]:
    """两个后端的「违反约束」异常。

    唯一约束撞了要回 4xx（"这个代码已经有了"），不能回 500（"服务器坏了"）——
    前者用户看得懂并且知道怎么办，后者只会让人以为是我们的问题。
    捕获时写成 `except integrity_errors()`，换后端不用改捕获点。
    """
    errors: tuple[type[Exception], ...] = (sqlite3.IntegrityError,)
    if is_postgres():
        try:
            import psycopg2
            errors = (*errors, psycopg2.IntegrityError)
        except ImportError:
            pass
    return errors


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _remove_generated_demo_archive(conn: sqlite3.Connection) -> None:
    """Remove only the fabricated archive created by versions before StockSDK integration."""

    conn.execute(
        "DELETE FROM companies WHERE description LIKE '示例档案：%' AND symbol IN ('600000', '000001', '300001')"
    )


# v32 要按 symbol 重建的五张表：(表名, 除归属键之外的自然键列)。
# 自然键决定去重时保留哪一行——同一只票在多个用户下各存了一份，合并时必须
# 按「同一天同一来源只留一条」来收，否则主键冲突。
_MARKET_TABLES_V32 = (
    ("market_snapshots", ()),                       # 有自增 id，不需要额外去重键
    ("price_bars", ("trade_date", "source")),
    ("financial_periods", ("report_date", "source")),
    ("valuation_points", ("metric", "point_date", "source")),
    ("company_profiles", ()),                       # symbol 就是主键
)


def _market_by_symbol_migration(conn: sqlite3.Connection) -> None:
    """v32：行情/财务/简况从 company_id 改挂 symbol，全局共享一份。

    **为什么要重建整张表而不是加一列。** 归属键从 company_id 换成 symbol，
    主键跟着变（price_bars 的主键是 (company_id, trade_date, source)）。
    SQLite 改不了主键，只能建新表搬过去；而搬的过程正好是去重的机会——
    两个用户各存一份的同一天 K 线，在新表里会撞主键。

    去重规则：同一个 (symbol, 自然键) 只留一条，取 rowid 最大的那条（最后写入的）。
    这些是可以重新同步回来的来源数据，选错一条的代价是一次刷新，不是丢记录。

    注意 PRAGMA 的两个坑（v30 那次踩过）：foreign_keys=ON 时 RENAME 会连带改写
    子表的外键；而这两个 PRAGMA 在事务里是静默失效的，必须先 commit。
    """
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= 32:
        return
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(price_bars)").fetchall()}
    if not columns or "symbol" in columns:
        return                          # 新库：建表时就是 symbol，没有可迁的

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 0:
        raise RuntimeError("关不掉外键约束，迁移会把子表的外键改坏，中止")

    try:
        for table, natural in _MARKET_TABLES_V32:
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if not existing or "symbol" in existing:
                continue
            keep = [c for c in existing if c != "company_id"]
            key = ["symbol", *natural]

            conn.execute(f"ALTER TABLE {table} RENAME TO {table}_v31")
            conn.executescript(_table_ddl(table))

            # 从旧表带出 symbol：company_id → companies.symbol
            select_cols = ", ".join(f"old.{c}" for c in keep)
            group_by = ", ".join(["c.symbol", *(f"old.{c}" for c in natural)])
            conn.execute(f"""
                INSERT INTO {table} (symbol, {", ".join(keep)})
                SELECT c.symbol, {select_cols}
                FROM {table}_v31 old
                JOIN companies c ON c.id = old.company_id
                WHERE old.rowid IN (
                    SELECT MAX(inner_old.rowid) FROM {table}_v31 inner_old
                    JOIN companies ic ON ic.id = inner_old.company_id
                    GROUP BY {", ".join(["ic.symbol", *(f"inner_old.{c}" for c in natural)])}
                )
            """) if natural else conn.execute(f"""
                INSERT INTO {table} (symbol, {", ".join(keep)})
                SELECT c.symbol, {select_cols}
                FROM {table}_v31 old
                JOIN companies c ON c.id = old.company_id
            """)
            conn.execute(f"DROP TABLE {table}_v31")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _table_ddl(table: str) -> str:
    """从建表脚本里抠出这一张表的 CREATE TABLE + 它的索引。

    重建表时要用**当前版本**的定义，不能手抄一份——手抄的那份迟早跟真定义漂开，
    而漂开的表现是「迁移完少了一列」，要到用到那列时才发现。
    """
    import re

    script = _SCHEMA_SQL
    block = re.search(rf"(CREATE TABLE IF NOT EXISTS {table} \(.*?\n\s*\);)", script, re.S)
    if not block:
        raise RuntimeError(f"建表脚本里找不到 {table}")
    parts = [block.group(1)]
    for index in re.finditer(rf"(CREATE INDEX IF NOT EXISTS \w+ ON {table}\([^;]*\);)", script):
        parts.append(index.group(1))
    return "\n".join(parts)


def _market_by_symbol_migration_pg(conn, run) -> None:
    """v32 的 PG 版：行情/财务/简况从 company_id 改挂 symbol。

    PG 这边不能沿用 SQLite 那套「建新表搬过去」——那是因为 SQLite 改不了主键。
    PG 可以直接 ALTER，所以就地改：加列 → 回填 → 去重 → 换主键 → 删旧列。

    **顺序不能变。** 先去重再设 NOT NULL 和主键：两个用户各存了一份同一天的 K 线，
    不先收掉就会在建主键那步失败，而那时表已经改了一半。
    """
    schema = pgbackend.SCHEMA

    def columns_of(table: str) -> set[str]:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s", (schema, table)).fetchall()
        return {r["column_name"] for r in rows}

    for table, natural in _MARKET_TABLES_V32:
        existing = columns_of(table)
        # **判据是「还有没有 company_id」，不是「有没有 symbol」。**
        # 原来写成「有 symbol 就跳过」，而上一轮跑到 market_snapshots 时在删列那步
        # 失败了（策略还引用着 company_id）——symbol 已经加上、company_id 还在。
        # 重跑时这张表整个被跳过，那一列永远留着，每次写快照都撞 NOT NULL，
        # 于是「实时行情快照」连续失败 24 次没人发现。
        # 半途失败的迁移必须能重跑接上，所以每一步都做成可重复的。
        if not existing or "company_id" not in existing:
            continue

        # 老策略是按 company_id 写的，不先撤掉，删列那步会被它挡住
        # （PG 会说 "policy scope_isolation depends on column company_id"）。
        # 这几张表从此全局共享，本来就不该再有策略。
        run(f"DROP POLICY IF EXISTS scope_isolation ON {schema}.{table}")
        run(f"ALTER TABLE {schema}.{table} DISABLE ROW LEVEL SECURITY")
        if "symbol" not in existing:
            run(f"ALTER TABLE {schema}.{table} ADD COLUMN symbol TEXT")
        run(f"""UPDATE {schema}.{table} t SET symbol = c.symbol
                FROM {schema}.companies c WHERE c.id = t.company_id""")
        # 回填不到的（公司已删、外键是 SET NULL 的那种）没有归属，直接丢
        run(f"DELETE FROM {schema}.{table} WHERE symbol IS NULL")

        if natural:
            # 同一 (symbol, 自然键) 只留一条：取 ctid 最大的，也就是最后写入的那条。
            keys = ", ".join(["symbol", *natural])
            run(f"""DELETE FROM {schema}.{table} a
                    WHERE a.ctid <> (SELECT max(b.ctid) FROM {schema}.{table} b
                                     WHERE {" AND ".join(f"b.{k} = a.{k}" for k in ["symbol", *natural])})""")
        elif table == "company_profiles":
            run(f"""DELETE FROM {schema}.{table} a
                    WHERE a.ctid <> (SELECT max(b.ctid) FROM {schema}.{table} b WHERE b.symbol = a.symbol)""")

        # 回填不到的填空串再设非空：重跑时可能已经有一批 symbol 是好的、
        # 另一批还是 NULL（上一轮半途挂了），直接 SET NOT NULL 会失败。
        run(f"UPDATE {schema}.{table} SET symbol = \'\' WHERE symbol IS NULL")
        run(f"ALTER TABLE {schema}.{table} ALTER COLUMN symbol SET NOT NULL")

        # 换主键。旧主键的名字由 PG 自动生成，从系统表里问出来而不是猜。
        pk = conn.execute(
            "SELECT conname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = %s AND t.relname = %s AND c.contype = 'p'",
            (schema, table)).fetchone()
        if pk:
            run(f"ALTER TABLE {schema}.{table} DROP CONSTRAINT {pk['conname']}")
        if natural:
            run(f"ALTER TABLE {schema}.{table} ADD PRIMARY KEY (symbol, {', '.join(natural)})")
        elif table == "company_profiles":
            run(f"ALTER TABLE {schema}.{table} ADD PRIMARY KEY (symbol)")
        elif "id" in existing:
            run(f"ALTER TABLE {schema}.{table} ADD PRIMARY KEY (id)")

        run(f"ALTER TABLE {schema}.{table} DROP COLUMN company_id")
        logger.info("v32：%s 已改按 symbol 存", table)
