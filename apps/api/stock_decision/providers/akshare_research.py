"""候选公司的"这家公司是干什么的"：简况、官方入口、券商研报。

只看几个财务指标是没法判断一家公司的——不知道它做什么生意，ROE 高低都无从解释。
所以初筛时要先把这三样摆出来：

- **简况**：主营业务与公司简介，来自巨潮资讯（上市公司信息披露指定网站）。
- **官方入口**：交易所页面、巨潮全文检索、东财行情页。这几个是按代码拼出来的，不需要请求，
  永远可用；即使抓取全挂了，用户仍然点得进去自己看。
- **券商研报**：东方财富汇总的个股研报，带机构、评级、日期与 PDF 原文链接。

关于研报里的评级：那是券商的观点，不是本站的判断。所以它必须连着机构名一起显示，
让人知道是谁说的；本站自己不产生任何评级。
"""

from typing import Any

from .base import QuoteProviderError


def _text(value: Any) -> str | None:
    if value is None or value != value:
        return None
    text = str(value).strip()
    return text or None


def official_links(symbol: str, website: str | None = None) -> list[dict[str, str]]:
    """按代码拼出来的官方入口，不发请求，所以永远可用。"""

    prefix = "sh" if symbol.startswith("6") else "bj" if symbol.startswith(("4", "8")) else "sz"
    links = [
        {
            "label": "交易所公司页",
            "url": (
                f"http://www.sse.com.cn/assortment/stock/list/info/company/index.shtml?COMPANY_CODE={symbol}"
                if prefix == "sh"
                else f"https://www.szse.cn/certificate/individual/index.html?code={symbol}"
                if prefix == "sz"
                else f"https://www.bse.cn/company/stock_detail.html?code={symbol}"
            ),
        },
        {"label": "巨潮公告全文检索", "url": f"http://www.cninfo.com.cn/new/fulltextSearch?keyWord={symbol}"},
        {"label": "东财行情与资料", "url": f"https://quote.eastmoney.com/{prefix}{symbol}.html"},
        {"label": "东财研报列表", "url": f"https://data.eastmoney.com/report/{symbol}.html"},
    ]
    if website:
        url = website if website.startswith("http") else f"http://{website}"
        links.insert(0, {"label": "公司官网", "url": url})
    return links


def fetch_brief(symbol: str) -> dict[str, Any]:
    """主营业务与公司简介。取不到就如实返回空，不用行业名硬凑一段描述。"""

    try:
        import akshare as ak
    except ModuleNotFoundError as exc:
        raise QuoteProviderError("AKShare 未安装") from exc

    payload: dict[str, Any] = {"main_business": None, "introduction": None, "website": None, "source": None}
    try:
        frame = ak.stock_profile_cninfo(symbol=symbol)
        row = frame.to_dict(orient="records")[0] if len(frame) else {}
        payload.update(
            {
                "main_business": _text(row.get("主营业务")),
                "introduction": _text(row.get("公司简介")),
                "website": _text(row.get("公司网址")),
                "source": "巨潮资讯",
            }
        )
    except Exception:
        pass
    if not payload["main_business"]:
        try:
            frame = ak.stock_zyjs_ths(symbol=symbol)
            row = frame.to_dict(orient="records")[0] if len(frame) else {}
            business = _text(row.get("主营业务")) or _text(row.get("经营范围"))
            if business:
                payload["main_business"] = business
                payload["source"] = payload["source"] or "同花顺"
        except Exception:
            pass
    return payload


def fetch_reports(symbol: str, limit: int = 5) -> list[dict[str, Any]]:
    """券商研报：机构、评级、日期与 PDF 原文。评级是券商的观点，展示时必须连着机构名。"""

    try:
        import akshare as ak
    except ModuleNotFoundError as exc:
        raise QuoteProviderError("AKShare 未安装") from exc
    try:
        frame = ak.stock_research_report_em(symbol=symbol)
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        title = _text(row.get("报告名称"))
        if not title:
            continue
        rows.append(
            {
                "title": title,
                "org": _text(row.get("机构")) or "机构未标注",
                "rating": _text(row.get("东财评级")),
                "date": str(row.get("日期") or "")[:10],
                "url": _text(row.get("报告PDF链接")),
            }
        )
    rows.sort(key=lambda item: item["date"], reverse=True)
    return rows[:limit]
