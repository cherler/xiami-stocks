"""资料分级：**一个占多数的未定义档位，等于这套分级对多数资料不起作用。**

深度报告的第一条纪律是"按资料分级说话"：一手可以当事实，媒体是转述，
研报和观点只能写"市场上有观点认为"。不分级的话，模型会把股吧里的一句话
跟年报里的一句话放在同一个位置上引用。

2026-08-15 拿真账号在线上跑了一份真实报告（格力，5 次检索、10 分），
量下来这套分级对多数资料并没有在起作用：

    检索回来 36 条 → 一手 1、媒体 9、研报 3、观点 2、**其他 21**
    正文 27 处引用 → 其中 **14 处指向「其他」**

翻开那 21 条：财联社、界面新闻、21 世纪经济报道、中国经济网、环球网财经、
搜狐财经、网易财经——都是主流财经媒体，只是不在那张白名单上；
**还有格力自己的官网 www.gree.com**，跟百度百科、境外研究站并排放在同一个桶里。

而提示词里对「其他」**一个字都没有**。四档规矩写得很细，第五档 —— 也就是
数量最多的那一档 —— 没有定义。模型只能自己决定该给它多重的分量。

两头一起补：能认出来的尽量认出来，认不出来的也要在提示词里说清楚该怎么用。
"""

import pytest

from stock_decision import deep_report, websearch


# ------------------------------------------------------------------ 认得出来的要认出来

@pytest.mark.parametrize("url,expected", [
    # 线上那 21 条「其他」里真实出现过的主流财经媒体
    ("https://www.cls.cn/detail/123", "媒体"),          # 财联社
    ("https://m.cls.cn/detail/123", "媒体"),
    ("https://www.jiemian.com/article/1.html", "媒体"),  # 界面新闻
    ("https://www.21jingji.com/article/2.html", "媒体"),  # 21 世纪经济报道
    ("https://www.ce.cn/xwzx/1.shtml", "媒体"),          # 中国经济网
    ("https://finance.huanqiu.com/article/3", "媒体"),   # 环球网财经
    ("https://q.stock.sohu.com/cn/000651/", "媒体"),     # 搜狐财经
    ("https://www.163.com/dy/article/4.html", "媒体"),   # 网易财经
    # 原来就认得的那几类不许被带坏
    ("https://www.cninfo.com.cn/new/disclosure/detail", "一手"),
    ("https://guba.eastmoney.com/news,000651,1.html", "观点"),
    ("https://pdf.dfcfw.com/pdf/H3_AP1.pdf", "研报"),
    ("https://finance.sina.com.cn/stock/1.shtml", "媒体"),
    # 认不出来的仍然是「其他」——**不要为了好看把它们塞进媒体**，
    # 分级的价值在于它是真的
    ("https://baike.baidu.com/item/格力电器", "其他"),
    ("https://straitsresearch.com/report/x", "其他"),
    ("https://app.myzaker.com/news/1", "其他"),
])
def test_a_source_is_graded_by_what_it_actually_is(url, expected):
    assert websearch.source_kind(url) == expected, url


def test_the_company_own_site_counts_as_first_hand_across_its_domains():
    """**同一家公司常有不止一个官网域名。**

    格力档案里登记的是 gree.com.cn，而检索回来的两条官网内容在 www.gree.com 上——
    于是格力自己发的东西被归成「其他」，跟百度百科同级。这正是 own_site 这个字段
    当初为茅台加上的那个问题，只是换了个域名后缀又犯了一次。
    """
    assert websearch.source_kind("https://www.gree.com/about", "www.gree.com.cn") == "一手"
    assert websearch.source_kind("https://www.gree.com.cn/news", "www.gree.com.cn") == "一手"
    assert websearch.source_kind("https://ir.gree.com.cn/x", "www.gree.com.cn") == "一手"


def test_only_the_suffix_is_relaxed_never_the_name():
    """放宽的是后缀，不是名字。gree.com / gree.cn 认，**gree.xyz 不认** ——
    一个抢注域名被当成"公司自己说的"，比归错档严重得多。"""
    assert websearch.source_kind("https://gree.xyz/news", "www.gree.com.cn") == "其他"
    assert websearch.source_kind("https://greenews.com/x", "www.gree.com.cn") == "其他"
    assert websearch.source_kind("https://fake-gree.com/x", "www.gree.com.cn") == "其他"


