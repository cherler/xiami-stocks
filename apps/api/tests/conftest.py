"""所有测试共用的隔离数据库。

原来这个 fixture 写在 test_api.py 里，只对那个文件生效——新加的测试文件
若忘了自带 fixture，就会**直接打到真实研究库上**。挪到 conftest 里让它对整个
目录 autouse，这类事故从结构上不可能再发生。

## 默认跑 PostgreSQL

线上是 PG，测试就该在 PG 上跑。此前默认 SQLite，代价已经付过了——四个只在 PG
上才炸的 bug 全是上线后靠读 last_error 才发现的：

  · `INSERT OR REPLACE`   PG 语法错误，整个「全市场底座」作业静静挂掉
  · `row[0]`              PG 的行是字典，抛 KeyError(0)，而它的 str() 就是「0」
  · `HAVING` 引用别名     SQLite 允许，PG 把别名解析成同名的列
  · `sqlite_master`       PG 没有这张表，导出接口直接 500

更要紧的是**行级安全只有 PG 有**。在 SQLite 上跑，隔离测试验的只是应用层那
一百零一处过滤没漏；在 PG 上跑，验的才是「就算漏了数据库也不给」。

想单独验 SQLite 那条路（它仍是建表结构的定义方式），设 `STOCK_TEST_SQLITE=1`。

## 为什么要专门建一个测试角色

行级安全有一个很容易踩的坑：策略建好了、ENABLE/FORCE 也开了，但只要连库的角色
带 BYPASSRLS（超级用户默认带，云库主账号通常也带），**策略一条都不生效，
而从应用这边完全看不出来**——查询照常返回，只是返回了所有人的行。

用主账号跑测试，隔离测试会全绿，而线上真出事。所以这里自己建一个不绕过 RLS 的
角色，让它当测试 schema 的属主（当属主是为了仍能建表，FORCE RLS 保证策略对属主
也生效）。

## 为什么专门用一个 schema

上一次的事故是测试跑进了真实的 `stocks` schema，92 个测试"全绿"，同时把测试
数据写进了真库。所以这里**不复用 STOCK_PG_SCHEMA**，而是钉死一个独立名字，
每次会话开始时整个删掉重建。名字里带 test，万一有人在生产上误跑，一眼能看出
这个 schema 是可以扔的。
"""

import os
from pathlib import Path

# ---------------------------------------------------------------- 只许一个进程跑

# **同一时刻只能有一个 pytest 在跑这个目录。**
#
# 整套测试共用一个钉死的 schema（stocks_pytest），每个用例开头都会把它删掉重建。
# 两个 pytest 进程同时跑的时候，A 正在建表、B 把 schema 整个删了，症状是随机的：
#   · UniqueViolation: duplicate key ... pg_type_typname_nsp_index
#   · DeadlockDetected
#   · RuntimeError: 这些建表语句无论怎么排都建不出来
#   · 后台任务没有在预期时间内结束
# 这些错误跟被改的代码毫无关系，而且每次挂的是不同的用例——
# 于是人会去查那个用例，查半天查不出来。（本轮实测：连着踩了五次。）
#
# 与其记得"别并发跑"，不如让并发跑不起来：拿一把文件锁，拿不到就直接说清楚。
def _acquire_single_run_lock() -> None:
    import atexit
    import fcntl

    lock_path = Path(__file__).resolve().parent / ".pytest-single-run.lock"
    handle = lock_path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SystemExit(
            "\n已经有另一个 pytest 在跑这个目录了。\n"
            "整套测试共用一个 PostgreSQL schema，并发跑会互相把表删掉，\n"
            "报出来的错跟你改的代码没有关系。等前一个跑完再来。\n"
        )
    handle.write(str(os.getpid()))
    handle.flush()
    atexit.register(handle.close)


