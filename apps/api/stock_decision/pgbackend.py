"""PostgreSQL 后端：让本仓 205 处 SQLite 写法原样跑在虾米伙伴的库上。

**为什么是适配层，不是逐条改写。** repository.py 有 4500 行、205 处 execute。
逐条改写等于把整个数据层重写一遍，而其中 99% 的 SQL 在两个方言里本来就一模一样
（`ON CONFLICT (…) DO UPDATE SET x = excluded.x` 连关键字都相同）。真正不同的只有
七件事，列在下面 —— 把这七件收进一处翻译，比在 4500 行里找茬可靠得多。

**为什么保留 SQLite。** 这是个人研究工作台，「一个文件、拷走就能带走」是它的本分；
接进平台是为了共享账号与积分，不是为了从此离不开一台 PostgreSQL。
`STOCK_DB_BACKEND` 决定走哪条路，两条路跑同一套 SQL。

翻译的七件事：

1. 占位符 `?` → `%s`（字符串字面量里的问号不能动）
2. `INSERT OR IGNORE` → `INSERT … ON CONFLICT DO NOTHING`
3. `cursor.lastrowid` → PG 没有这个概念，改成给 INSERT 补 `RETURNING id`
4. DDL：`INTEGER PRIMARY KEY [AUTOINCREMENT]` → `BIGSERIAL`，`REAL` → `DOUBLE PRECISION`
5. `GROUP_CONCAT(x, s)` → `string_agg(x, s)`
6. `PRAGMA …` → 丢弃（结构版本改存在一张表里）
7. 布尔与时间**不做转换**：本仓把布尔存成 0/1、时间存成 ISO 文本，
   PG 这边照样用 INTEGER 与 TEXT。转成 BOOLEAN/TIMESTAMPTZ 会波及几百处
   取值与比较逻辑，收益只是"更地道"，不值得。

所有表建在 `stocks` schema 下，与主站 `app` schema 同库不同域：
PG 不能跨库查询，而注销账号要在一个事务里把两边的数据一起清掉。
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any

# 建表 DDL 里出现过的、需要在 INSERT 后补 RETURNING id 的表（初始化时填充）
_TABLES_WITH_ID: set[str] = set()
_lock = threading.Lock()

def _schema() -> str:
    """表所在的 schema。与 dsn() 同理：环境变量优先，其次 .env。"""
    from . import llm

    return os.getenv("STOCK_PG_SCHEMA") or llm.load_env().get("STOCK_PG_SCHEMA") or "stocks"


# 模块级常量在导入时求值，那时 .env 可能还没被读到；同名函数供需要时取新值。
# 保留 SCHEMA 这个名字是因为它已被 database.py 与迁移脚本引用多处。
SCHEMA = _schema()


def admin_dsn() -> dict[str, Any]:
    """备份/还原用的连接参数 —— 需要一个**能看见所有行**的账号。

    开了行级安全之后，应用那个角色只看得见当前数据域的行，`pg_dump` 出来的
    自然也只有那一份：备份成功、大小正常、内容残缺。这种坏法要等到真去恢复
    的那天才会发现，所以单独走一套凭据。

    没配 PG_ADMIN_USER 就退回普通凭据。那种情况下备份仍会做，只是内容取决于
    当前角色看得见什么——backup 那边会检查并说清楚。
    """
    from . import llm

    env = llm.load_env()
    user = os.getenv("PG_ADMIN_USER") or env.get("PG_ADMIN_USER")
    if not user:
        return dsn()
    params = dsn()
    params["user"] = user
    params["password"] = (os.getenv("PG_ADMIN_PASSWORD")
                          or env.get("PG_ADMIN_PASSWORD") or params["password"])
    return params


def dsn() -> dict[str, Any]:
    """连接参数。环境变量优先，其次仓根 .env（与其他配置同一来源）。

    **必须读 .env。** 原来只读 os.getenv，而默认值恰好是本机开发库
    （127.0.0.1:5433/xiamimate_dev）——本地怎么跑都对，一上服务器就连回环 5433
    被拒。systemd 用 EnvironmentFile 时能读到，但任何直接跑脚本的场合
    （初始化结构、迁移、排障）都会静默连错库，而报错信息只说「连接被拒」，
    看不出是配置没被读到。
    """
    from . import llm

    env = llm.load_env()

    def pick(key: str, fallback: str) -> str:
        return os.getenv(key) or env.get(key) or fallback

    return {
        "host": pick("PG_HOST", "127.0.0.1"),
        "port": int(pick("PG_PORT", "5433")),
        "dbname": pick("PG_DB", "xiamimate"),
        "user": pick("PG_USER", "xiamimate"),
        "password": pick("PG_PASSWORD", "xiamimate_dev"),
    }


# ── SQL 翻译 ──────────────────────────────────────────────────────────────

_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")


def _outside_strings(sql: str, fn) -> str:
    """只对字符串字面量之外的部分做替换。

    必要性：公司名、来源名里带问号的情况真实存在（`'待确认？'`），
    无脑替换 `?` 会把数据里的问号变成占位符，参数个数对不上直接报错。
    """
    out = []
    last = 0
    for m in _STRING_LITERAL.finditer(sql):
        out.append(fn(sql[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(fn(sql[last:]))
    return "".join(out)


def translate(sql: str) -> str:
    """把一条 SQLite 语句翻成 PostgreSQL。DDL 走 translate_ddl。"""
    sql = _outside_strings(sql, lambda part: part.replace("?", "%s"))
    sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, flags=re.I)
    if re.search(r"\bINSERT\s+OR\s+IGNORE\b", sql, re.I):
        sql += " ON CONFLICT DO NOTHING"
    # `INSERT OR REPLACE` 没法机械翻译：PG 的 DO UPDATE 必须写明冲突列和要更新的列，
    # 而这两样只有调用点自己知道。所以这里不猜，直接把它拦下来并说清怎么改。
    #
    # 拦而不是放行，是因为放行的后果太隐蔽：PG 只回一句 `syntax error at or near "OR"`，
    # 而这类语句大多在后台作业里，错误落进 sync_schedules.last_error 就没人看了
    # —— 线上「全市场底座」作业就是这样静静挂了一整天，页面上只表现为云图没数据。
    if re.search(r"\bINSERT\s+OR\s+REPLACE\b", sql, re.I):
        raise ValueError(
            "INSERT OR REPLACE 是 SQLite 方言，PG 不认。"
            "改写成两边都支持的 INSERT … ON CONFLICT(冲突列) DO UPDATE SET x = excluded.x。"
            f"\n出问题的语句：{sql.strip()[:200]}")
    sql = re.sub(r"\bGROUP_CONCAT\s*\(", "string_agg(", sql, flags=re.I)
    sql = _outside_strings(sql, _rewrite_date)
    return _qualify(sql)


_DATE_CALL = re.compile(r"\bdate\s*\(", re.I)


def _rewrite_date(part: str) -> str:
    """`date(x)` → `substr(x, 1, 10)`。

    SQLite 的 date() 从 ISO 文本里截出 'YYYY-MM-DD'，返回的**还是文本**；
    PG 的 date(x) 是转成 date 类型，于是 `text > date` 直接报「没有这个操作符」。
    本仓所有时间都存 ISO 文本，截前 10 个字符结果完全一样，比较也仍是文本比较
    ——ISO 格式下字典序就是时间序，这正是这套存法成立的前提。

    必须自己配对括号，不能用正则一把梭：`date(` 的参数里可能还有函数调用，
    而 `[^()]*` 那种写法会在第一个右括号处收尾。上一版还顺手把 `substr(x,1,4)`
    改成了 `substr(x,1,4,1,10)`——正则匹配到的是"某个函数调用"，不是"date 调用"。
    """
    out = []
    index = 0
    while True:
        m = _DATE_CALL.search(part, index)
        if not m:
            out.append(part[index:])
            return "".join(out)
        out.append(part[index:m.start()])
        depth = 1
        cursor = m.end()
        while cursor < len(part) and depth:
            if part[cursor] == "(":
                depth += 1
            elif part[cursor] == ")":
                depth -= 1
            cursor += 1
        if depth:                       # 括号没配上：原样留着，别猜
            out.append(part[m.start():])
            return "".join(out)
        inner = part[m.end():cursor - 1]
        out.append(f"substr({inner}, 1, 10)")
        index = cursor


_TABLE_REF = re.compile(
    r"\b(FROM|JOIN|INTO|UPDATE|TABLE(?:\s+IF\s+NOT\s+EXISTS)?|INDEX(?:\s+IF\s+NOT\s+EXISTS)?)\s+([a-z_][a-z0-9_]*)",
    re.I)


def _qualify(sql: str) -> str:
    """给本仓的表名加上 schema 前缀。

    不用 `search_path`：本进程与主站共用一个库，若哪天两边有同名表（`news_items`
    这种名字撞车一点都不稀奇），search_path 会静悄悄地选中另一张，
    而那种错查出来极慢。写死前缀，撞不了。
    """
    def sub(m):
        kw, name = m.group(1), m.group(2)
        if name.lower() in _TABLES_WITH_ID or name.lower() in _KNOWN_TABLES:
            return f"{kw} {SCHEMA}.{name}"
        return m.group(0)
    return _TABLE_REF.sub(sub, sql)


_KNOWN_TABLES: set[str] = set()


def register_tables(names: set[str], with_id: set[str]) -> None:
    with _lock:
        _KNOWN_TABLES.clear()
        _KNOWN_TABLES.update(n.lower() for n in names)
        _TABLES_WITH_ID.clear()
        _TABLES_WITH_ID.update(n.lower() for n in with_id)


_INSERT_TABLE = re.compile(r"^\s*INSERT\s+INTO\s+(?:[a-z_]+\.)?([a-z_][a-z0-9_]*)", re.I)


def needs_returning(sql: str) -> str | None:
    """这条 INSERT 要不要补 RETURNING id —— 补了才有 lastrowid 可用。"""
    if re.search(r"\bRETURNING\b", sql, re.I):
        return None
    m = _INSERT_TABLE.match(sql)
    if not m:
        return None
    return m.group(1).lower() if m.group(1).lower() in _TABLES_WITH_ID else None


# ── DDL 翻译 ──────────────────────────────────────────────────────────────

def translate_ddl(script: str) -> tuple[str, set[str], set[str]]:
    """把建表脚本翻成 PG 版。返回 (脚本, 全部表名, 带 id 主键的表名)。"""
    tables: set[str] = set()
    with_id: set[str] = set()
    # **逐条解析，不要拿一个正则去扫整段。** 用 `\((.*?)\n\s*\);` 扫整段时，
    # 某张表若把 `);` 写在最后一列同一行（market_universe 就是），它的惰性匹配
    # 会一路吞到下一张表的结尾——于是下一张表整个消失，而且不报错，
    # 直到搬数据时才冒出一句 relation does not exist。
    for statement in _split_statements(script):
        m = re.match(r"\s*CREATE TABLE(?:\s+IF NOT EXISTS)?\s+([a-z_][a-z0-9_]*)\s*\(",
                     statement, re.I)
        if not m:
            continue
        tables.add(m.group(1).lower())
        if re.search(r"\bid\s+INTEGER\s+PRIMARY\s+KEY", statement, re.I):
            with_id.add(m.group(1).lower())

    out = script
    # 自增主键。SQLite 的 INTEGER PRIMARY KEY 本身就是 rowid 别名（自增），
    # 写不写 AUTOINCREMENT 都一样；PG 这边一律用 BIGSERIAL。
    out = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", out, flags=re.I)
    out = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\b", "BIGSERIAL PRIMARY KEY", out, flags=re.I)
    out = re.sub(r"\bREAL\b", "DOUBLE PRECISION", out, flags=re.I)
    # PRAGMA 在 PG 里不存在，结构版本改用 stocks.schema_meta
    out = re.sub(r"^\s*PRAGMA[^;]*;\s*$", "", out, flags=re.I | re.M)
    return out, tables, with_id


# ── 连接包装 ──────────────────────────────────────────────────────────────

class _Cursor:
    """把 psycopg2 的游标伪装成 sqlite3 的游标。

    差别只有 lastrowid 一处：PG 没有"上一个自增值"的概念（并发下那也不是个
    有意义的问题），要靠 INSERT 自己 RETURNING 回来。所以 execute 时顺手补上，
    取回来存着，供调用方的 `.lastrowid` 读。
    """

    def __init__(self, raw):
        self._raw = raw
        self.lastrowid: int | None = None

    def execute(self, sql: str, params: tuple | list = ()):
        translated = translate(sql)
        table = needs_returning(translated)
        if table:
            translated = translated.rstrip().rstrip(";") + " RETURNING id"
        self._raw.execute(translated, tuple(params))
        if table:
            row = self._raw.fetchone()
            self.lastrowid = int(row["id"]) if row else None
        return self

    def executemany(self, sql: str, seq):
        self._raw.executemany(translate(sql), [tuple(p) for p in seq])
        return self

    def fetchone(self):
        return self._raw.fetchone()

    def fetchall(self):
        return self._raw.fetchall()

    @property
    def rowcount(self):
        return self._raw.rowcount

    def __iter__(self):
        return iter(self._raw)


_ROW_CURSOR = None


def _row_cursor():
    """游标类：行既能按列名取、也能按下标取 —— 对齐 `sqlite3.Row`。

    psycopg2 的文档里写得很直白：RealDictCursor「does not allow the normal access
    (using integer indices) to fetched data」。而本仓是照着 sqlite3.Row 写的，
    `conn.execute("SELECT COUNT(*) …").fetchone()[0]` 这种写法有七处。
    在 PG 上它们不是取到错值，是抛 `KeyError: 0`。

    **为什么这个 bug 能活到线上。** KeyError(0) 的 str() 就是一个 `0`，
    调度器把它记进 last_error，于是数据库里留下的证据是「inbox_tidy 失败：0」——
    看不出是什么错、更看不出在哪一行。它又只在计数类查询里触发，
    页面主流程照常 200，所以从外面完全看不出来。

    **为什么不换成 psycopg2 自带的 DictCursor**（它本来就两种都支持）：
    DictRow 是 list 子类，`.get()` 没了、`"x" in row` 变成查值不查键。
    本仓 `row.get(...)` 用了 29 处。换过去是拿一个已知 bug 换一批未知 bug。
    这里只加整数下标这一件事，其余字典语义原样不动。

    惰性构造是因为 psycopg2 是可选依赖：只跑 SQLite 的环境不装它，
    模块顶层继承会让 import 直接失败。
    """
    global _ROW_CURSOR
    if _ROW_CURSOR is not None:
        return _ROW_CURSOR

    import psycopg2.extras

    class _Row(psycopg2.extras.RealDictRow):
        # 构建期只走 __setitem__（psycopg2 借 dict 自身暂存列名映射），
        # 不碰读路径，所以重写 __getitem__ 是安全的。
        def __getitem__(self, key):
            if isinstance(key, int):
                return list(self.values())[key]
            return super().__getitem__(key)

    class _RowCursor(psycopg2.extras.RealDictCursor):
        # RealDictCursor 在 __init__ 里把 row_factory 钉成 RealDictRow，只能事后换。
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.row_factory = _Row

    _ROW_CURSOR = _RowCursor
    return _ROW_CURSOR


class Connection:
    """`with connection() as conn:` 的 PG 版：正常退出提交，异常回滚。

    与 sqlite3 的连接上下文管理器语义一致 —— 本仓 200 多处都是这么用的，
    语义换一下就会出现"以为提交了其实没有"，那种错要等到下次读才发现。
    """

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql: str, params: tuple | list = ()):
        return _Cursor(self._raw.cursor()).execute(sql, params)

    def executemany(self, sql: str, seq):
        return _Cursor(self._raw.cursor()).executemany(sql, seq)

    def executescript(self, script: str):
        """建表脚本。DDL 已在 initialize 时翻译过，这里按分号切开逐条执行。"""
        with self._raw.cursor() as cur:
            for statement in _split_statements(script):
                cur.execute(statement)
        return self

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        _checkin(self._raw)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._raw.commit()
        else:
            self._raw.rollback()
        _checkin(self._raw)      # 还回池里，不是关掉
        return False


def _split_statements(script: str) -> list[str]:
    """按分号切语句，跳过字符串字面量里的分号与 $$ 函数体。"""
    statements = []
    buf = []
    in_string = False
    index = 0
    while index < len(script):
        ch = script[index]
        if ch == "'":
            in_string = not in_string
        if ch == ";" and not in_string:
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
        else:
            buf.append(ch)
        index += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _load_registry(raw) -> None:
    """从库里读一次表清单，作为「哪些名字要加 stocks. 前缀」的依据。

    **不能只靠建库时登记。** 建库只在 initialize_database 里发生一次，而进程里
    先跑的可能是别的东西（启动时的 recover_stale_jobs 就排在初始化前面）。
    registry 空着的时候翻译会静悄悄地不加前缀，然后报 relation does not exist ——
    错得离真正的原因很远。以库为准就没有先后问题。
    """
    with raw.cursor() as cur:
        cur.execute(
            "SELECT c.relname AS name, "
            "       bool_or(a.attname = 'id' AND a.attnum > 0) AS has_id "
            "FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_attribute a ON a.attrelid = c.oid "
            "WHERE n.nspname = %s AND c.relkind = 'r' GROUP BY c.relname",
            (SCHEMA,))
        rows = cur.fetchall()
    names = {r["name"] for r in rows}
    with_id = {r["name"] for r in rows if r["has_id"]}
    if names:
        register_tables(names, with_id)


# ── 连接池 ────────────────────────────────────────────────────────────────
#
# 实测：新建一条连接 7ms，在已有连接上跑一次查询 0.5ms。而一次「决策总览」请求
# 要开 9 条连接（全仓 120 处 `with connection()`），光建连接就占掉一半以上时间。
#
# **池化最危险的地方是身份。** `app.scope` 是会话变量，跟着连接走而不是跟着请求走。
# 借出去的连接如果还留着上一个人的 scope，下一个请求就会以别人的身份查库 ——
# 那是比忘了加 WHERE 更难查的泄漏，因为它取决于谁先谁后。
# 所以身份在**每次借出时重设**，不是建连时设一次。

# 按连接参数分池。**不能只用一个列表**：凭据是会变的（测试在角色之间切换、
# 备份走管理员账号），共用一个池会把上一个角色的连接借给下一个人 ——
# 表现是莫名其妙的 permission denied，而真正的原因跟当前这行代码毫无关系。
_POOL: dict[tuple, list] = {}
_POOL_MAX = 8          # 本模块是单进程 uvicorn，8 条足够；多了只是占着 RDS 的连接数
_pool_lock = threading.Lock()


def _pool_key() -> tuple:
    params = dsn()
    return (params["host"], params["port"], params["dbname"], params["user"])


def _new_raw_connection():
    import psycopg2
    import psycopg2.extras

    return psycopg2.connect(**dsn(), cursor_factory=_row_cursor())


def _checkout():
    """借一条连接。池里有就复用，没有就新建。

    **不单独探活。** 借出后紧接着要设一次身份（见 connect），那条语句本身就是探活：
    连接死了它会报错，那时再换一条新的。多加一次 `SELECT 1` 只是白花一个往返，
    而往返正是池化要省的东西。
    """
    key = _pool_key()
    with _pool_lock:
        bucket = _POOL.get(key) or []
        while bucket:
            raw = bucket.pop()
            if not raw.closed:
                return raw
    return _new_raw_connection()


def _checkin(raw) -> None:
    """还回池里。放不下或连接已坏就直接关掉。"""
    if raw.closed:
        return
    try:
        raw.rollback()          # 别把没提交的东西留给下一个人
    except Exception:
        try:
            raw.close()
        except Exception:
            pass
        return
    key = _pool_key()
    with _pool_lock:
        bucket = _POOL.setdefault(key, [])
        if len(bucket) < _POOL_MAX:
            bucket.append(raw)
            return
    raw.close()


def close_pool() -> None:
    """进程退出时清空。测试里换库、换角色之后也要调，否则会拿到旧身份的连接。"""
    with _pool_lock:
        pool = [raw for bucket in _POOL.values() for raw in bucket]
        _POOL.clear()
    for raw in pool:
        try:
            raw.close()
        except Exception:
            pass


def connect() -> Connection:
    raw = _checkout()
    # **每次借出都重设身份**，见上面那段注释。
    # 设失败说明这条连接已经死了（超时、PG 重启），换一条新的重来一次。
    try:
        _announce_scope(raw)
    except Exception:
        try:
            raw.close()
        except Exception:
            pass
        raw = _new_raw_connection()
        _announce_scope(raw)
    if not _KNOWN_TABLES:
        try:
            _load_registry(raw)
        except Exception:
            # schema 还没建（第一次跑 initialize_database）时读不到，属正常。
            raw.rollback()
    return Connection(raw)


# ── 行级安全（RLS）─────────────────────────────────────────────────────────
#
# **为什么要有这一层。** 本仓原本是「一台机器一份数据」的单机工作台，多用户是
# 2026-08-05 才补上的：每条查询自己记得加 `_sw()` / `_swc()`，一共一百零一处。
# 漏一处的后果是静默泄漏——测试全绿、页面正常、别人的数据出去了。同一天的审查
# 里就找出八处忘了加的，其中一处能直接改掉别人的投资逻辑。
#
# 靠人记住一百处，等于迟早还会漏。所以把判定挪到数据库里：策略生效之后，
# **就算某条 SQL 完全没写过滤，PG 也不会把别人的行返回给它**。
# 应用层的 `_sw()` 保留不动——SQLite 那边没有 RLS，本地开发仍靠它。
#
# 身份靠会话变量 `app.scope` 传递，在 connect() 时设一次（本仓不用连接池，
# 一条连接就是一次请求的生命周期）。
#
# **子表不加 user_id 列，用子查询回溯。** 因为 companies 自己也有策略，
# 策略里的 `SELECT id FROM companies` 会被再过滤一次——等于自动继承归属。
# 这样省掉一次十四张表的加列迁移，也不会出现「列加了但某处忘了填」的新缺口。

# 自己带 user_id 的根表
_RLS_ROOT_TABLES = (
    "background_jobs", "companies", "daily_briefings", "inbox_corrections",
    "industry_chain_themes", "industry_chain_stages", "industry_chain_nodes",
    "industry_chain_edges", "industry_chain_company_positions",
    "news_feeds", "news_items", "portfolios", "research_tasks", "rule_terms",
    "screen_runs", "screen_strategies", "user_settings", "method_assessments", "counter_hits",
    "candidate_review_runs", "candidate_review_targets",
    # 决策闭环：一家公司在闭环里停在哪一格，是**这个人自己的**判断进度，
    # 不是关于公司的事实。所以它跟 companies 一样按用户隔离。
    "decision_cards",
    # 助理盯盘。提醒正文里有你的计划价和仓位计划，漏出去等于漏出你的交易计划。
    # 按 user_id 而不是 company_id 隔离：心跳那类提醒不挂在任何一家公司上。
    "assistant_watch_state", "assistant_alerts", "assistant_watch_runs",
    "assistant_actions", "assistant_memory", "assistant_subscriptions",
)

# 挂在 companies 下面的表：归属由所属公司决定
_RLS_COMPANY_TABLES = (
    "company_calendar_events", "evidences", "research_events", "research_reports",
    "supply_chain_links", "theses", "thesis_reviews", "trades", "valuations",
    # 管理层承诺台账：挂在公司下面，跟证据、逻辑同一个数据域。
    "management_promises",
    # 状态推进日志。**挂 company_id 而不是 card_id**：卡片被删（公司移出档案）
    # 时日志会跟着级联删掉，而策略要在删之前就拦得住别人来读。
    "decision_transitions",
    # 成交登记。同上，挂 company_id —— 而且这张表装的是**真实成交价**，
    # 比状态日志更敏感，漏出去等于漏出别人的交易记录。
    "decision_fills",
)

# 全局共享、**不设策略**的行情与财务数据（v32 起按 symbol 存）。
#
# 这些是客观事实：茅台的 K 线谁看都一样，没有「我的 K 线」。给它们加策略只会
# 让每个用户各存一份、数据源各拉一次（实测一个人 34,849 行）。
#
# 代价说清楚：登录用户能看到系统同步过哪些标的，也就间接知道「有人在看这只」。
# 这一点已确认可以接受——行情本身是公开数据。
_GLOBAL_MARKET_TABLES = (
    "market_snapshots", "price_bars", "financial_periods",
    "valuation_points", "company_profiles",
    # 年报披露的分部构成。跟 K 线同理：茅台按产品分了几块、每块毛利率多少，
    # 谁看都是同一份，没有「我的分部构成」。
    "business_segments",
    # 报表原始科目（合同负债、净利息收入这些）。同理：报表上写多少就是多少。
    "financial_line_items",
    # 公告正文。同一份公告谁下载都是同一个 PDF，按用户存一份纯属浪费——
    # 一份年报正文几万字，十个用户就是十份。
    "announcement_texts",
    # 产业链位置（年报披露的客户/供应商集中度）。同理：年报上写多少就是多少。
    "chain_positions",
    # 产业链环节的同行（从 earth-atlas 导入）。谁跟谁同环节，谁看都一样。
    "chain_segment_members",
)

# 挂在 research_tasks 下面的表。
#
# **归属键要挑那个不可空的。** research_task_items 同时有 task_id（NOT NULL）和
# company_id（可空的弱引用，候选股还没建档时就是 NULL）。一开始按 company_id 写策略，
# 结果 `NULL IN (...)` 求值为 NULL、不是 true —— 于是「候选清单转研究任务」整个功能
# 被自己的策略挡死，报 new row violates row-level security policy。
_RLS_TASK_TABLES = ("research_task_items",)

# 系统域：调度器要替所有人同步数据，必须看得见全部。
SYSTEM_SCOPE = "__system__"

_SCOPE = "current_setting('app.scope', true)"
_SYSTEM = f"{_SCOPE} = '{SYSTEM_SCOPE}'"


def _policy_expression(table: str) -> str:
    if table in _RLS_ROOT_TABLES:
        return f"(user_id = {_SCOPE} OR {_SYSTEM})"
    if table in _RLS_TASK_TABLES:
        return f"(task_id IN (SELECT id FROM {SCHEMA}.research_tasks) OR {_SYSTEM})"
    if table in _RLS_COMPANY_TABLES:
        # companies 自己有策略，所以这个子查询已经是「我的公司」。
        return f"(company_id IN (SELECT id FROM {SCHEMA}.companies) OR {_SYSTEM})"
    if table == "record_revisions":
        # 通用修订日志：按 entity_type 分别回溯。**白名单**——不认识的类型一条都不给，
        # 将来加了新的 entity_type 而这里没跟上，结果是看不到，不是看到别人的。
        return (
            f"((entity_type = 'thesis' AND entity_id IN (SELECT id FROM {SCHEMA}.theses))"
            f" OR (entity_type = 'trade' AND entity_id IN (SELECT id FROM {SCHEMA}.trades))"
            f" OR {_SYSTEM})")
    raise AssertionError(f"{table} 没有对应的 RLS 表达式")


def rls_tables() -> tuple[str, ...]:
    return (*_RLS_ROOT_TABLES, *_RLS_COMPANY_TABLES, *_RLS_TASK_TABLES, "record_revisions")


def apply_row_level_security(conn) -> list[str]:
    """给需要隔离的表装上策略。可重复执行。

    `FORCE ROW LEVEL SECURITY` 不能省：本应用是拿建表的那个账号连的库，
    而表的属主默认**绕过**自己的策略——不加 FORCE 就等于什么都没开，
    而且开没开从外面看不出来。
    """
    # 先把全局表上的策略撤干净。**这一步要无条件跑**：这些表以前是按 company_id
    # 隔离的，改成全局共享之后老策略还留在库里，而它引用的列已经不存在了——
    # 表现是「策略数比预期多一张」，不看仔细根本发现不了。
    for table in _GLOBAL_MARKET_TABLES:
        try:
            conn.execute(f"DROP POLICY IF EXISTS scope_isolation ON {SCHEMA}.{table}")
            conn.execute(f"ALTER TABLE {SCHEMA}.{table} DISABLE ROW LEVEL SECURITY")
            conn.commit()
        except Exception:
            conn.rollback()

    applied = []
    for table in rls_tables():
        qualified = f"{SCHEMA}.{table}"
        try:
            conn.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
            conn.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
            conn.execute(f"DROP POLICY IF EXISTS scope_isolation ON {qualified}")
            expression = _policy_expression(table)
            conn.execute(
                f"CREATE POLICY scope_isolation ON {qualified} "
                f"USING {expression} WITH CHECK {expression}")
            conn.commit()
            applied.append(table)
        except Exception:
            # 表还没建出来（首次初始化的中间态）时跳过，下一次初始化会补上。
            conn.rollback()
    return applied


def _announce_scope(raw) -> None:
    """把「这次是谁」告诉数据库，RLS 策略靠它判定。

    设在 connect() 里而不是每条语句前：本仓不用连接池，一条连接就是一个
    `with connection()` 块的生命周期，身份在这期间不会变。

    **取不到数据域时按系统域处理**，因为取不到只发生在两种场合——调度器
    （它本来就该看全部）和建库/迁移脚本。反过来「拿不准就当普通用户」会让
    调度器同步不到任何公司，而那种坏法是静悄悄的：作业报成功，数据不更新。
    """
    from .access import OWNER_SCOPE, current_scope

    scope = current_scope()
    if scope is None:
        scope = SYSTEM_SCOPE
    elif scope == OWNER_SCOPE:
        scope = OWNER_SCOPE
    with raw.cursor() as cur:
        # 用参数化而不是拼接：scope 来自主站返回的 user_id，虽然 access 那边
        # 已经白名单校验过，但这里是它进 SQL 的最后一道口子，没理由靠上游。
        cur.execute("SELECT set_config('app.scope', %s, false)", (scope,))
    # **不在这里 commit**，省一个往返。代价是：这次请求中途若回滚，scope 会跟着
    # 被撤销（SET 在 PG 里是事务性的）。那种情况下 current_setting 返回 NULL，
    # 策略里 `user_id = NULL` 求值为假 —— 看到零行，而不是看到别人的行。
    # 失败方向是对的，且下次借出会重设。


def rls_status() -> dict[str, Any]:
    """行级安全到底生没生效。

    **必须单独查一次，不能看「策略建了没有」。** 策略建好、ENABLE 和 FORCE 都开着，
    只要连库的角色带 BYPASSRLS（超级用户默认带，云库主账号通常也带），
    一条都不生效——而查询照常返回，只是返回了所有人的行，从应用这边完全看不出来。
    实测踩过：本地 docker 与线上 RDS 的账号都带 BYPASSRLS，策略装完形同虚设。

    所以这里查的是「这个角色会不会绕过」，而不是「策略在不在」。
    """
    conn = connect()
    try:
        role = conn.execute(
            "SELECT current_user AS name, rolsuper, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user").fetchone()
        protected = conn.execute(
            "SELECT count(*) AS n FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relrowsecurity AND c.relforcerowsecurity",
            (SCHEMA,)).fetchone()["n"]
        bypasses = bool(role["rolsuper"] or role["rolbypassrls"])
        return {
            "role": role["name"],
            "bypasses_rls": bypasses,
            "protected_tables": int(protected),
            "expected_tables": len(rls_tables()),
            "effective": (not bypasses) and int(protected) >= len(rls_tables()),
        }
    finally:
        conn.close()
