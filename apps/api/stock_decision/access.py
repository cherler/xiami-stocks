"""访问控制。

**为什么需要它。** 本仓 33 张表**没有一张带 user_id**：公司档案、投资逻辑、持仓账本、
交易流水全是"这台机器上的唯一一份数据"。这个设计对「本地单机个人工作台」是对的——
不必为一个人造多租户。但它有一个直接后果：**谁能连到这个进程，谁就拥有全部数据。**

挂到 `https://xiamimate.com/stocks/` 之后，"能连到"变成了"所有人"。实测过：
不带任何 Cookie，`GET /api/v1/companies` 读到全部档案，`POST` 建公司返回 201。
持仓成本、每一笔交易的理由、还没公开的判断——全部对公网可读可写。

**所以这一层做的是「守住唯一那份数据」，不是「区分不同用户的数据」。**
两者差别很大，不能混：前者一个白名单就够，后者要给 33 张表加 user_id、
改几百处查询、还要想清楚注销时怎么清——那是另一件工程（见 wiki）。
在它做完之前，本模块只对**站主本人**开放。

**数据域（scope）。** 2026-08-05 起本模块按用户隔离数据：每张根表带 user_id，
站主（管理员邮箱）的域是 `__owner__`——**建库以来的全部存量数据都归这个域**，
其他登录用户各有自己的域，互相看不见。调度器跑在系统域（scope=None，不过滤），
因为它要替所有人同步公司数据。

三种运行姿态：

- `STOCK_ACCESS=auto`（线上用的就是这个）：跟随运营台「模块显隐」里的虾米看股开关——
  显示则等同 multi，隐藏则等同 owner。这样「开放本模块」只是运营台上的一次点击，
  不用登服务器改配置，也不会出现「入口开了但服务端还关着」的半开状态。
- `STOCK_ACCESS=open`：不校验，一律落在站主域。**只在本机开发时用**，绑 127.0.0.1。
- `STOCK_ACCESS=multi`：任何登录用户可用，各看各的数据；
  管理员邮箱（`STOCK_OWNER_EMAILS`）落在站主域。
- `STOCK_ACCESS=owner`：只允许站主登录（想彻底钉死、不受运营台影响时用）。

身份一律问主站（`/v1/me`），本进程不自己验签——签名密钥不该有第二份拷贝。
没配 `XM_API_BASE` 时无从校验，退回 open。
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Any

from . import llm

log = logging.getLogger("stock_decision.access")

# 站主域：建库以来的存量数据全部归它；管理员登录后也落在这个域。
# 用哨兵值而不是真实 user_id，是为了不依赖「主站里站主到底是哪个 id」——
# 换邮箱、本地没登录、测试环境，行为都一致。
OWNER_SCOPE = "__owner__"

# 游客域。**这个域永远是空的**：中间件不让游客写，所以没有任何一行会落进来。
# 它的作用不是装数据，是让 RLS 有一个「什么都匹配不到」的身份可用。
GUEST_SCOPE = "__guest__"

# 当前请求的数据域。默认站主域：测试、脚本、本地单机都天然落在存量数据上。
# 调度器显式设成 None（系统域，不过滤）——它要替所有用户同步公司数据。
_scope: contextvars.ContextVar = contextvars.ContextVar("stock_scope", default=OWNER_SCOPE)


# 这次请求是不是站主发起的。默认 True：本地开发、脚本、调度器都该当作站主，
# 否则一装上守卫，单机模式和后台任务全被自己挡在门外。
_is_owner: contextvars.ContextVar[bool] = contextvars.ContextVar("stock_is_owner", default=True)


def current_scope():
    """当前数据域。None = 系统域（只有调度器该拿到它）。"""
    return _scope.get()


def set_owner_flag(value: bool) -> contextvars.Token:
    return _is_owner.set(bool(value))


def reset_owner_flag(token) -> None:
    _is_owner.reset(token)


def is_owner() -> bool:
    return _is_owner.get()


def require_owner(what: str) -> None:
    """整实例级操作的守卫：**按数据域过滤救不了它们**。

    备份、还原、下载整库这类动作作用于整个数据库文件/schema，不是某个人的数据：
    还原会用一份快照覆盖所有人的记录，下载拿到的是所有人的原始行。
    这种操作没有"只做我那份"的版本，所以只能按人挡，不能按域过滤。

    多用户模式下，这几个接口此前对任何登录用户都开着——也就是随便谁都能
    下走全站数据，甚至把全站数据回滚掉。
    """
    if not is_owner():
        raise AccessDenied(f"{what}会影响所有人的数据，只有站主能做。", "owner_only", 403)


def set_scope(scope) -> contextvars.Token:
    return _scope.set(scope)


def reset_scope(token) -> None:
    _scope.reset(token)

# 主站身份接口的缓存：同一个 Cookie 在短时间内反复问没有意义，
# 而每个 API 请求都去问一次会让本站的每次点击都多一跳。
#
# ## 为什么要有上限
#
# 键是 Cookie 串。**过期的条目原来永远不会被删** —— 只在读到时判一下
# 「够不够新」，不够新就重新去问，然后覆盖写回。于是字典只涨不落：
# 换一次浏览器、清一次 Cookie、来一个新用户，就多一条永久的键；
# 而这些键还是身份凭据本身，长期驻留在进程内存里没有任何好处。
#
# 不引第三方缓存库，也不另起清理线程：一个有序字典 + 插入时顺手清一遍就够。
# 上限 512 是按"同时在线的活跃会话"给的，超了就丢最早的那条 ——
# 丢了的代价只是下次请求多问主站一跳，不是错误。
_CACHE: "OrderedDict[str, tuple[float, dict[str, Any] | None]]" = OrderedDict()
_CACHE_TTL_SECONDS = 60
_CACHE_MAX_ENTRIES = 512

# **"没认出来"只缓存一小会儿。**
#
# 2026-08-15 线上实测：站主打开首页，主站 `/v1/me` 在那一瞬返回了 401
# （21:51:48），九秒后同一个人再问就是 200。而这里把「没登录」按 Cookie
# 缓存了 60 秒 —— 于是首屏那一批请求（dashboard / 决策看板 / 云图）
# **全部按游客处理**，dashboard 返回 200 + 一份空档案，首页写着「已建档 0 家」，
# 而他有 6 家。
#
# 正面结果缓存 60 秒是省一跳；否定结果缓存 60 秒是**把一次瞬时故障放大成
# 整整一分钟的错误身份**，而 401 恰恰是最可能瞬时的那一种（令牌正在刷新、
# 刚登录、会话刚续期）。
#
# 不能干脆不缓存：一次进站会并发打十来个接口，全部回源等于把主站当压测目标。
# 5 秒刚好够吸收一次页面加载的那一批，又短到下一次交互就会重新问。
_NEGATIVE_TTL_SECONDS = 5

# 模块显隐的缓存。同样 60 秒：运营台拨一下开关，最多一分钟后生效。
# 这个只有一个键（"v"），不会涨。
_VIS_CACHE: dict[str, tuple[float, bool]] = {}


def _remember(cookie: str, now: float, user: "dict[str, Any] | None") -> None:
    """写缓存，并顺手把过期的和超出上限的清掉。

    **清理放在写入这一侧**，不放在读的那一侧：读命中的时候只碰一条，
    看不到全貌；而写入本来就是稀疏事件（每个 Cookie 每分钟最多一次）。
    """
    stale = [key for key, (stamp, _) in _CACHE.items() if now - stamp >= _CACHE_TTL_SECONDS]
    for key in stale:
        _CACHE.pop(key, None)
    _CACHE[cookie] = (now, user)
    _CACHE.move_to_end(cookie)
    while len(_CACHE) > _CACHE_MAX_ENTRIES:
        _CACHE.popitem(last=False)


class AccessDenied(RuntimeError):
    def __init__(self, message: str, code: str = "forbidden", status: int = 403) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def module_shown() -> bool:
    """运营台把「虾米看股」设成显示了吗。

    读的是主站 `/v1/site-settings` 里的 `modulesVis` —— 运营台「模块显隐」那个开关
    写的就是它。本模块在前端清单里是 planned（默认隐藏），所以只有被显式覆盖成 true
    才算开。

    **取不到一律当作没开。** 这个判断会决定要不要对所有登录用户敞开数据，
    所以主站抖一下、字段缺一个、JSON 解析失败，结论都必须是「关」。
    """
    import time

    base = llm.load_env().get("XM_API_BASE")
    if not base:
        return False

    now = time.monotonic()
    cached = _VIS_CACHE.get("v")
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    shown = False
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(base.rstrip("/") + "/v1/site-settings")
        with opener.open(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        overrides = payload.get("modulesVis") if isinstance(payload, dict) else None
        shown = bool(isinstance(overrides, dict) and overrides.get("stocks") is True)
    except Exception:
        log.warning("读不到主站模块显隐配置，本次按「未开放」处理")
        shown = False

    _VIS_CACHE["v"] = (now, shown)
    return shown


def mode() -> str:
    configured = (os.getenv("STOCK_ACCESS") or llm.load_env().get("STOCK_ACCESS") or "").strip().lower()
    if configured == "auto":
        # 跟随运营台：模块显示 → 所有登录用户可用（各看各的）；模块隐藏 → 只有站主。
        # 这样「开放本模块」就真的只是运营台上的一个开关，不用再登服务器改 .env。
        # 两处各改一半正是最容易出的错：只开入口 = 所有人点进去 401，
        # 只开服务端 = 数据敞开着但没人找得到入口，看起来「没上线」。
        return "multi" if module_shown() else "owner"
    if configured in {"open", "owner", "multi"}:
        return configured
    # 没显式配置时：接了主站就默认 multi（要求登录、按用户隔离），
    # 没接主站就是本地单机。默认值要偏安全——忘了配的后果是要求登录，不是数据裸奔。
    return "multi" if llm.load_env().get("XM_API_BASE") else "open"


def owner_emails() -> set[str]:
    raw = os.getenv("STOCK_OWNER_EMAILS") or llm.load_env().get("STOCK_OWNER_EMAILS") or ""
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def owner_user_ids() -> set[str]:
    raw = os.getenv("XM_OWNER_USER_ID") or llm.load_env().get("XM_OWNER_USER_ID") or ""
    return {item.strip() for item in raw.split(",") if item.strip()}


def _whoami(cookie: str) -> dict[str, Any] | None:
    """拿 Cookie 去主站问「这是谁」。本进程不自己验 JWT 签名。

    自己验签意味着把 `JWT_SECRET` 再抄一份到这个仓的 .env 里——多一份拷贝就多一处泄漏面，
    而且两边过期策略一旦不同步就会出现「主站已登出、这里还认」。
    """
    import time

    base = llm.load_env().get("XM_API_BASE")
    if not base or not cookie:
        return None

    now = time.monotonic()
    cached = _CACHE.get(cookie)
    if cached:
        # 认出来了缓存 60 秒；没认出来只缓存 5 秒 —— 见 _NEGATIVE_TTL_SECONDS。
        ttl = _CACHE_TTL_SECONDS if cached[1] else _NEGATIVE_TTL_SECONDS
        if now - cached[0] < ttl:
            return cached[1]

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(base.rstrip("/") + "/v1/me", headers={"cookie": cookie})
    try:
        with opener.open(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        user = payload.get("user") if isinstance(payload, dict) else None
        user = user if isinstance(user, dict) else (payload if isinstance(payload, dict) else None)
    except urllib.error.HTTPError as exc:
        user = None
        if exc.code != 401:
            log.warning("身份校验失败（HTTP %s）", exc.code)
    except Exception as exc:
        # 主站不可达时**不放行**：这一层守的是数据，宁可自己进不去，
        # 也不能因为对面抖了一下就对公网敞开。
        raise AccessDenied("身份服务暂时不可达，为保护数据本次拒绝访问。", "auth_unavailable", 503) from exc

    _remember(cookie, now, user)
    return user


def check(cookie: str) -> dict[str, Any]:
    """校验这次请求能不能访问，并解析出它的数据域。

    返回 {"user", "scope", "is_owner"}；拒绝时抛 AccessDenied。
    """
    current = mode()
    if current == "open":
        return {"user": None, "scope": OWNER_SCOPE, "is_owner": True, "is_guest": False}

    user = _whoami(cookie)
    if not user:
        # ── 游客：能看市场，看不见任何人的研究 ──────────────────────
        #
        # 直接 401 挡在门外的问题是**没法引新人**：一个没登录的人点进来
        # 只看到「请先登录」，他不知道这里有什么，也就没有登录的理由。
        #
        # 所以给一个自己什么都不拥有的数据域。全站 27 张按用户隔离的表都装了
        # RLS，游客域一行都匹配不到——**不需要在一百个接口上各写一次判断**，
        # 数据库那一层已经把这件事做完了。而九张全局市场表（行情、K 线、
        # 财报、公告正文…见 pgbackend._GLOBAL_MARKET_TABLES）没有 RLS，
        # 那些本来就是公开事实，谁看都一样。
        #
        # **写入由中间件挡死**（见 main.py 的 credit_context）：
        # 所有游客共用这一个域，放开写等于让游客甲建的档案出现在游客乙那里；
        # 而且花钱的动作全是 POST，挡住写就同时挡住了烧积分。
        #
        # owner 模式不给游客态：那一档的语义就是「钉死，只有站主」。
        if current == "owner":
            raise AccessDenied("这个模块目前只对站主开放。", "not_owner", 403)
        return {"user": None, "scope": GUEST_SCOPE, "is_owner": False, "is_guest": True}

    allowed_ids, allowed_emails = owner_user_ids(), owner_emails()
    email = str(user.get("email") or "").strip().lower()
    user_id = str(user.get("user_id") or "").strip()
    is_owner = bool(user_id and user_id in allowed_ids) or bool(email and email in allowed_emails)

    if current == "owner":
        if not allowed_ids and not allowed_emails:
            raise AccessDenied(
                "本模块已开启只允许站主访问，但没有配置站主是谁。"
                "请在 .env 里设 STOCK_OWNER_EMAILS 或 XM_OWNER_USER_ID。", "owner_unset", 503)
        if not is_owner:
            raise AccessDenied("这个模块目前只对站主开放。", "not_owner", 403)

    if not user_id and not is_owner:
        raise AccessDenied("身份信息不完整，无法确定数据归属。", "no_user_id", 403)
    # 站主落在存量数据域；其他人各有自己的域，互相看不见。
    return {"user": user, "scope": OWNER_SCOPE if is_owner else user_id,
            "is_owner": is_owner, "is_guest": False}


def describe() -> dict[str, Any]:
    """给「数据状态」页说明当前的访问姿态。不泄漏站主邮箱本身。"""
    current = mode()
    return {
        "mode": current,
        "owner_configured": bool(owner_user_ids() or owner_emails()),
        "note": {
            "open": "开放模式：不校验身份，一律落在站主数据域。只应绑 127.0.0.1 本机使用。",
            "owner": "仅站主：只有站主名单里的账号能访问。身份由主站判定，本进程不存密钥。",
            "multi": "多用户：任何登录用户可用，数据按用户隔离；管理员看到的是存量数据域。",
        }[current],
        # **这次请求是不是游客。** 页面靠它决定给「登录才能建档案」的引导，
        # 还是照常给建档入口——不然游客看到的是一个点了就 401 的按钮。
        "is_guest": current_scope() == GUEST_SCOPE,
        # **这次请求是不是站主。** 备份/还原/整库导出是站主专属（require_owner），
        # 而前端此前没有这个信号，于是「备份与恢复」这一项对所有人都亮着，
        # 谁点进去都是撞一脸 403 —— 挡住了，但等于向每个用户公告这里有整站还原。
        "is_owner": is_owner(),
        # 配的是 auto 时，当前姿态是跟运营台开关算出来的，不是写死的。
        # 这一栏让「数据状态」页能说清「现在是仅站主，因为运营台里这个模块还是隐藏」。
        "follows_console": (os.getenv("STOCK_ACCESS") or llm.load_env().get("STOCK_ACCESS") or "").strip().lower() == "auto",
    }
