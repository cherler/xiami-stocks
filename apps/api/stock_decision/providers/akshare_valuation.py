from datetime import date, datetime
from typing import Any

from .base import InvalidSymbolError, QuoteProviderError
from .stock_sdk import normalize_cn_symbol


class AkShareValuationProvider:
    """历史估值序列（PE TTM 与 PB），来自百度股市通。

    只搬运历史数值。分位数在本地计算，并且始终附带样本区间与截止日；
    低分位不代表便宜，更不代表应当买入，这一判断留给用户。
    """

    provider_id = "baidu_valuation"
    display_name = "AKShare / 百度股市通"
    category = "历史估值"

    # 百度接口的窗口越长采样越稀疏；近五年这一档的密度最适合算 3 年、5 年分位。
    PERIOD = "近五年"
    METRICS = (("pe_ttm", "市盈率(TTM)"), ("pb", "市净率"))

    def _canonical(self, symbol: str) -> str:
        canonical = normalize_cn_symbol(symbol)
        if not canonical.startswith(("0", "3", "6")):
            raise InvalidSymbolError(f"当前估值源暂不支持代码 {canonical} 所属市场")
        return canonical

    def fetch_valuation_history(self, symbol: str) -> dict[str, Any]:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，无法同步历史估值") from exc

        canonical = self._canonical(symbol)
        points: list[dict[str, Any]] = []
        missing: list[str] = []
        for metric, indicator in self.METRICS:
            try:
                frame = ak.stock_zh_valuation_baidu(symbol=canonical, indicator=indicator, period=self.PERIOD)
            except Exception:
                missing.append(indicator)
                continue
            if frame is None or len(frame) == 0:
                missing.append(indicator)
                continue
            for row in frame.to_dict(orient="records"):
                point_date = self._as_date(row.get("date"))
                value = self._as_number(row.get("value"))
                if point_date is None or value is None or value <= 0:
                    # 非正的 PE 表示亏损期，落到分位里会得到没有意义的排序，这里直接跳过并在页面说明。
                    continue
                points.append({"metric": metric, "point_date": point_date, "value": value})
        if not points:
            raise QuoteProviderError("百度股市通未返回历史估值数据")
        return {"source": self.display_name, "period": self.PERIOD, "missing_metrics": missing, "points": points}

    @staticmethod
    def _as_date(value: Any) -> str | None:
        if value is None or value != value:
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = str(value).strip()[:10]
        try:
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None

    @staticmethod
    def _as_number(value: Any) -> float | None:
        if value is None or value != value:
            return None
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            return None


valuation_provider = AkShareValuationProvider()
