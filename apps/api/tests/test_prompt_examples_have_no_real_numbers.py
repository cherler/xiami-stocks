"""提示词里的**示范不许带真数字** —— 模型会照抄。

## 这条是撞出来的

DIGEST_SYSTEM_PROMPT 的形状示范里原来写着
`{"label": "营业总收入", "value": "922.78 亿", "note": "同比 +1.30%"}`。
922.78 亿是贵州茅台的营收。读一份寒武纪的研报时，模型把它照抄进了 figures，
**然后自己加了一句「口径有误，实为 7.09 亿元」** —— 而那个数已经印在页面上了。

表格示范更隐蔽：`709 / 1536 / 2674 / 3342` 是寒武纪的真实预测值。
读寒武纪那份时它刚好是对的，换任何一份别的文件就会凭空出现四个"看起来很真"的数。

## 为什么这一条比一般的提示词毛病重

读文档这一页存在的**全部理由**是每个数都能翻回原文核。凭空冒出一个真实存在的
财务数字，读的人核不到之后不会只怀疑这一个数 —— 整份结果都不敢信了，
而这一页除了"可核"以外没有别的价值。

所以：示范里的数一律写成 ○，并且明写一条「你输出的每个数都必须能在原文里找到」。
"""

from __future__ import annotations

import re

from stock_decision import documents as doc

# 提示词里的示范段（第一个 { 到 `规矩：` 之前）
PROMPTS = {
    "DIGEST_SYSTEM_PROMPT": doc.DIGEST_SYSTEM_PROMPT,
    "FUND_SYSTEM_PROMPT": doc.FUND_SYSTEM_PROMPT,
}

# 看起来像财务数字的：带小数点或千分位的多位数。
# 「2023A」「2026-10」这类年份/日期不算，纯个位数（示范里的 [5, 7] 页码）也不算。
_MONEY = re.compile(r"(?<![\d.\-])(?:\d{1,3}(?:,\d{3})+|\d{2,}\.\d+|\d{4,})(?![\d\-])")
# 页码、年份、编号这些是示范里必须有的真值，单独放行
_ALLOWED = {"2023", "2024", "2025", "2026", "2028", "10000", "2023-06-30"}


def _example_block(prompt: str) -> str:
    start = prompt.find("{")
    end = prompt.find("规矩：")
    return prompt[start:end] if 0 <= start < end else prompt


def test_the_shape_examples_carry_no_money_figures():
    for name, prompt in PROMPTS.items():
        block = _example_block(prompt)
        hits = [h for h in _MONEY.findall(block) if h not in _ALLOWED]
        assert not hits, (
            f"{name} 的示范里有看起来像真数的值：{hits}。"
            f"模型会照抄 —— 实测把「922.78 亿」（另一家公司的营收）抄进了一份研报的结果。"
            f"示范里的数一律写成 ○。")


def test_the_digest_prompt_says_every_number_must_be_findable():
    """光把示范改成 ○ 不够，还要明写这条 —— 模型也会从别处编数。"""
    assert "上面那段里没有一个真数字" in doc.DIGEST_SYSTEM_PROMPT
    assert "必须能在给你的原文里找到" in doc.DIGEST_SYSTEM_PROMPT