# ------------------------------------------------------------------ 认不出来的也要有规矩

def test_the_prompt_defines_the_bucket_that_holds_the_most_sources():
    """**四档规矩，五个档位。** 数量最多的那一档没有定义，
    于是过半的引用挂在一个模型只能自己拿主意的档上。"""
    for tier in ("一手", "媒体", "研报", "观点", "其他"):
        assert tier in deep_report.SYSTEM_PROMPT, f"提示词里没有交代「{tier}」该怎么用"


def test_an_unidentified_source_cannot_carry_a_conclusion_alone():
    """「其他」只能当线索。一条判断如果只挂得上「其他」，
    要么找到别的编号一起挂，要么写进 unknowns —— 这句话必须在提示词里。"""
    assert "不能单独支撑" in deep_report.SYSTEM_PROMPT
    assert "unknowns" in deep_report.SYSTEM_PROMPT


# ------------------------------------------------------------------ 花掉的那一轮别丢了

def test_a_report_whose_json_is_broken_is_reformatted_not_thrown_away(monkeypatch):
    """一份报告的钱大头在检索（实测 10 分，5 次联网）。最后一段格式坏了就整份丢掉，
    等于把已经买回来的资料扔进垃圾桶。"""
    import json

    from stock_decision import llm

    good = {"headline": "空调主业承压", "cards": [], "sections": [], "themes": [], "unknowns": []}
    broken = '{"headline": "空调主业承压" "cards": []}'
    replies = [broken, json.dumps(good, ensure_ascii=False)]

    class _C:
        def __init__(self, text):
            self.text = text

    monkeypatch.setattr(llm, "call", lambda *a, **k: _C(replies.pop(0)))
    monkeypatch.setattr(deep_report, "ai_available", lambda: (True, ""))

    out = deep_report.compose({"name": "格力电器", "symbol": "000651"},
                              [{"kind": "媒体", "title": "t", "snippet": "s", "published": ""}],
                              [], {})
    assert out["headline"] == "空调主业承压"
    assert replies == [], "坏 JSON 没有被送去重排"


def test_a_report_cut_off_by_the_budget_says_so(monkeypatch):
    """没写完救不回来（重排一个字都不许加），但**原因要说对**：
    说「格式坏了」会让人去怀疑模型，说「太长了被截断」他才知道这是预算问题。"""
    from stock_decision import llm

    class _C:
        text = '{"headline": "空调主业承压", "cards": [{"title": "主业'

    monkeypatch.setattr(llm, "call", lambda *a, **k: _C())
    monkeypatch.setattr(deep_report, "ai_available", lambda: (True, ""))

    with pytest.raises(RuntimeError, match="掐断"):
        deep_report.compose({"name": "格力电器", "symbol": "000651"},
                            [{"kind": "媒体", "title": "t", "snippet": "s", "published": ""}],
                            [], {})


def test_the_answer_budget_leaves_room_for_the_longest_allowed_report():
    """提示词允许 6 章 × 12 句 × 400 字，而回答上限原来是 5,000 token。
    实测那一份只写了 2,033 token 所以没撞线 —— 但撞线的表现是
    **整份报告连同已经花掉的 5 次检索一起丢掉**，不值得赌。"""
    assert deep_report.MAX_ANSWER_TOKENS >= 20000


def test_every_cap_in_the_code_is_also_stated_in_the_prompt():
    """代码里 sections 切 6、lines 切 12、themes 切 8、unknowns 切 8。
    **只在这一头切的话**，模型写了 8 章、页面只显示 6 章 —— 被切掉的两章
    不报错、不留痕，而它们的钱已经付过了。"""
    for cap in ("最多 6 章", "最多 12 句", "最多 8 个", "最多 8 条"):
        assert cap in deep_report.SYSTEM_PROMPT, cap


def test_the_reformat_shape_matches_the_prompt_it_reformats_for():
    """两处写岔的话，重排会照着另一个形状改：改出来是合法 JSON，字段却对不上，
    然后 compose 里那几个 .get() 静静地读出一堆空值，谁也不会报错。"""
    for field in ("headline", "cards", "sections", "themes", "unknowns", "refs", "direction"):
        assert field in deep_report.REFORMAT_SHAPE, field
        assert field in deep_report.SYSTEM_PROMPT, field