def _block_outbound_network() -> None:
    """测试不许连外网。连上了就当场报错，**而不是等它超时**。

    ## 为什么加这个

    起草投资逻辑改成工具循环、又给底座作业挂上申万分类同步之后，
    测试里有用例真的去发了外部请求——表现是**整套测试从 4.5 分钟变成
    十八分钟还没结束**，而输出被 `| tail` 缓冲着，看不出停在哪一条。
    查这件事花的时间比写这个守卫长得多。

    这跟并发跑 pytest 是同一类问题：不是"记得别这么干"能解决的，要让它干不了。

    ## 挡在 URL 层，不是 socket 层

    我第一版挡的是 `socket.connect`，**完全没用**——这台机器上出站走的是
    127.0.0.1:7890 那个本地代理，socket 看到的目标地址就是本机。
    实测那一版让请求照样发了出去（拿回来一个 403）。

    所以改成挡 urllib 的 `OpenerDirector.open` 和 requests 的 `HTTPAdapter.send`：
    这两个是本仓真正的出口（llm / disclosure / access 走 urllib，akshare 走 requests），
    而且这一层看得见真正的目标域名，报错里能写清楚是谁在发。
    """
    import urllib.request

    allowed_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}

    def _refuse(url: str):
        from urllib.parse import urlparse

        host = (urlparse(str(url)).hostname or "").lower()
        if host and host not in allowed_hosts:
            raise RuntimeError(
                f"测试里发起了外网请求（{url}）。这在这套测试里永远是错的：\n"
                f"  · 它会让套件变慢甚至挂死，而且报出来的错跟被改的代码无关\n"
                f"  · 外部数据随时会变，用它做断言的测试迟早会自己红\n"
                f"该 mock 掉这个 provider 或这次模型调用。")

    real_open = urllib.request.OpenerDirector.open

    def guarded_open(self, fullurl, *args, **kwargs):
        _refuse(getattr(fullurl, "full_url", fullurl))
        return real_open(self, fullurl, *args, **kwargs)

    urllib.request.OpenerDirector.open = guarded_open

    try:
        from requests.adapters import HTTPAdapter
    except ImportError:
        return
    real_send = HTTPAdapter.send

    def guarded_send(self, request, *args, **kwargs):
        _refuse(request.url)
        return real_send(self, request, *args, **kwargs)

    HTTPAdapter.send = guarded_send


_acquire_single_run_lock()
_block_outbound_network()

import pytest

TEST_SCHEMA = "stocks_pytest"
TEST_ROLE = "xiamimate_stocks_test"
TEST_ROLE_PASSWORD = "pytest_only_not_a_secret"

_USE_SQLITE = os.environ.get("STOCK_TEST_SQLITE", "").strip().lower() in {"1", "true", "yes", "on"}
_USE_PG = not _USE_SQLITE

# **必须在导入业务代码前钉死后端。** backend() 会回退读仓根 .env，而
# configure_database(tmp) 只改 SQLite 路径——两者不一致时，整个测试套件会跑在
# 一个你以为没在用的库上。（实测发生过：92 个测试"全绿"，同时把测试数据写进了真库。）
os.environ["STOCK_DB_BACKEND"] = "sqlite" if _USE_SQLITE else "postgres"

if _USE_PG:
    os.environ["STOCK_PG_SCHEMA"] = TEST_SCHEMA

from stock_decision import llm  # noqa: E402
from stock_decision.database import SCHEMA_VERSION, configure_database, initialize_database  # noqa: E402

# 管理员凭据（建角色、删建 schema 要用）。
#
# **必须也读 .env，不能只看 os.environ。** 本地把 PG_USER 写进 .env 之后，
# `os.environ.get("PG_USER")` 是空的，于是这里以为"没有管理员"，回退到应用角色，
# 然后在 ALTER ROLE 上报一句 permission denied —— 而错误信息跟真正的原因
# （凭据没读到）离得很远。
_env = llm.load_env()

# ── 访问姿态钉死在 open ──────────────────────────────────────────────
#
# **测试不能读开发者的 .env。** access.mode() 的取值链是
# os.environ → 仓根 .env → 默认值，而全套测试用的是不带 Cookie 的 TestClient。
# 本机把 STOCK_ACCESS 切成线上那档（auto/multi）之后，这些请求全变成游客，
# 写入被中间件挡掉 —— 实测 105 条失败，而且失败信息是 `KeyError: 'id'` 之类，
# 跟真正的原因（访问姿态变了）离得很远，看着像是自己刚才那次改动搞坏的。
#
# 要验别的姿态就在用例里自己 monkeypatch（见 test_guest.py），
# 而不是靠开发者本机恰好配成什么样。
os.environ["STOCK_ACCESS"] = "open"
_ADMIN_USER = (os.environ.get("PG_ADMIN_USER") or _env.get("PG_ADMIN_USER")
               or os.environ.get("PG_USER") or _env.get("PG_USER"))
_ADMIN_PASSWORD = (os.environ.get("PG_ADMIN_PASSWORD") or _env.get("PG_ADMIN_PASSWORD")
                   or os.environ.get("PG_PASSWORD") or _env.get("PG_PASSWORD"))


def _as_admin(fn):
    """临时切回管理员身份执行。建角色、DROP SCHEMA 这些测试角色自己做不了。"""
    saved = (os.environ.get("PG_USER"), os.environ.get("PG_PASSWORD"))

    def restore(pair):
        for name, value in zip(("PG_USER", "PG_PASSWORD"), pair):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    restore((_ADMIN_USER, _ADMIN_PASSWORD))
    try:
        return fn()
    finally:
        restore(saved)
        # 池子按凭据分桶，切回来之后旧桶留着没用，顺手清掉免得占着连接数。
        from stock_decision import pgbackend

        pgbackend.close_pool()


