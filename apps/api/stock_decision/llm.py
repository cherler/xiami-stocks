"""所有模型调用的唯一入口,以及它与虾米伙伴积分账户之间的闸口。

**为什么要收成一处。** 之前 classification / drafting / researching / news / chain_and_reports
各写了一份「拼 body → urlopen → 取 text」,五份代码逐字重复,而且都把 `usage` 字段丢掉了。
计费必须按真实 token 走,丢掉 usage 就等于没有计费依据;超时、重试、错误信息的口径也
各不相同。收成一处之后,加一个字段(比如 usage)只改一个地方。

**闸口是怎么工作的。**

    调用前:按最坏情况(max_tokens + 提示词估算)向主站冻结额度 →
    调用中:模型返回真实 usage →
    调用后:按真实 token 结算,冻多的自动退回;失败则整笔释放,不扣分。

冻结而不是直接扣,是因为「这次要花多少」只有调用完才知道;不冻结就只能事后扣,
而事后扣意味着余额为 0 的人也能先把服务用掉。

**没接入主站时它是透明的。** `XM_API_BASE` 没配(本地单机开发、你自己跑着玩)就整条跳过,
不冻结、不结算、也不报错 —— 但会在返回里如实说明「未接入积分」,不假装扣过。

**它只会扣发起请求的那个人。** 浏览器发起的调用,中间件把用户的 `xm_session` Cookie
放进 contextvar,这里原样转发给主站,主站自己解出是谁。本进程从头到尾不知道 user_id,
也就伪造不了别人。后台任务(夜间分级、定时同步)没有 Cookie,走内网密钥 + 显式 user_id,
这条路要在 .env 里显式配 `XM_INTERNAL_KEY` 与 `XM_OWNER_USER_ID` 才打开。
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("stock_decision.llm")

ENV_KEYS = (
    "MINIMAX_API_KEY",
    "MINIMAX_BASE_URL",
    "MINIMAX_MODEL",
    "XM_API_BASE",
    "XM_INTERNAL_KEY",
    "XM_OWNER_USER_ID",
    "XM_CREDIT_MODULE",
    # 联网检索（见 websearch.py）。免费额度那把在前，付费那把兜底。
    # **漏在这个白名单外面的键会静默读不到**：实测漏了之后，
    # 估价接口回的是「没有配 TAVILY_API_KEY」，而 .env 里明明写着，
    # 排查方向会整个跑偏到"key 是不是失效了"。
    "TAVILY_API_KEY",
    "TAVILY_API_KEY_VIP",
    "FIRECRAWL_API_KEY",
    # 访问控制（见 access.py）。白名单漏了键会静默地读不到——
    # 而这两个键漏读的后果是「以为锁上了其实没锁」或「以为开着其实全挡了」。
    "STOCK_ACCESS",
    "STOCK_OWNER_EMAILS",
    "STOCK_DB_BACKEND",
    # 后台整理要不要调模型（默认否，见 scheduler.background_ai_enabled）
    "STOCK_BACKGROUND_AI",
    # PG 连接参数：pgbackend.dsn() 要用，白名单漏了就会静默连回默认的本机开发库
    # 备份要一个能看见所有行的账号（开了 RLS 之后应用角色只看得见自己那份）
    "PG_ADMIN_USER",
    "PG_ADMIN_PASSWORD",
    "PG_HOST",
    "PG_PORT",
    "PG_DB",
    "PG_USER",
    "PG_PASSWORD",
    "STOCK_PG_SCHEMA",
)

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def load_env() -> dict[str, str]:
    """环境变量优先,其次仓根的 .env。两边都没有就是空串(调用方据此判断"没配")。"""
    config = {key: os.environ.get(key, "") for key in ENV_KEYS}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in config and not config[key]:
                config[key] = value.strip()
    return config


def ai_available() -> tuple[bool, str]:
    config = load_env()
    if not config["MINIMAX_API_KEY"] or not config["MINIMAX_BASE_URL"]:
        return False, "没有配置 MINIMAX_API_KEY / MINIMAX_BASE_URL,只用规则分级"
    return True, f"模型 {config['MINIMAX_MODEL'] or '未指定'}"


def model_name() -> str:
    return load_env().get("MINIMAX_MODEL") or "MiniMax-M3"


# ── 调用发起人 ────────────────────────────────────────────────────────────
#
# 用 contextvar 而不是把 request 一路传下去:模型调用点埋在 repository 深处,
# 中间隔着七八层与身份毫无关系的函数。为了记账把 request 穿进去,会让这些函数
# 从此都依赖 Web 框架 —— 后台任务、脚本、测试就都调不动了。

@dataclass
class Principal:
    """这次调用该记在谁头上。cookie 与 internal 二选一。"""

    cookie: str = ""            # 浏览器发起:原样转发的 Cookie 头
    user_id: str = ""           # 后台任务发起:显式指明扣谁
    internal_key: str = ""

    def headers(self) -> dict[str, str]:
        if self.cookie:
            return {"cookie": self.cookie}
        if self.internal_key:
            return {"x-internal-key": self.internal_key}
        return {}

    def usable(self) -> bool:
        return bool(self.cookie) or bool(self.internal_key and self.user_id)


_principal: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "stock_decision_principal", default=None)

# Hosted conversational jobs must not inherit the interactive fallback-to-free.
_strict_billing: contextvars.ContextVar[bool] = contextvars.ContextVar('strict_billing', default=False)


def set_principal(principal: Principal | None) -> contextvars.Token:
    return _principal.set(principal)


def reset_principal(token: contextvars.Token) -> None:
    _principal.reset(token)


# 一次请求里所有模型调用的累计花费。
#
# 「这次花了多少分」不能由单次调用回答:分级一次要发好几批、简报要读整库。
# 所以按请求累计,接口在最后统一读一次。也用 contextvar,理由同上。
_accounting: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "stock_decision_accounting", default=None)


def start_accounting() -> contextvars.Token:
    return _accounting.set({"credits": 0, "tokens": 0, "calls": 0, "metered": 0})


def reset_accounting(token: contextvars.Token) -> None:
    _accounting.reset(token)


def _record(meter: "Meter", tokens: int) -> None:
    bucket = _accounting.get()
    if bucket is None:
        return
    bucket["credits"] += meter.cost
    bucket["tokens"] += tokens
    bucket["calls"] += 1
    bucket["metered"] += 1 if meter.active else 0


def collected() -> dict[str, Any]:
    """本次请求到目前为止的花费。没开始记账(后台任务、脚本)时返回全零。"""
    bucket = _accounting.get() or {"credits": 0, "tokens": 0, "calls": 0, "metered": 0}
    return {
        "credits": bucket["credits"],
        "tokens": bucket["tokens"],
        "calls": bucket["calls"],
        # 有任何一次真正计了费,这次就是计费的;一次都没有(未登录/未接入)则如实说明。
        "metered": bucket["metered"] > 0,
    }


def background_principal() -> Principal | None:
    """后台任务用的发起人。没配内网密钥/站主 user_id 就返回 None(于是不计费)。

    这是**没有归属信息**时的兜底(整库同步这类不属于任何人的活)。
    凡是知道这次是在替谁干活的,一律用 principal_for_scope()。
    """
    config = load_env()
    if config["XM_INTERNAL_KEY"] and config["XM_OWNER_USER_ID"]:
        return Principal(internal_key=config["XM_INTERNAL_KEY"], user_id=config["XM_OWNER_USER_ID"])
    return None


def principal_for_scope(scope: str | None) -> Principal | None:
    """替某个数据域干活时的发起人 —— 账记在这个域的主人头上。

    后台任务此前一律走 background_principal(),也就是所有人的消耗都记到站主账上。
    但积分闸口本来就是为模型调用准备的,后台调用并不特殊:花的 token 跟用户在页面上
    点一次没有区别,唯一要回答的是记给谁,而逐用户跑的任务本来就知道答案。

    站主域是哨兵值 `__owner__`,不是真实 user_id,要换成 XM_OWNER_USER_ID;
    其余数据域的值本身就是 user_id。取不到就返回 None —— 于是不计费,
    而不是记错人:记错账比不记账更难查。
    """
    from .access import OWNER_SCOPE

    config = load_env()
    key = config["XM_INTERNAL_KEY"]
    if not key or not scope:
        return None
    user_id = config["XM_OWNER_USER_ID"] if scope == OWNER_SCOPE else scope
    if not user_id:
        return None
    return Principal(internal_key=key, user_id=user_id)


# ── 积分闸口客户端 ────────────────────────────────────────────────────────

class CreditsError(RuntimeError):
    """闸口明确拒绝(余额不足等)。与"闸口不可用"区分开——后者不该挡住调用。"""

    def __init__(self, message: str, code: str = "credits") -> None:
        super().__init__(message)
        self.code = code


def _post(base: str, path: str, payload: dict[str, Any], headers: dict[str, str],
          timeout: int = 15) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
    )
    # 主站在同一台机器上,别让系统代理把内网请求绕出去。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {}


@dataclass
class Meter:
    """一次调用的计费状态。闸口没接入时 `active` 为 False,其余字段保持零值。"""

    module: str
    task: str
    active: bool = False
    hold_id: str = ""
    held: int = 0
    cost: int = 0
    tokens: int = 0
    # 这一轮用掉几次联网搜索。**冻结和结算都要带上它**——
    # 只带 tokens 的话，搜索这部分永远不会被收，而它是真金白银。
    searches: int = 0
    note: str = "未接入积分(本地单机模式)"
    _base: str = ""
    _headers: dict[str, str] = field(default_factory=dict)
    _user_id: str = ""
    # 结算与释放的幂等键在冻结时就固定下来:重试要落在同一个键上才叫幂等。
    _commit_key: str = ""
    _release_key: str = ""
    # 这次调用在未计费台账里的行号。0 = 没落账（本地单机、未登录，或闸口正常）。
    _unbilled_id: int = 0

    def _key(self, scope: str) -> str:
        # 幂等键必须**每次调用唯一**:同一个 hold 结算两次是两笔账,不是重放。
        return f"{self.module}:{self.task}:{scope}:{uuid.uuid4().hex[:20]}"

    def commit(self, tokens: int) -> None:
        if not self.active:
            # **没计上费的那些也要收尾。** 只有跑完才知道实际烧了多少 token，
            # 而对账要的正是这个数——只记「漏了一次」没法算出漏了多少钱。
            if self._unbilled_id:
                from . import billing_ledger
                billing_ledger.finish(self._unbilled_id, tokens, self.searches,
                                      credits_for_report(self.searches, tokens))
            return
        payload = {"module": self.module, "task": self.task, "hold_id": self.hold_id,
                   "tokens": max(0, tokens), "searches": self.searches,
                   "idempotency_key": self._commit_key}
        if self._user_id:
            payload["user_id"] = self._user_id
        status, data = _post(self._base, "/v1/credits/commit", payload, self._headers)
        if status >= 400:
            # 结算失败不能反过来打断已经成功的业务调用。冻结会被主站的
            # release_stale_holds 兜底回收,这里只留下可查的日志。
            log.error("积分结算失败 hold=%s status=%s data=%s", self.hold_id, status, data)
            self.note = "结算失败,已记日志(冻结将由主站超时释放)"
            return
        self.cost = int(data.get("cost") or 0)
        self.tokens = int(data.get("tokens") or 0)
        self.note = f"本次消耗 {self.cost} 积分"

    def release(self) -> None:
        if not self.active or not self.hold_id:
            return
        payload = {"hold_id": self.hold_id, "idempotency_key": self._release_key}
        if self._user_id:
            payload["user_id"] = self._user_id
        status, _ = _post(self._base, "/v1/credits/release", payload, self._headers)
        if status >= 400:
            log.error("积分释放失败 hold=%s status=%s", self.hold_id, status)
        self.note = "调用失败,已退回冻结额度"

    def summary(self) -> dict[str, Any]:
        return {"metered": self.active, "credits": self.cost, "tokens": self.tokens,
                "searches": self.searches, "note": self.note}


def _fall_back_unbilled(meter: Meter, reason: str, estimated_tokens: int) -> None:
    """闸口没计上费时的统一收尾：落台账，并判断该不该停手。

    **顺序是先记账再判断。** 反过来的话，压垮骆驼的那一次不会被记下来，
    而它恰恰是最该被记下来的一次。

    停手时抛的是 CreditsError —— 跟"余额不足"同一条通道，
    前端已经会把它显示成一句人话，不必再多一种错误类型。
    """
    from . import billing_ledger

    meter._unbilled_id = billing_ledger.record(
        meter.module, meter.task, reason, estimated_tokens, meter.searches)
    meter.note = f"{reason}，本次未计费（已记台账）"
    if billing_ledger.paused():
        # 这条 error 级日志就是告警本身：连着十分钟漏计二十次以上，
        # 不是抖一下，是真宕了，需要有人去看。
        log.error("积分闸口连续不可用（%s 分钟内 %s 次未计费），AI 功能暂停",
                  billing_ledger.WINDOW_MINUTES, billing_ledger.recent_count())
        raise CreditsError(
            "积分服务连不上，为避免漏计费，AI 功能暂时停用；恢复后会自动放开。",
            "gate_down")


def reserve(module: str, task: str, estimated_tokens: int, searches: int = 0) -> Meter:
    """冻结额度。闸口没配就返回一个不激活的 Meter,调用照常进行。

    ## searches:联网搜索也要计费

    **这条路以前只报 tokens,于是搜索一次都没收过钱。** 一份深度报告搜 5 次、
    实扣 3 分，而公式（⌈tokens/5000⌉ + 搜索数 × SEARCH_COEFF）该收 9 分。
    闸口的公式一直是对的，少的是把搜索次数送过去的这个参数。
    """
    from . import billing_ledger

    meter = Meter(module=module, task=task)
    meter.searches = max(0, int(searches or 0))
    config = load_env()
    base = config["XM_API_BASE"]
    if not base:
        if _strict_billing.get():
            raise CreditsError('账户计费服务未配置，助手暂时不可用。')
        return meter
    principal = _principal.get() or background_principal()
    if not principal or not principal.usable():
        if _strict_billing.get():
            raise CreditsError('无法确认本次用量的账户，已停止处理。')
        meter.note = "未识别到登录身份,本次不计费"
        return meter

    meter._base = base
    meter._headers = principal.headers()
    meter._user_id = principal.user_id
    meter._commit_key = meter._key("commit")     # 提前生成:重试时用的是同一个键
    meter._release_key = meter._key("release")
    payload = {"module": module, "task": task, "estimated_tokens": max(0, estimated_tokens),
               "searches": meter.searches,
               "idempotency_key": meter._key("reserve")}
    if principal.user_id:
        payload["user_id"] = principal.user_id

    try:
        status, data = _post(base, "/v1/credits/reserve", payload, meter._headers)
    except Exception as exc:
        if _strict_billing.get():
            raise CreditsError('积分服务暂时不可达，助手已暂停本次处理。') from exc
        # 闸口连不上 ≠ 用户没钱。挡住调用会让主站抖一下就把整个研究台弄瘫,
        # 而漏计的这一次有日志可查、金额也有限。两害相权取其轻。
        #
        # **但这个"两害相权"原来没有上限**：闸口宕一天就免费送一天，
        # 事后连漏了多少都算不出来。所以现在漏计的每一次都落台账，
        # 并且连着漏得太多就停手（阈值见 billing_ledger）。
        log.warning("积分闸口不可达,本次不计费:%s", exc)
        _fall_back_unbilled(meter, billing_ledger.REASON_UNREACHABLE, estimated_tokens)
        return meter

    if status == 402:
        raise CreditsError(data.get("error") or "AI 额度不足。", "no_credits")
    if status == 401:
        if _strict_billing.get():
            raise CreditsError('账户验证已失效，请重新登录。')
        meter.note = "未登录,本次不计费"
        return meter
    if status >= 400:
        if _strict_billing.get():
            raise CreditsError('积分服务暂时无法确认额度，请稍后再试。')
        log.warning("积分冻结被拒 status=%s data=%s", status, data)
        _fall_back_unbilled(meter, billing_ledger.REASON_REJECTED, estimated_tokens)
        return meter

    if _strict_billing.get() and not data.get('hold_id'):
        raise CreditsError('积分服务未确认额度，已停止本次处理。')
    meter.active = True
    meter.hold_id = str(data.get("hold_id") or "")
    meter.held = int(data.get("held") or 0)
    meter.note = f"已冻结 {meter.held} 积分,按实际用量结算"
    return meter


def credit_state() -> dict[str, Any]:
    """本模块的计费状态：接没接入、单价怎么算、当前还剩多少。

    余额要用发起人的身份去主站问；没接入或没登录就如实说明，不显示 0（0 会被读成
    「你没钱了」，而事实是「这里根本没在计费」）。
    """
    config = load_env()
    base = config["XM_API_BASE"]
    state: dict[str, Any] = {
        "connected": bool(base),
        "module": config["XM_CREDIT_MODULE"] or "stocks",
        "balance": None,
        "available": None,
        "note": "未接入虾米伙伴积分，本地单机模式下所有 AI 功能不计费。",
        "pricing": None,
    }
    if not base:
        return state

    principal = _principal.get() or background_principal()
    headers = principal.headers() if principal else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        request = urllib.request.Request(base.rstrip("/") + "/v1/credits/quote?module="
                                         + state["module"] + "&tokens=0", headers=headers)
        with opener.open(request, timeout=10) as response:
            quote = json.loads(response.read().decode("utf-8"))
        state["pricing"] = {
            "token_bucket": quote.get("token_bucket"),
            "multiplier": quote.get("multiplier"),
            "formula": f"⌈tokens/{quote.get('token_bucket')}⌉ × {quote.get('multiplier')}，最少 1 分",
        }
    except Exception as exc:
        state["note"] = f"积分服务暂时不可达：{exc}"
        return state

    try:
        # 后台身份要带上 user_id：内部密钥这条路服务端不知道查谁。
        suffix = f"?user_id={principal.user_id}" if principal and principal.user_id else ""
        request = urllib.request.Request(base.rstrip("/") + "/v1/credits/account" + suffix,
                                         headers=headers)
        with opener.open(request, timeout=10) as response:
            account = json.loads(response.read().decode("utf-8"))
        state["balance"] = account.get("balance")
        state["available"] = account.get("available")
        state["note"] = "AI 调用按实际 token 计费，从虾米伙伴账户扣。"
    except urllib.error.HTTPError as exc:
        state["note"] = "未登录虾米伙伴，AI 调用暂不计费。" if exc.code == 401 else f"查询余额失败（HTTP {exc.code}）"
    except Exception as exc:
        state["note"] = f"查询余额失败：{exc}"
    return state


# ── 模型调用 ──────────────────────────────────────────────────────────────

# 提示词的 token 估算。中文按每字约 1 token 上取整,再加 max_tokens 作为输出上限。
# 只用于冻结额度的"最坏情况",结算永远按真实 usage,估高了只影响可用余额。
# 一分等于多少 token。**这个数原来只写在 assessment.py 的一句注释里**，
# 而它是所有事前估价的共同分母——写在两处迟早会漂开。
TOKENS_PER_CREDIT = 5000

# 一次联网搜索折算多少积分。**必须跟主站 pricing.SEARCH_COEFF 一致。**
#
# 这里再写一份是为了「事前报价」——报价要在动手之前给出来，不该为了算个价钱
# 先往主站发一次请求。真正扣钱的是主站，这份只用来显示。
# 两处不一致的话，页面上报 8 分、实扣 9 分，而没有任何地方会报错。
SEARCH_CREDIT_COEFF = 1.25


def credits_for_report(searches: int, model_tokens: int) -> int:
    """报告积分 = ⌈ 搜索数 × 系数 + ⌈tokens / 5000⌉ ⌉，跟主站同一条公式。"""
    import math

    buckets = -(-max(0, model_tokens) // TOKENS_PER_CREDIT)
    return max(1, math.ceil(max(0, searches) * SEARCH_CREDIT_COEFF + buckets))


# ── 读文档的定价：**跟通用公式分开** ──────────────────────────────────────
#
# 通用公式（TOKENS_PER_CREDIT=5000）把输入输出一视同仁，而读一份 PDF
# **99% 是输入**：那份 64 万字的年报按通用价是 128 分（约 14 元），
# 而模型真实成本不到 1 元。按通用价卖，这个功能没人敢用第二次。
#
# 定价基准：DeepSeek V4-Flash 官方价（2026-08-17 查，off-peak，汇率 7.1）
#
#     输入（未命中缓存）  $0.22/M  →  1.56 元/M
#     输入（命中缓存）    $0.007/M →  0.05 元/M
#     输出              $0.66/M  →  4.69 元/M
#
# 乘 2.5 倍，再按线上积分单价 0.11 元/分（大包 ¥99/900 分，最保守那一档）换算：
#
#     读进去  3.9 元/M  →  35 分/M   →  1 分 ≈ 28,000 token，取整 25,000
#     写出来 11.7 元/M  → 107 分/M   →  1 分 ≈  9,300 token，取整  8,000
#     追问   0.13 元/M  →   1 分/M   →  几乎免费，但不标 0（会被当成 bug）
#
# **命中缓存那一档是这个功能的关键**：「上传一份年报连着问五个问题」在通用定价下
# 是五次全价，在这里是一次全价 + 四次几乎免费。
READ_TOKENS_PER_CREDIT = 25_000        # 读进去的
WRITE_TOKENS_PER_CREDIT = 8_000        # 写出来的
CACHED_TOKENS_PER_CREDIT = 150_000     # 同一份文件追问（命中缓存）


def credits_for_document(read_tokens: int, write_tokens: int = 0,
                         cached: bool = False) -> int:
    """读一份文档要几分。**输入输出分开算** —— 见上面那段。

    `cached=True` 是同一份文件的追问：内容已经在模型的前缀缓存里，
    真实成本掉三十倍，这里也跟着掉。
    """
    per = CACHED_TOKENS_PER_CREDIT if cached else READ_TOKENS_PER_CREDIT
    read = -(-max(0, read_tokens) // per)
    write = -(-max(0, write_tokens) // WRITE_TOKENS_PER_CREDIT)
    return max(1, read + write)


def credits_for(tokens: int) -> int:
    """token 数换成分。**向上取整**：估价宁可高一点。

    冻结额本来就按上界估、结算按真实用量，所以估高只影响可用余额显示，
    不会多收；而估低会让人以为便宜，点下去才发现不是。
    """
    return max(1, -(-tokens // TOKENS_PER_CREDIT))


# 每个会花钱的动作，点之前大概要几分。
#
# **原来 11 个动作里只有 1 个事前告诉你要花多少**，另外 17 处是事后才显示。
# 对一个按 token 计费的产品，"点了才知道多少钱"的结果不是省着用，是不敢用——
# 而这几个功能恰恰是这个产品最贵重的部分。
#
# 这里给的是**典型值**，不是承诺：真实用量取决于喂进去多少字。
# 页面上要写"约"，并且结算永远按真实 usage。
TYPICAL_TOKENS = {
    "inbox-classify": 3000,        # 一批公告标题
    "counter-match": 2500,         # 公告 × 认错条件比对
    "news-match": 2500,
    "evidence-polarity": 1500,     # 一段证据判极性
    # 起草一条逻辑。**从 3000 提到 75000 是因为它现在自己查库**（见 company_tools）：
    # 以前是一次问答喂 2300 字，现在是三轮工具循环、累计入参 7~9 万字。
    # 8 万字 ÷ 1.2 ≈ 6.7 万 token（**字不是 token**，见下面 devils-advocate 那条）。
    # 实测三家公司各跑一轮得到的数，不是拍的。
    "thesis-draft": 65000,
    "method-assessment": 6000,     # 八个方法逐个过
    # 涨跌归因那段解释。入参是规则层算好的事实表 + 判定表（JSON），
    # **实测三家：5682 / 10028 / 10066 字**，取上沿 10000 字 ÷ 1.2 ≈ 8300 token，
    # 加上 900 的输出上限。不是拍的。
    "rally-narrate": 9200,
    # 一批公告里找承诺。**从 5000 提到 100000 是因为它现在读公告原文了**
    # （见 disclosure.py）：以前每条只喂十四个字的标题，现在要读几十份正文。
    #
    # 这个数是实测来的，不是拍的：四家公司各跑一轮，入参 8~12 万字、4~5 次调用。
    # 10 万字 ÷ 1.2 ≈ 8.3 万 token。
    # 旧的报价会让人以为这是个便宜动作，而它现在是仅次于反方 Agent 的第二贵。
    "promise-extract": 83000,
    # 工具循环 + 每条主张再并行复核一遍，全站最贵的一个。
    #
    # **250000 是错的，两个错叠在一起：**
    #
    # 一、字当成了 token。上一版写「累计入参 25 万字」然后把 25 万填进这张
    #     以 token 为单位的表。中文大约 1.2 字一个 token，字数直接当 token
    #     用会高估两成——这张表里几个大数都有这个毛病。
    #
    # 二、拿最坏情况当典型值。这张表叫 TYPICAL_TOKENS，而 250000 假设的是
    #     跑满 6 轮、9 个工具全调一遍。实测（中国平安，全部工具各调一次）：
    #
    #         工具返回总量        26,110 字（最大的一个 7,124，没有一个接近
    #                             run_loop 里那个 12000 的截断线）
    #         每轮固定开销         3,145 字（系统提示 + 工具定义 + 问题）
    #         典型 3 轮 4 工具    60,201 字 ≈  50,000 token → 11 分
    #         最坏 6 轮 9 工具   156,698 字 ≈ 131,000 token → 27 分
    #
    # 所以典型值填 55000。**报价不是承诺，结算永远按真实 usage**
    # （见 Completion.tokens → meter.commit），估高不会多收，
    # 但会把人吓得不敢点——而这是唯一一个会主动推翻你判断的功能。
    # **55000 又低了，2026-08-14 拿真账号在线上量的：**
    #
    #     普通问法   查 7 次库   实扣 18 分（≈ 90,000 token）
    #     问细一点   查 15 次库  实扣 36 分（≈ 180,000 token）
    #
    # 55000 = 11 分，比典型情况低了六成 —— 而这张表自己的规矩是
    # 「估高不会多收，估低会让人以为便宜、点下去才发现不是」。
    # 上一版按"典型 3 轮 4 工具"推算，实测轮数比那多一倍以上：
    # 反方会一路追着查（theses → financials → industry_metrics → segments
    # → valuation → announcements → promises → peers → announcement_text）。
    #
    # 取 90000（18 分）= 实测的普通问法。问得细会更贵，但那张表叫
    # TYPICAL_TOKENS，不叫 MAX——最坏情况不该当典型值（上一版就是这么错到 250000 的）。
    "devils-advocate": 90000,
    "deep-report": 20000,          # 分章长文
    # 主题产业链：3 次公开检索 + 一次结构化整理；结果仍全部待用户核验。
    # 三轮公开检索的资料会连同提示词送入模型；只按 4,200 输出 token 估算会低估两倍以上。
    "industry-chain-draft": 30000,
    "screen": 8000,                # 一批候选写评语
    # AI 选股点一下的**总量**：翻译 + 挑选两次调用加起来。
    #
    # 这张表是给页面报价用的（typical_credits），而用户点的是一个动作、
    # 不是两次调用——分开挂两个价，他看到的是 1 分，实际扣 3 分。
    # 冻结额跟这张表无关，走的是每次调用现算的 estimate_tokens。
    #
    # 入参量（现金流那条默认问法，全 A 命中 955 家取前 40）：
    #     翻译   system 993 + user 1361 + 出参 1200 =  3554 字
    #     挑选   system 963 + user 10570 + 出参 3000 = 14533 字
    #     合计 18087 字 ÷ 1.2 ≈ 15000 token → 3 分
    #
    # **真跑一次是 9397 token（2 次调用），也就是 2 分。** 这里仍填 15000：
    # 上面那个数是按 max_tokens 跑满算的上界，而报价宁可高一点——
    # 估低会让人以为便宜，点下去才发现不是。结算永远按真实 usage。
    #
    # **联网那种问法要另加搜索费**：2 次搜索 × 1.25 ≈ 再多 3 分。
    # 这一条没法进这张表（表只认 token），所以写在页面的确认文案里。
    "ai-pick": 15000,
}


def typical_credits(task: str) -> int | None:
    """这个动作点下去大概几分。不认识的动作返回 None——**不要瞎猜一个数**。"""
    tokens = TYPICAL_TOKENS.get(task)
    return credits_for(tokens) if tokens else None


# 冻结额里替 max_tokens 出场的那个数：**一次调用大概会写多少输出**。
#
# ## 为什么冻结额不能跟 max_tokens 挂钩
#
# max_tokens 是「最多允许写多长」，不是「预计会写多长」。两者差一个数量级：
# 实测反方那段最长的答案 5527 字 ≈ 4600 token，而为了永远不被掐断，
# max_tokens 给到了 100000。拿 100000 去冻额度，等于按二十倍的预期值冻，
# 结果是余额少的人被一个「额度不足」挡在门外 —— **而那次调用他其实付得起**。
#
# 使用者 2026-08-14 拍板：「一次因为 max_tokens 不够导致失败，就会影响我们的产品」
# 「冻结不要跟模型最多的 max_tokens 挂钩」。
#
# ## 这么改会不会少收钱
#
# 会，但只在极少数情况下，而且有垫。闸口那边写得很清楚：
# **「结算额永远 min(实际, 冻结) —— 冻多了自动退，冻少了不补收」**
# （xiamimate-tools-backend/app/routes/credits_gateway.py）。所以冻少了就是少收。
#
# 垫在入参那一侧：入参这里数的是**字符数**，而中文大约 1.2 字才一个 token，
# 所以入参项本身就比真实 token 高两成。反方那个最贵的调用实测：
#
#     冻结 = 60000 字 + 8000        = 68000 → 14 分
#     实际 = 50000 token + 4600     = 54600 → 11 分   ← 仍然冻得够
#
# 要少收，得输出真的超过八千 token 且把入参那两成垫也吃掉 —— 那时候片子
# 本来也该被截断了。**用极少数的少收，换永远不被截断**，这是使用者定的取舍。
HOLD_OUTPUT_TOKENS = 8000


def estimate_tokens(system: str, user: str, max_tokens: int) -> int:
    """冻结额的估算。**第三个参数只作上限参考，不直接进账**（见 HOLD_OUTPUT_TOKENS）。"""
    return len(system) + len(user) + min(max_tokens, HOLD_OUTPUT_TOKENS)


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    meter: Meter | None = None

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def billing(self) -> dict[str, Any]:
        return self.meter.summary() if self.meter else {"metered": False, "credits": 0, "tokens": self.tokens}


def call_tools(system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
               *, task: str, max_tokens: int = 3000, timeout: int = 180) -> dict[str, Any]:
    """带工具调一轮，**返回原始 content 块**，让调用方自己跑循环。

    为什么不在这里替调用方跑完整个循环：工具执行是有副作用风险的动作，
    执行什么、执行几轮、拿到结果怎么校验，都该由那个知道业务的模块决定。
    这一层只负责"把话递过去、把话拿回来"，以及照常记账。

    返回 {"content": [...], "stop_reason": ..., "completion": Completion}。
    """
    config = load_env()
    if not config["MINIMAX_API_KEY"] or not config["MINIMAX_BASE_URL"]:
        raise RuntimeError("模型未配置:缺少 MINIMAX_API_KEY / MINIMAX_BASE_URL")

    module = config["XM_CREDIT_MODULE"] or "stocks"
    # **冻结额按"预计写多少"，不按"最多允许写多少"** —— 见 HOLD_OUTPUT_TOKENS。
    meter = reserve(module, task, len(system) + len(json.dumps(messages, ensure_ascii=False))
                    + min(max_tokens, HOLD_OUTPUT_TOKENS))

    body = json.dumps({
        "model": config["MINIMAX_MODEL"] or "MiniMax-M3",
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "tools": tools,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        config["MINIMAX_BASE_URL"].rstrip("/") + "/v1/messages",
        data=body,
        headers={"content-type": "application/json", "x-api-key": config["MINIMAX_API_KEY"],
                 "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        meter.release()
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "ignore")[:300]
        except Exception:
            pass
        if exc.code == 400 and "tool" in detail.lower():
            raise RuntimeError(
                f"当前模型（{config['MINIMAX_MODEL'] or 'MiniMax-M3'}）似乎不支持工具调用。"
                f"反方 Agent 必须靠工具读库才能保证数字有出处，"
                f"换一个支持 tools 的模型再试。原始返回：{detail}") from exc
        raise RuntimeError(f"模型请求失败(HTTP {exc.code})：{detail}") from exc
    except BaseException as exc:
        meter.release()
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"模型请求失败：{exc}") from exc

    usage = payload.get("usage") or {}
    completion = Completion(
        text="".join(block.get("text", "") for block in payload.get("content", [])
                     if block.get("type") == "text").strip(),
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        meter=meter,
    )
    meter.commit(completion.tokens)
    _record(meter, completion.tokens)
    return {"content": payload.get("content") or [], "completion": completion,
            "stop_reason": payload.get("stop_reason") or ""}


def call(system: str, user: str, *, task: str, max_tokens: int = 2000,
         timeout: int = 120, searches: int = 0) -> Completion:
    """调一次模型,顺带把这次调用记到积分账上。

    task 会进流水与用量统计(形如 `stocks:briefing`),取值就是本站的功能名。
    """
    config = load_env()
    if not config["MINIMAX_API_KEY"] or not config["MINIMAX_BASE_URL"]:
        raise RuntimeError("模型未配置:缺少 MINIMAX_API_KEY / MINIMAX_BASE_URL")

    module = config["XM_CREDIT_MODULE"] or "stocks"
    # searches:这一轮之前用掉的联网搜索次数，跟着这次调用一起计费。
    # **搜索是真金白银，而它以前一次都没被收过**（见 reserve 的说明）。
    meter = reserve(module, task, estimate_tokens(system, user, max_tokens), searches)

    body = json.dumps({
        "model": config["MINIMAX_MODEL"] or "MiniMax-M3",
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        config["MINIMAX_BASE_URL"].rstrip("/") + "/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": config["MINIMAX_API_KEY"],
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        meter.release()
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "ignore")[:200]
        except Exception:
            pass
        raise RuntimeError(f"模型请求失败(HTTP {exc.code}){('：' + detail) if detail else ''}") from exc
    except BaseException as exc:                 # 含 CancelledError:客户端断连也要退冻结
        meter.release()
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"模型请求失败：{exc}") from exc

    text = "".join(block.get("text", "") for block in payload.get("content", [])
                   if block.get("type", "text") == "text").strip()
    usage = payload.get("usage") or {}
    completion = Completion(
        text=text,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        meter=meter,
    )
    meter.commit(completion.tokens)
    _record(meter, completion.tokens)
    return completion
