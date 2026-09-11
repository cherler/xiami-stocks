"""节点短名：库里那一栏是整段描述，图上要放得下。"""

import pytest

from stock_decision.chain_and_reports import node_label


@pytest.mark.parametrize("raw,expected", [
    # 全部取自库里现有的 16 条 —— 提示词要求"不超过12字、一条只写一个"之后
    # 模型仍然这么写，所以这一层是必须的，不是保险。
    ("再保险公司（如中国再保、瑞士再保、慕尼黑再保）", "再保险公司"),
    ("个人客户（寿险、产险、健康险投保人）", "个人客户"),
    # 冒号先于斜杠切：斜杠在「团体/法人客户」里是名字的一部分，不是列表分隔符。
    # 所以这里留下的是「资产管理/投资标的」而不是「资产管理」—— 9 个字放得下，信息也更全。
    ("资产管理/投资标的：债券、股票、不动产、基础设施项目", "资产管理/投资标的"),
    ("团体/法人客户（车险投保人、企业财产险雇主）", "团体/法人客户"),
    ("中国人寿（601628）、中国太保（601601）等寿险公司", "中国人寿"),
    ("综合性金融集团：其他银行系/集团系金融控股对手", "综合性金融集团"),
    ("医院、体检中心、第三方医疗机构", "医院"),
    ("茅台酒", "茅台酒"),                      # 本来就短的不动
])
def test_a_paragraph_becomes_a_node_name(raw: str, expected: str) -> None:
    assert node_label(raw) == expected


def test_a_long_name_without_separators_is_cut_with_an_ellipsis():
    """没有分隔符可切时才硬截，并且要留省略号——不然会看成一个完整的名字。"""
    label = node_label("一个非常非常长的没有任何分隔符号的对手方名称叫法")

    assert len(label) <= 13 and label.endswith("…")


def test_it_never_returns_empty():
    """空标签会在图上留一个点不出来的节点，比显示错的还糟。"""
    assert node_label("（仅括号）") != ""
    assert node_label("、") != ""