def pytest_configure(config):
    """建测试角色与测试 schema。整轮只做一次。"""
    if not _USE_PG:
        return
    from stock_decision import pgbackend

    assert pgbackend.SCHEMA == TEST_SCHEMA, (
        f"测试 schema 被改成了 {pgbackend.SCHEMA!r}；拒绝在非测试 schema 上执行 DROP")

    def setup():
        conn = pgbackend.connect()
        try:
            exists = conn.execute(
                "SELECT 1 AS ok FROM pg_roles WHERE rolname = %s", (TEST_ROLE,)).fetchone()
            if exists:
                conn.execute(f"ALTER ROLE {TEST_ROLE} PASSWORD %s", (TEST_ROLE_PASSWORD,))
            else:
                conn.execute(f"CREATE ROLE {TEST_ROLE} LOGIN PASSWORD %s", (TEST_ROLE_PASSWORD,))
            # 这一条是整个隔离测试成立的前提：带 BYPASSRLS 的角色会让策略形同虚设，
            # 而测试照样全绿。显式关掉，不依赖默认值。
            conn.execute(f"ALTER ROLE {TEST_ROLE} NOBYPASSRLS NOSUPERUSER")
            conn.commit()

            try:
                conn.execute(f"GRANT {TEST_ROLE} TO CURRENT_USER")
                conn.commit()
            except Exception:
                conn.rollback()

            dbname = pgbackend.dsn()["dbname"]
            conn.execute(f"GRANT CONNECT, CREATE ON DATABASE {dbname} TO {TEST_ROLE}")
            conn.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
            conn.execute(f"CREATE SCHEMA {TEST_SCHEMA} AUTHORIZATION {TEST_ROLE}")
            conn.commit()
        finally:
            conn.close()

    _as_admin(setup)

    # 从这里开始，业务代码一律以测试角色连库——策略对它是真生效的。
    os.environ["PG_USER"] = TEST_ROLE
    os.environ["PG_PASSWORD"] = TEST_ROLE_PASSWORD
    # **备份要单独一套能看见所有行的凭据。** 开了 FORCE RLS 之后，
    # 用测试角色跑 pg_dump 会被数据库直接拒绝（"query would be affected by
    # row-level security policy"），备份测试于是必然失败——而这跟被测的功能
    # 一点关系都没有，纯粹是测试环境没把线上有的东西配齐。
    #
    # 这条在 CI 上红了一整天没人发现，因为开发机上它是 skip 的：
    # needs_matching_pg_client 要求 pg_dump 与服务端大版本一致，本机对不上就跳过。
    # **一条在开发机永远跳过、在 CI 永远失败的测试，等于没有测试。**
    if _ADMIN_USER:
        os.environ.setdefault("PG_ADMIN_USER", _ADMIN_USER)
        if _ADMIN_PASSWORD:
            os.environ.setdefault("PG_ADMIN_PASSWORD", _ADMIN_PASSWORD)
    from stock_decision import pgbackend

    pgbackend.close_pool()      # 换了身份，之前借过的连接一律作废


def reset_to_empty_database(tmp_path: Path) -> None:
    """给测试一个空库，两种后端都管用。

    有测试靠 `configure_database(新路径)` 换空库——那只对 SQLite 有效，
    PG 模式下它只改了一个根本用不到的文件路径，库里的数据还在，
    于是「换到空库」这一步静静地没发生，后面的断言莫名其妙地失败。
    """
    _empty_database(tmp_path)


# 结构只建一次。**这是整套测试最大的一笔时间。**
#
# 剖出来的数据：1154 个测试跑 1029 秒，最慢 25 名里 23 个是 `setup` 而不是 `call`，
# 最慢的两个 call 加起来才 17 秒。也就是说时间不在测试本身，是**均匀摊在每个测试
# 之前的准备上**（平均 0.89 秒／个），而准备期间 CPU 只用到 12% —— 全在等数据库往返。
#
# 原来每个用例调**两次** initialize_database()，而它每次都要：
#   1. 在内存 SQLite 里把整套建表 + 迁移阶梯跑一遍，dump 出结构（纯 CPU，不便宜）
#   2. 把派生出的约一百条 DDL **逐条提交**到 PG（一条一个往返）
#   3. 逐列比对补列、重装一遍行级安全策略（又是几十个往返）
#
# 而这些东西在两个用例之间**根本不会变**：TRUNCATE 清的是数据，
# 表、索引、RLS 策略都是 schema 对象，一个都不会掉。
# 种子也只有 schema_meta 那一行（实测一个刚初始化的库里其余表全空）。
#
# 所以：结构一轮只建一次，每个用例只做 TRUNCATE。
_SCHEMA_BUILT = False


