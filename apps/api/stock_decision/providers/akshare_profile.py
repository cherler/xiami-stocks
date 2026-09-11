from datetime import date, datetime
from typing import Any

from .base import InvalidSymbolError, QuoteProviderError
from .stock_sdk import normalize_cn_symbol

WAN = 10_000.0


def _text(value: Any) -> str | None:
    """AKShare 用 NaN、NaT、'--'、'None' 表示缺失；一律转成 None，不留占位字符。"""

    if value is None:
        return None
    if value != value:  # pandas NaN / NaT
        return None
    text = str(value).strip()
    if text in {"", "--", "None", "NaN", "NaT", "nan"}:
        return None
    return text


def _number(value: Any) -> float | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _iso_date(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    for pattern in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[: len(pattern.replace("%Y", "2000").replace("%m", "01").replace("%d", "01").replace("%H:%M:%S", "00:00:00"))], pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _amount_in_yuan(value_in_wan: Any) -> float | None:
    """巨潮与同花顺的股本、注册资金、募集资金均以万为单位。"""

    number = _number(value_in_wan)
    return None if number is None else round(number * WAN, 2)


class AkShareCompanyProfileProvider:
    """公司概况、股本、分红、解禁与公告披露，来自巨潮资讯、同花顺与新浪。

    这里只搬运公开披露的事实，不生成任何评价、评级或操作建议。
    """

    provider_id = "akshare_cninfo_profile"
    display_name = "AKShare / 巨潮资讯"
    category = "公司概况与大事"

    def _canonical(self, symbol: str) -> str:
        canonical = normalize_cn_symbol(symbol)
        if not canonical.startswith(("0", "3", "6")):
            raise InvalidSymbolError(f"当前公司概况源暂不支持代码 {canonical} 所属市场")
        return canonical

    def fetch_company_profile(self, symbol: str) -> dict[str, Any]:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，无法同步公司概况") from exc

        canonical = self._canonical(symbol)
        missing: list[str] = []

        def section(label: str, call: Any) -> Any:
            """任一子接口失败只记录缺口，不让整次同步失败。"""

            try:
                return call()
            except Exception:
                missing.append(label)
                return None

        profile_frame = section("公司概况", lambda: ak.stock_profile_cninfo(symbol=canonical))
        business_frame = section("主营构成", lambda: ak.stock_zyjs_ths(symbol=canonical))
        ipo_frame = section("发行与上市", lambda: ak.stock_ipo_summary_cninfo(symbol=canonical))
        share_frame = section("股本结构", lambda: ak.stock_share_change_cninfo(symbol=canonical, start_date="19900101", end_date=date.today().strftime("%Y%m%d")))
        dividend_frame = section("分红方案", lambda: ak.stock_fhps_detail_ths(symbol=canonical))
        unlock_frame = section("限售解禁", lambda: ak.stock_restricted_release_queue_sina(symbol=canonical))
        disclosure_frame = section(
            "公告披露",
            lambda: ak.stock_zh_a_disclosure_report_cninfo(
                symbol=canonical,
                market="沪深京",
                start_date=(date.today().replace(year=date.today().year - 1)).strftime("%Y%m%d"),
                end_date=date.today().strftime("%Y%m%d"),
            ),
        )
        if profile_frame is None and business_frame is None and share_frame is None:
            raise QuoteProviderError("公司概况来源均未返回数据")

        payload: dict[str, Any] = {"source": self.display_name, "missing_sections": missing}
        payload.update(self._profile_fields(profile_frame, business_frame))
        payload.update(self._share_fields(share_frame))
        payload.update(self._ipo_fields(ipo_frame))
        dividends = self._dividends(dividend_frame)
        payload.update(self._latest_dividend(dividends))
        payload["events"] = self._events(dividends, unlock_frame, disclosure_frame)
        return payload

    def _profile_fields(self, profile_frame: Any, business_frame: Any) -> dict[str, Any]:
        row: dict[str, Any] = profile_frame.iloc[0].to_dict() if profile_frame is not None and len(profile_frame) else {}
        business: dict[str, Any] = business_frame.iloc[0].to_dict() if business_frame is not None and len(business_frame) else {}
        return {
            "full_name": _text(row.get("公司名称")),
            "english_name": _text(row.get("英文名称")),
            "industry": _text(row.get("所属行业")),
            "market": _text(row.get("所属市场")),
            "legal_representative": _text(row.get("法人代表")),
            "registered_capital": _amount_in_yuan(row.get("注册资金")),
            "founded_date": _iso_date(row.get("成立日期")),
            "listed_date": _iso_date(row.get("上市日期")),
            "website": _text(row.get("官方网站")),
            "registered_address": _text(row.get("注册地址")),
            "office_address": _text(row.get("办公地址")),
            "main_business": _text(business.get("主营业务")) or _text(row.get("主营业务")),
            "product_type": _text(business.get("产品类型")),
            "business_scope": _text(row.get("经营范围")) or _text(business.get("经营范围")),
            "introduction": _text(row.get("机构简介")),
        }

    def _share_fields(self, share_frame: Any) -> dict[str, Any]:
        if share_frame is None or len(share_frame) == 0:
            return {"total_shares": None, "circulating_shares": None, "share_structure_date": None, "share_change_reason": None}
        rows = share_frame.to_dict(orient="records")
        rows.sort(key=lambda item: _iso_date(item.get("变动日期")) or "")
        latest = rows[-1]
        return {
            "total_shares": _amount_in_yuan(latest.get("总股本")),
            "circulating_shares": _amount_in_yuan(latest.get("已流通股份")),
            "share_structure_date": _iso_date(latest.get("变动日期")),
            "share_change_reason": _text(latest.get("变动原因")),
        }

    def _ipo_fields(self, ipo_frame: Any) -> dict[str, Any]:
        if ipo_frame is None or len(ipo_frame) == 0:
            return {"issue_price": None, "raised_net": None, "underwriter": None}
        row = ipo_frame.iloc[0].to_dict()
        return {
            "issue_price": _number(row.get("发行价格")),
            "raised_net": _amount_in_yuan(row.get("募集资金净额")),
            "underwriter": _text(row.get("主承销商")),
        }

    def _dividends(self, dividend_frame: Any) -> list[dict[str, Any]]:
        if dividend_frame is None or len(dividend_frame) == 0:
            return []
        dividends = []
        for row in dividend_frame.to_dict(orient="records"):
            dividends.append(
                {
                    "report_period": _text(row.get("报告期")),
                    "plan": _text(row.get("分红方案说明")),
                    "progress": _text(row.get("方案进度")),
                    "payout_ratio": _text(row.get("股利支付率")),
                    "record_date": _iso_date(row.get("A股股权登记日")),
                    "ex_date": _iso_date(row.get("A股除权除息日")),
                    "board_date": _iso_date(row.get("董事会日期")),
                    "total_amount": _text(row.get("分红总额")),
                }
            )
        return dividends

    def _latest_dividend(self, dividends: list[dict[str, Any]]) -> dict[str, Any]:
        implemented = [item for item in dividends if item["ex_date"]]
        latest = max(implemented, key=lambda item: item["ex_date"], default=None)
        return {
            "latest_dividend_period": latest["report_period"] if latest else None,
            "latest_dividend_plan": latest["plan"] if latest else None,
            "latest_dividend_progress": latest["progress"] if latest else None,
            "latest_dividend_payout_ratio": latest["payout_ratio"] if latest else None,
            "latest_dividend_record_date": latest["record_date"] if latest else None,
            "latest_dividend_ex_date": latest["ex_date"] if latest else None,
        }

    def _events(self, dividends: list[dict[str, Any]], unlock_frame: Any, disclosure_frame: Any) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for item in dividends:
            event_date = item["ex_date"] or item["record_date"] or item["board_date"]
            if not event_date or not item["plan"]:
                continue
            detail_parts = [part for part in (item["report_period"], item["progress"], item["total_amount"] and f"分红总额 {item['total_amount']}", item["payout_ratio"] and f"股利支付率 {item['payout_ratio']}") if part]
            events.append(
                {
                    "category": "分红",
                    "event_date": event_date,
                    "title": item["plan"],
                    "detail": " · ".join(detail_parts),
                    "url": None,
                    "source": "同花顺分红方案",
                }
            )
        if unlock_frame is not None:
            for row in unlock_frame.to_dict(orient="records"):
                event_date = _iso_date(row.get("解禁日期"))
                if not event_date:
                    continue
                shares = _number(row.get("解禁数量"))
                value = _number(row.get("解禁股流通市值"))
                detail_parts = []
                if shares is not None:
                    detail_parts.append(f"解禁 {shares / 10_000:.2f} 亿股" if shares >= 10_000 else f"解禁 {shares:.2f} 万股")
                if value is not None:
                    detail_parts.append(f"解禁市值约 {value:.2f} 亿元")
                announce = _iso_date(row.get("公告日期"))
                if announce:
                    detail_parts.append(f"公告于 {announce}")
                events.append(
                    {
                        "category": "解禁",
                        "event_date": event_date,
                        "title": f"限售股上市流通（第 {_text(row.get('上市批次')) or '—'} 批）",
                        "detail": " · ".join(detail_parts),
                        "url": None,
                        "source": "新浪限售解禁",
                    }
                )
        if disclosure_frame is not None:
            for row in disclosure_frame.to_dict(orient="records"):
                event_date = _iso_date(row.get("公告时间"))
                title = _text(row.get("公告标题"))
                if not event_date or not title:
                    continue
                events.append(
                    {
                        "category": "公告",
                        "event_date": event_date,
                        "title": title,
                        "detail": "",
                        "url": _text(row.get("公告链接")),
                        "source": "巨潮资讯公告",
                    }
                )
        return events


company_profile_provider = AkShareCompanyProfileProvider()
