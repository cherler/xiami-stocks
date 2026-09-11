"""联网检索：来源分级与两把 key 的切换。

这里不打真实网络——测的是那几个会让报告出错的判断：
一条资料算一手还是观点、额度用尽时切不切付费那把、失败时会不会疯狂重试。
"""

import urllib.error

import pytest

from stock_decision import websearch


class TestSourceKind:
    """**必须标出来**：一手可以直接当事实引用，二手要写"据某某报道"，
    观点只能当"市场在这样讨论"。不标的话，模型会把股吧里的一句话
    跟年报里的一句话放在同一个位置上引用。
    """

    def test_the_companys_own_site_is_first_hand(self):
        """第一版漏了这个字段，茅台官网发的一季报被归成"其他"——
        跟一个不认识的域名同级，而它恰恰最该当事实引用。"""
        assert websearch.source_kind(
            "https://www.moutaichina.com/mtgf/x.pdf", "www.moutaichina.com") == "一手"

    def test_exchanges_and_regulators_are_first_hand(self):
        assert websearch.source_kind("https://www.cninfo.com.cn/new/disclosure") == "一手"
        assert websearch.source_kind("https://www.sse.com.cn/a") == "一手"

    def test_a_forum_on_a_media_domain_is_still_a_forum(self):
        """guba.eastmoney.com 同时命中 eastmoney —— 顺序反了会被归成媒体，
        于是股吧里的一句话获得了跟证券时报同等的分量。"""
        assert websearch.source_kind("https://guba.eastmoney.com/news,600519,1.html") == "观点"
        assert websearch.source_kind("https://finance.eastmoney.com/a/1.html") == "媒体"

    def test_broker_research_is_its_own_class(self):
        """券商研报比论坛观点重，但仍然是观点不是事实。站内别处已经这么标了。"""
        assert websearch.source_kind("https://pdf.dfcfw.com/pdf/H3_AP2025.pdf") == "研报"

    def test_an_unknown_host_is_not_promoted(self):
        assert websearch.source_kind("https://some-random-blog.example/a") == "其他"


class TestKeyTiers:
    def test_free_quota_goes_first(self, monkeypatch):
        """免费额度是白给的，不用白不用。"""
        monkeypatch.setenv("TAVILY_API_KEY", "free-key")
        monkeypatch.setenv("TAVILY_API_KEY_VIP", "paid-key")
        monkeypatch.setattr(websearch.llm, "load_env", lambda: {})

        assert [tier for tier, _ in websearch.keys()] == ["免费额度", "按量付费"]

    def test_it_switches_to_the_paid_key_when_quota_runs_out(self, monkeypatch):
        """402 = 真没额度了。**不能当场报错让用户干等**，付费那把还能用。"""
        monkeypatch.setenv("TAVILY_API_KEY", "free-key")
        monkeypatch.setenv("TAVILY_API_KEY_VIP", "paid-key")
        monkeypatch.setattr(websearch.llm, "load_env", lambda: {})
        used: list[str] = []

        def fake_call(query, key, days):
            used.append(key)
            if key == "free-key":
                raise urllib.error.HTTPError("u", 402, "no quota", {}, None)
            return {"results": [{"url": "https://stcn.com/a", "title": "t", "content": "c"}]}

        monkeypatch.setattr(websearch, "_call", fake_call)
        hits = websearch.search("茅台")

        assert used == ["free-key", "paid-key"]
        assert hits[0]["tier"] == "按量付费", "没留痕的话「这个月怎么开始扣钱了」没人说得清"

    def test_a_plain_failure_does_not_burn_the_second_key(self, monkeypatch):
        """**429/402 之外不换把。** 换了也是一样的结果，白烧一次额度。"""
        monkeypatch.setenv("TAVILY_API_KEY", "free-key")
        monkeypatch.setenv("TAVILY_API_KEY_VIP", "paid-key")
        monkeypatch.setattr(websearch.llm, "load_env", lambda: {})
        used: list[str] = []

        def fake_call(query, key, days):
            used.append(key)
            raise urllib.error.HTTPError("u", 500, "boom", {}, None)

        monkeypatch.setattr(websearch, "_call", fake_call)
        with pytest.raises(websearch.SearchError):
            websearch.search("茅台")

        assert used == ["free-key"], "500 也去试第二把，等于白烧额度"


class TestGather:
    def test_the_same_article_is_not_counted_twice(self, monkeypatch):
        """同一篇被多个查询命中很常见。不去重的话它在报告里会被当成
        「多个来源都提到」——那是凭空造出来的佐证强度。"""
        monkeypatch.setattr(websearch, "search",
                            lambda q, days=None, own_site="": [
                                {"url": "https://stcn.com/a", "title": "同一篇",
                                 "kind": "媒体", "snippet": "", "score": 1, "published": ""}])

        result = websearch.gather(["问题一", "问题二", "问题三"])

        assert len(result["hits"]) == 1

    def test_it_stops_when_quota_is_gone(self, monkeypatch):
        """额度用完就整体停下，继续搜只是浪费时间。"""
        calls: list[str] = []

        def boom(q, days=None, own_site=""):
            calls.append(q)
            raise websearch.SearchError("两把 key 都用不了：额度")

        monkeypatch.setattr(websearch, "search", boom)
        result = websearch.gather(["一", "二", "三"])

        assert calls == ["一"], "额度没了还接着搜"
        assert result["failures"]

    def test_the_search_budget_is_a_hard_cap(self, monkeypatch):
        """成本封顶写死在代码里，不靠"记得省着点用"。"""
        calls: list[str] = []
        monkeypatch.setattr(websearch, "search",
                            lambda q, days=None, own_site="": calls.append(q) or [])

        websearch.gather([f"问题{i}" for i in range(20)])

        assert len(calls) == websearch.MAX_SEARCHES