def _empty_database(tmp_path: Path) -> None:
    global _SCHEMA_BUILT
    if _USE_PG:
        # PG 没法一个用例一个库，改成每个用例前清空所有表的数据（保留结构）。
        from stock_decision import pgbackend

        if not _SCHEMA_BUILT:
            initialize_database()
            _SCHEMA_BUILT = True
        conn = pgbackend.connect()
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s", (TEST_SCHEMA,)).fetchall()
        names = [f"{TEST_SCHEMA}.{r['tablename']}" for r in rows]
        if names:
            # 一条 TRUNCATE 全部搞定：分开截断会被外键挡住，而 CASCADE 在这里是安全的
            # ——所有表都在这一份清单里，本来就要一起清空。
            conn.execute(f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE")
            # schema_meta 那一行是唯一的种子，被 TRUNCATE 清掉了，就地补回来 ——
            # 为一行数据重跑整套 DDL 是这套测试慢的主要原因。
            conn.execute(
                f"INSERT INTO {TEST_SCHEMA}.schema_meta (key, value) VALUES ('version', %s) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),))
            conn.commit()
        return

    configure_database(tmp_path / "stock-decision-test.db")
    initialize_database()


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path: Path) -> None:
    _empty_database(tmp_path)


@pytest.fixture()
def needs_matching_pg_client():
    """备份类测试要求 pg_dump/psql 的大版本和数据库一致。

    对不上时**跳过而不是失败**：产品代码此时是按设计拒绝的（见
    backup._require_matching_client），失败的是测试机缺工具，不是功能坏了。
    把这两件事混在一起，下次真坏了会被当成"又是版本问题"忽略掉。
    """
    if not _USE_PG:
        return
    from stock_decision import backup

    try:
        backup._require_matching_client(backup._pg_binary("pg_dump"))
    except Exception as exc:
        pytest.skip(f"跳过：{exc}")


@pytest.fixture(autouse=True)
def _no_real_curl(monkeypatch) -> None:
    """**测试里不许真的起 curl 去联网。**

    这条是门禁抓出来的。取 PDF 那一步后来加了第二条路（直连拿不到 PDF 就换
    curl，见 disclosure.fetch_bytes 的说明），而 test_disclosure 里那两个
    「非 PDF 响应 / 网络超时」的测试只 mock 了 urllib —— 于是 curl **真的去把
    文件取回来了**，「取不到」变成了「已取正文」，两个测试红了。

    红了是对的：它说明单元测试会打真网。而那不只是慢和不稳 ——
    **联网的测试会在断网时红、在网站改版时红**，而那两种红跟被测代码没关系，
    看几次之后就没人当真了。

    跟隔离数据库同一个道理：写在 conftest 里 autouse，从结构上挡住，
    不靠每个测试作者记得去 mock 第二条路。真要测那条路的测试自己
    monkeypatch 回去（`monkeypatch.setattr(dc, "_fetch_with_curl", ...)`）。
    """
    from stock_decision import disclosure

    monkeypatch.setattr(
        disclosure, "_fetch_with_curl",
        lambda url: {"body": b"", "note": "测试里不起 curl（见 conftest._no_real_curl）"})


@pytest.fixture(autouse=True)
def _no_real_assistant_delivery(monkeypatch) -> None:
    """**测试里的提醒永远送不到真的飞书。**

    助理送提醒的路是 `nanobot trigger <号>` —— 它把话写进本机 ~/.nanobot 的收件箱，
    网关再推到站主的飞书。这条路不经过 HTTP，上面那两道断网的闸拦不住它。
    而配置读的是仓根 `.env`：站主在 .env 里配好触发号的那天起，
    任何一条调了 watch_once(send=True) 的测试都会往他手机上真发一条。

    所以两件事都在这里从结构上挡住：
    - 配置只读环境变量，**不读 .env**——测试要什么配置自己 setenv；
    - nanobot 的路径默认指向一个不存在的文件，找不到真命令也就发不出去。
    """
    import os

    from stock_decision import assistant

    monkeypatch.setattr(assistant, "_setting", lambda key: os.environ.get(key, "").strip())
    monkeypatch.delenv("STOCK_ASSISTANT_TRIGGER", raising=False)
    monkeypatch.delenv("STOCK_ASSISTANT_WATCH", raising=False)
    monkeypatch.delenv("STOCK_ASSISTANT_SCOPE", raising=False)
    monkeypatch.setenv("STOCK_ASSISTANT_NANOBOT", "/nonexistent/nanobot-blocked-in-tests")
