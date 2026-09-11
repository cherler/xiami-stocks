"""产业链位置：年报强制披露的客户与供应商集中度。

原来的「产业链地图」是模型凭世界知识画的四个方框。实测中国平安那张，
上游七条里三条是同一件事（「再保险人」「再保险公司」「再保险公司」，
其中两条字面完全相同），下游是「个人客户」「个人投保人」「个人保险客户」——
三种说法一个意思，而且都不是产业链节点，是空词。

而这件事年报里有确定答案：前五名客户占销售总额多少、前五名供应商占采购总额多少。
实测寒武纪 88.66%、茅台 10.10%，是两种完全不同的生意。

这里守四件事：
- **纯正则解析，不经过模型**——一个抽错的百分比跟对的长得一模一样。
- **不能取第一处命中**：标题在一份年报里出现七到九次，第一处实测落在研发段落上。
- **只看年度报告**：半年报没有这一节，搜到的「前五大客户」在信用风险段里，是另一件事。
- **抽不到就说抽不到**，不猜、不退回让模型编。
"""

from __future__ import annotations

from stock_decision import chain_position as cp

# 深交所模板（格力 2025 年报原文的形状）
SZSE = """主要销售客户和主要供应商情况 公司主要销售客户情况
前五名客户合计销售金额（元） 24,647,540,609.21
前五名客户合计销售金额占年度销售总额比例 14.40%
前五名客户销售额中关联方销售额占年度销售总额比例 2.34%
公司前 5大客户资料 序号 客户名称 销售额（元） 占年度销售总额比例
1 第一名 10,119,088,327.50 5.91%
2 第二名 5,922,757,391.80 3.46%
公司主要供应商情况
前五名供应商合计采购金额（元） 30,000,000,000.00
前五名供应商合计采购金额占年度采购总额比例 32.75%"""

# 上交所模板：一句话写完，金额单位是万元（寒武纪 / 茅台原文的形状）
SSE = ("A.公司主要销售客户及主要供应商情况 √适用 □不适用 "
       "前五名客户销售额 576,030.47 万元，占年度销售总额88.66%；"
       "其中前五名客户销售额中关联方销售额0.00万元，占年度销售总额0.00%。 "
       "前五名供应商采购额 348,825.84 万元，占年度采购总额75.23%。")


def test_szse_template_parses():
    got = cp.parse_section(SZSE)
    assert got["customer_ratio"] == 14.40
    assert got["supplier_ratio"] == 32.75
    assert got["customer_amount"] == 24647540609.21
    assert [item["ratio"] for item in got["top"]] == [5.91, 3.46]


def test_sse_template_parses_despite_the_spaces():
    """**PDF 抽出来的文字到处是空格。**

    「前五名客户销售额 576,030.47 万元」——数字前后、单位前后都可能有空格。
    第一版正则没允许空格，于是寒武纪那条 88.66%（全场最高的客户集中度、
    最该抓到的那个）没抽到，而供应商那条抽到了——看起来像
    「这家只披露了供应商」，而不是「解析器少写了 \\s*」。
    """
    got = cp.parse_section(SSE)
    assert got["customer_ratio"] == 88.66
    assert got["supplier_ratio"] == 75.23
    # 万元要换算成元
    assert got["customer_amount"] == 5760304700.0


def test_nothing_parsed_returns_empty_not_zero():
    """抽不到就是抽不到。**返回 0 会被读成"前五大客户只占 0%"**，
    而那是"极度分散"的意思——跟"没披露"完全相反。"""
    got = cp.parse_section("这段文字里没有任何客户与供应商的集中度披露。")
    assert "customer_ratio" not in got
    assert "supplier_ratio" not in got


def test_extract_skips_hits_that_do_not_parse():
    """**标题在一份年报里出现七到九次**（目录、正文、附注引用），
    第一处实测落在研发段落上。取的是「后面能解析出数字的那一处」。"""
    # 填充要长过 SECTION_SPAN，否则目录那一处的窗口会一直伸到真表格上，
    # 它也解析成功——那样这条测试测的就不是"跳过"了。
    body = ("……目录……主要销售客户和主要供应商情况……见第 38 页……"
            + "无关内容。" * (cp.SECTION_SPAN // 5 + 400) + SZSE)
    got = cp.extract(body)
    assert got["customer_ratio"] == 14.40
    assert got["found_at"] > cp.SECTION_SPAN, "应该跳过了目录里那一处"
    # **摘录必须是真正写着数字的那一段**，不是目录那一行——
    # 点开年报要能一字不差找到它，这是这一页可信度的全部依据。
    assert "前五名客户合计销售金额" in got["excerpt"]
    assert "见第 38 页" not in got["excerpt"]


def test_a_report_without_the_section_says_so():
    """银行与保险的年报里没有这一节——**那是不适用，不是数据缺失**。
    这两件事使用者要做的事完全不同。"""
    got = cp.extract("这是一份银行年报，讲的是存贷款与资本充足率。")
    assert "customer_ratio" not in got
    assert "没有" in got["note"]


def test_the_reading_describes_but_never_scores():
    """**集中不等于差。** 给苹果供货的公司客户集中度极高，
    那是好生意还是坏生意，取决于它有没有被替代的可能——不替使用者下判断。"""
    high = cp.read_position(88.66, None)
    low = cp.read_position(10.1, None)
    assert "88.66" in high and "定价权" in high
    assert "10.1" in low and "分散" in low
    for text in (high, low):
        for word in ("差", "好", "风险高", "建议", "不要", "应当"):
            assert word not in text, f"不该出现评判词：{word} / {text}"
