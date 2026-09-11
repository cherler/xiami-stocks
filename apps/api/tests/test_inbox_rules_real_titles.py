"""分级规则拿**真实公告标题**验，不拿造出来的短句验。

2026-08-14 线上（使用者真实账号）：收件箱 113 条待核验，**全部是「中」**——
一条「高」、一条「低」都没有。而「中」这一档的定义是"规则和模型都拿不准，
留给人手动处理"，于是它就是一个清不完的积压。

查下来最直接的一条：

    PROCEDURAL_PATTERNS 里写着 `董事会决议|监事会决议|董事会会议决议`

而 A 股的标准标题是「第三届董事会**第七次**会议决议公告」——中间隔着「第七次」，
三个模式一条都匹配不上。**拿那 113 条真标题跑：命中 0 条**，
而其中 10 条正是这个形状。最常见的一类程序性公告，永远停在「中」。

这就是为什么规则要拿真标题验：`董事会决议` 这四个字看着没毛病，
造一条「董事会决议公告」测也能过，只有真实标题会照出它匹配不到东西。
"""

import pytest

from stock_decision.classification import classify_by_rules

# 全部摘自使用者线上收件箱（格力电器 / 贵州茅台 / 寒武纪）
BOARD_RESOLUTIONS = [
    "第三届董事会第七次会议决议公告",
    "第十三届董事会第六次会议决议公告",
    "第二届监事会第二十八次会议决议公告",
    "第十三届监事会第四次会议决议公告",
    "第二届董事会第三十六次会议决议公告",
]


@pytest.mark.parametrize("title", BOARD_RESOLUTIONS)
def test_a_board_resolution_is_procedural(title):
    """董监事会决议是最典型的程序性公告 —— 规则本来就想抓它，只是没抓着。"""
    result = classify_by_rules(title)
    assert result["relevance"] == "低", f"{title} 判成了「{result['relevance']}」：{result['reason']}"
    assert result["topic"] == "会议决议"


def test_the_old_contiguous_pattern_would_have_missed_them():
    """钉住这次的教训：**要求四个字连着，就一条真标题都匹配不上。**"""
    import re

    old = r"董事会决议|监事会决议|董事会会议决议"
    assert not any(re.search(old, t) for t in BOARD_RESOLUTIONS), \
        "旧模式居然匹配上了——那这条测试就失去意义了，请重新挑真实标题"


def test_a_substantive_announcement_is_not_swept_into_procedural():
    """放宽不能放过头：真讲事的公告不许被扫进「低」自动忽略掉。

    低这一档会被 tidy_inbox **自动忽略**，误判一条就是把一件真事悄悄埋掉。
    """
    for title in ["关于回购股份进展的公告",
                  "关于第一大股东股份质押的公告",
                  "2026年半年度报告"]:
        assert classify_by_rules(title)["relevance"] != "低", title
