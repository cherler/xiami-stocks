"""钱从哪来、去了哪 —— 一张桑基图，每一根流量都是报表上的一行。

年报、中报、三季报、一季报都能画（`period_span` 把口径带下去）。

## 为什么是桑基图，而不是又一张饼

饼图回答「构成」，桑基图回答**「流向」**。而对一份年报，真正要问的是流向：

    赚到的钱有多少分给了你，有多少投回了生意里，有多少趴在账上不动。

这件事表格里其实都有，只是分散在三张报表的不同页上，而且**要减一次才看得见**。
减出来的那个数恰恰是最要紧的一个：2025 年茅台经营现金流 615.2 亿、
分红与利息付出 672.4 亿、资本开支 31.3 亿 —— **相加超出了 88.5 亿**，
也就是当年派的息动用了账上的存量。这在表格里要翻两页再做一次减法；
在桑基图上是一眼看见的一根反向的流。

## 这一页的纪律：每一根流量都能指回一个科目名

跟产业链底图同一条规矩。所以：

- **能落到具体科目的，写科目原名**（「分配股利、利润或偿付利息所支付的现金」
  不缩写成「分红」—— 它里面确实还含利息，缩写就是在替使用者做一次没告诉他的合并）
- **倒算出来的一律标成倒算**（`derived=True`）。利润表那张里的「税金与其他」
  是收入减掉已知科目剩下的，它不是任何一行报表数据。
  不标出来的话，它跟旁边那些真科目在图上长得一模一样。
- **凑不齐就不画**，不用零填。缺一个科目的桑基图会把缺口摊到别的流上，
  而那正好是最难发现的一种错。

## 单位

一律用元，前端自己换算成亿。**不在这里做单位换算**：换过的数再想核回报表，
得先反算一次，而核对是这一页存在的理由。
"""

from __future__ import annotations

from typing import Any

# 从营业总收入里扣掉的各项。**顺序就是图上从上到下的顺序。**
#
# ## 为什么是三套，而不是一套
#
# 银行和保险的利润表上**没有营业成本**。照制造业那套画中国平安：
# 收入 10505 亿、四项费用一个都取不到，于是 8922 亿（85%）塞进一个叫
# 「税金与其他」的桶 —— 而那 8922 亿实际上是赔付支出、退保金、提取准备金。
# **那个标签是这张图上唯一一句彻底的假话**，比画不出来糟得多。
#
# ## 不按行业分类挑，按"哪一套取得到"挑
#
# 行业分类要么靠一张会过期的表，要么靠模型判断。而利润表自己就说了答案：
# 有营业成本的就是一般企业，有赔付支出的就是保险。**问数据，不问标签。**
#
# ⚠️ 银行的「营业收入」已经是**净额**（利息净收入 + 手续费净收入 + …），
# 所以支出侧**不许再减利息支出、手续费及佣金支出**——那是重复扣。
# 保险的营业收入是毛的（保费收入），赔付与手续费才在支出侧。
# 这一条错了图还是平的，只是每一根都偏 —— 所以下面用「营业支出」做校验。
_OUTFLOW_SETS = (
    ("一般企业", (
        ("营业成本", "营业成本"),
        ("销售费用", "销售费用"),
        ("管理费用", "管理费用"),
        ("研发费用", "研发费用"),
    )),
    ("保险", (
        ("赔付支出", "赔付支出"),
        ("退保金", "退保金"),
        ("提取保险责任准备金", "提取保险责任准备金"),
        ("手续费及佣金支出", "手续费及佣金支出"),
        ("业务及管理费", "业务及管理费"),
        ("营业税金及附加", "税金及附加"),
    )),
    ("银行", (
        ("业务及管理费用", "业务及管理费"),
        ("业务及管理费", "业务及管理费"),
        ("信用减值损失", "信用减值损失"),
        ("营业税金及附加", "税金及附加"),
    )),
)
_OUTFLOWS = _OUTFLOW_SETS[0][1]      # 兼容旧调用；新代码走 pick_outflows()

# 支出合计。银行保险的利润表上有这一行，**拿它校验我们拆出来的几项**：
# 拆出来的和它差太多，说明科目挑错了（多半是把已经计入净额的又减了一次）。
_TOTAL_COST = "营业支出"


def pick_outflows(items: dict[str, float]) -> tuple[str, tuple[tuple[str, str], ...]]:
    """按这家公司**真的有哪些科目**挑一套支出口径，挑不出来返回空。

    判据是"这一套里取得到的金额合计最大"，而不是"匹配到几个科目名"——
    一家保险公司也可能有个别通用科目，按个数挑会挑错。
    """
    best: tuple[float, str, tuple[tuple[str, str], ...]] = (0.0, "", ())
    for name, spec in _OUTFLOW_SETS:
        total = sum(items.get(key) or 0 for key, _ in spec)
        if total > best[0]:
            best = (total, name, spec)
    return best[1], best[2]

# 经营现金流那张图用到的科目。**那张图现在不画** —— 两张并成一张之后
# `cash_use()` 就没有调用方了，留着是因为「派息超过经营现金流多少」这个问题
# 仍然值得单独回答，只是还没想好摆在哪一页。要删的话连同它的四条测试一起删。
_CASH_DIVIDEND = "分配股利、利润或偿付利息所支付的现金"
_CASH_CAPEX = "购建固定资产、无形资产和其他长期资产所支付的现金"
_CASH_OPERATING = "经营活动产生的现金流量净额"

# 一根流量小到这个比例以下就不单画。**不是嫌它小，是画不出来**：
# 桑基图上一根 0.1% 的流是一条一像素的线，既看不见也点不着，
# 只会让图例多一行。它们会被并进「其他」，并在那一条上写明并了什么。
MIN_SHARE = 0.005

# 报告期的口径。**这四种画出来长得一模一样**，所以名字必须写在标题上：
# 一张「前三季度」的图和一张「全年」的图形状没有任何区别，
# 而把三季报当年报读，得出的每一个结论都是错的。
_PERIODS = {
    "12-31": ("年报", "全年"),
    "09-30": ("三季报", "前三季度累计"),
    "06-30": ("中报", "上半年累计"),
    "03-31": ("一季报", "第一季度"),
}


def period_label(report_date: str) -> str:
    """`2025-06-30` → `2025 中报`。认不出来的日期就原样返回，不猜。"""
    kind = _PERIODS.get(str(report_date)[5:], ("", ""))[0]
    return f"{str(report_date)[:4]} {kind}" if kind else str(report_date)


def period_span(report_date: str) -> str:
    """这一期覆盖多长时间：全年 / 前三季度累计 / 上半年累计 / 第一季度。

    **A 股的季报是累计口径**：三季报的「营业总收入」是 1—9 月的合计，不是第三季度
    单季。所以图上说的每一个数都要跟着这句话读。
    """
    return _PERIODS.get(str(report_date)[5:], ("", "这一期"))[1]


def paid_word(span: str) -> str:
    """分红那一根的措辞：年报说「当年实际支付」，季报说「上半年累计实际支付」。"""
    return "当年实际支付" if span == "全年" else f"{span}实际支付"


def _link(source: str, target: str, value: float, item: str = "",
          derived: bool = False, explain: str = "") -> dict[str, Any]:
    """一根流量。

    - `item` **只放报表科目原名**，别的什么都不放。它在提示框里是拿来核年报的：
      看到什么就该在年报里搜到什么。倒算出来的流量因此一律留空
      （`test_the_derived_bucket_is_marked_as_derived` 守着这条）。
    - `explain` 是这一根的口径说明。它跟 `item` 分开，是因为**这两句话的可信度
      完全不同**：一句能核，一句不能。

    ## 口径写在流量上，不写在图下面

    「分红与利息对应的是上一年度的利润」「税金与其他里含少数股东损益」这类话，
    原来堆在图下面成了三行小字 —— 使用者的原话是「别那么多废话」。
    而它们**只在你看那一根的时候才有用**：挪进提示框，图下面就只剩一句话。
    """
    return {"source": source, "target": target, "value": round(value, 2),
            "item": item, "derived": derived, "explain": explain}


def income_flow(revenue: float | None, net_profit: float | None,
                items: dict[str, float],
                segments: list[dict[str, Any]] | None = None,
                span: str = "全年") -> dict[str, Any] | None:
    """**一张图：钱从哪几门生意进来，一路出去，最后有多少到了股东手上。**

        茅台酒 1465.0 ─┐              ┌→ 归母净利润 ─┬→ 分红与利息
        其他系列酒 222.7├→ 营业总收入 ─┤              └→ 留在公司
        其他业务 32.8  ┘              └→ 营业成本 / 销售 / 管理 / 研发 / 税金与其他

    ## 三列，不是四列

    上一版在中间加了一层「毛利」，使用者一眼说别扭 —— 那条又粗又灰的带子把
    图切成两半，而它并不回答任何新问题（毛利率单独一个数就够了，不必占一列）。
    参考图（使用者给的）是三列：**来源 → 总收入 → 各项去处**，干净得多。

    ## 左边那几路是强制披露，不是编的

    年报分部附注里写着每个分部的收入金额。所以「茅台酒 / 其他系列酒」这种
    左半边不用推 —— 每一根都指回「分部附注 · X」。
    只在分部合计接近营业总收入时才画：口径只覆盖主营时画出来是缺一块的图，
    而缺口没有名字，读的人会以为这家公司有一半收入来路不明。

    ## 最后那一段的口径要说清楚

    「分红与利息」是现金流量表上**这一期实际支付**的现金，通常对应上一年度的利润；
    把它接在归母净利润后面，是为了看「赚的钱有多少到了股东手上」这个量级，
    **不是严格的会计勾稽**。分红超过当期净利时这一段不画 —— 那种情况下
    "从利润里分出去"这个说法本身就不成立了。

    ## 亏的那些期，主干要改名

    桑基图画不出负的流量。支出超过收入时，差额当成一路进来的钱画在左边，
    主干跟着改叫「这一期的钱」—— 因为它装的已经不是营业总收入那个数了，
    而节点标签上写的是吞吐量，写着「营业总收入 19.7 亿」而年报上是 11.7 亿，
    那是一个能被当场核错的数。**这一路叫什么取决于这一期是赚是亏**：
    亏的时候是「收入不够的部分」，赚的时候是「收入以外的进项」（投资收益之类）。

    ## span 是干什么的

    年报、中报、三季报、一季报都画得出来，而**四种画出来形状一模一样**。
    所以口径要跟着数一起走：说明的第一句就是它，分红那段的措辞也跟着它变。
    """
    if not revenue or revenue <= 0 or net_profit is None:
        return None

    links: list[dict[str, Any]] = []
    # 左半边没画出来时，**要说得出是为什么**。一片空白说不出自己是"没数据"
    # 还是"数据被判掉了"，而这两件事该点的按钮完全不一样。
    # 措辞要同时盖住"没同步过"和"同步了但停在别的期"——调用方把对不上期的分部
    # 当作没有传进来，这里说不出区别，所以两种都不说死。
    #
    # **一季报和三季报本来就没有分部附注**（不是强制披露项），所以对它们这句话
    # 不该是"去同步一下"，那会让人点一个永远不出结果的按钮。
    #
    # ⚠️ 另一半也踩过同一个坑：这句话原来写的是「点一次**同步财务数据**」，
    # 而分部附注根本不走那个按钮 —— 它是「主营构成」那块的**「同步主营构成」**，
    # 两个独立的动作、两个数据源。线上六家公司只有格力和茅台有分部，
    # 就是因为只有这两家被点过那个按钮；照着这句错话点一百次也不会有。
    # `left_fix` 告诉前端「这个缺口能不能当场补上」：
    #   syncable  —— 缺分部数据，点一下就能取（按钮画在图旁边，别叫人去别的页签找）
    #   ""        —— 补不了（季报本来就没有分部附注 / 分部口径对不上）
    left_fix = "" if span in ("第一季度", "前三季度累计") else "syncable"
    left_note = ("一季报三季报没有分部附注，左边那层画不出来 —— 想看就切年报或中报。"
                 if not left_fix else
                 "左边那层要年报分部附注，这一期还没取过。")

    # ── 左：钱是从哪几门生意进来的（年报分部附注）
    if segments:
        # **覆盖率要把补充行算进来。**
        #
        # 数据源给的分部里有一行「其他(补充)」，是它自己补的差额行，所以分部页
        # 把它标成 filler、画成灰色。第一版顺手把它从覆盖率里也剔掉了 ——
        # 格力 2025 因此是 1537.8/1711.2 = **0.8987**，比 0.9 这条线低 0.13 个
        # 百分点，整个左半边被判定"凑不齐"而不画。页面上是一片空白，
        # 而空白说不出自己是"没数据"还是"被判掉了"。
        #
        # 补充行本来就是收入的一部分，它只是没有分部的名字。**算覆盖率时它算数，
        # 画的时候并进「其他业务」** —— 那一根本来就是干这个的。
        real = [item for item in segments if (item.get("revenue") or 0) > 0]
        covered = sum(float(item["revenue"]) for item in real)
        if real and not 0.9 <= covered / revenue <= 1.02:
            # 取过了但对不上（分部合计跟营业总收入差太多），再点一次也是这个结果。
            left_fix = ""
            left_note = (f"分部附注合计是营业总收入的 **{covered / revenue:.0%}**，对不上，"
                         f"所以没画收入按业务拆开的那一层 —— 画出来会多一块或缺一块，"
                         f"而那一块没有名字。")
        if real and 0.9 <= covered / revenue <= 1.02:
            left_fix = ""
            left_note = ""
            merged: list[str] = []
            named = [item for item in real if not item.get("filler")]
            for item in sorted(named, key=lambda x: -float(x["revenue"])):
                value = float(item["revenue"])
                if value / revenue < MIN_SHARE:
                    merged.append(str(item["segment"]))   # 太细，单画是一条一像素的线
                    continue
                links.append(_link(str(item["segment"])[:20], "营业总收入", value,
                                   f"分部附注 · {item['segment']}"))
            gap = revenue - sum(l["value"] for l in links)
            if gap > 0:
                # 分部合计与营业总收入的差：补充行、其他业务收入、抵消项，
                # 加上占比太小没单画的那几个分部。
                # **有名字才画得出来，没有就叫「其他业务」并标成倒算。**
                explain = "分部附注的补充项与抵消项"
                if merged:
                    explain += f"，以及占比过小没单画的：{'、'.join(merged)}"
                links.append(_link("其他业务", "营业总收入", gap, derived=True, explain=explain))

    # ── 右：收入一路被扣掉，剩下净利
    #
    # **先算完再画。** 下面的次序是给人看的，不是算出来的次序 ——
    # 混在一起写过一版，结果「税金与其他」要在合计加完之后才算得出来，
    # 于是它被迫排在最后，而它本该在费用那一摞里。
    costs = 0.0
    drawn: list[tuple[str, float, str]] = []          # (显示名, 金额, 科目原名)
    tiny: list[tuple[str, float]] = []
    kind, spec = pick_outflows(items)
    seen: set[str] = set()
    for item, label in spec:
        value = items.get(item)
        if value is None or value <= 0 or label in seen:
            continue                                   # 两个别名同时存在时只画一次
        seen.add(label)
        costs += value
        drawn.append((label, value, item))
    kept = net_profit if net_profit > 0 else 0.0
    rest = revenue - costs - kept

    # **拆出来的支出跟报表上的「营业支出」对一下。**
    #
    # 银行的营业收入已经是净额，误把利息支出也减一遍的话，图还是平的，
    # 只是每一根都偏 —— 这种错自己不会暴露。差一成以上就当没拆开。
    reported = items.get(_TOTAL_COST)
    mismatched = bool(reported and costs and abs(costs - reported) / reported > 0.1)

    # **倒算出来的那一根不许是最粗的一根。**
    #
    # 第一版用的是「拆出来的支出要占收入四成」—— 那条误伤茅台：它毛利率 93%，
    # 四项成本本来就只占收入 18%，而那张图是对的。**四成是拍出来的数，
    # 而"最粗的一根是减出来的"是这张图自己就说得清的失败**：
    # 如果最大的一笔钱去了哪都说不出，那就没有拆开过。
    #
    # 平安：剩下 8922 亿，而画出来的每一根都比它小 → 判定没拆开。
    # 茅台：剩下 590.8 亿，归母净利润 823.2 亿比它大 → 拆开了，正常画。
    biggest = max([value for _, value, _ in drawn] + [kept], default=0.0)
    unexplained = rest > biggest
    if mismatched or unexplained:
        costs, drawn, kind = 0.0, [], ""
        rest = revenue - kept

    # ── 支出超过收入的那一期怎么画
    #
    # **桑基图画不出负的流量。** 寒武纪 2024 收入 11.7 亿、四项费用合计 19.7 亿：
    # 照原来的画法，营业总收入这个节点进 11.7 出 19.7 —— 图还是那个形状，
    # 只是有一根凭空变粗了，**而人眼看不出来**。这在只画最近一期年报时藏着，
    # 一开放选期就撞上（寒武纪九期里八期是亏的）。
    #
    # 差额当成**一路进来的钱**画在左边，跟 `cash_use()` 里对付派息缺口是同一招：
    # 藏进别的流里就等于没说，而说出来它本身就是这一期最要紧的一件事。
    # 主干也要改名：这时候它装的已经不是「营业总收入」那个数了。
    trunk = "营业总收入"
    shortfall = -rest if rest < 0 else 0.0
    # **这一路进来的钱叫什么，取决于这一期是赚是亏。**
    #
    # 亏的时候它主要是亏损；赚的时候（寒武纪 2025：收入 65.0 亿，四项费用加净利
    # 65.9 亿）它是投资收益、其他收益、利息收入这些营业收入以外的进项。
    # 第一版两种都写成「收入不够的部分 · 差额来自这一期的亏损」——
    # 对一家当年赚了 20.6 亿的公司说它在亏，**这是图上唯一一句会骗人的话**。
    gap_name = "收入不够的部分" if net_profit <= 0 else "收入以外的进项"
    if shortfall > 0:
        trunk = "这一期的钱"
        links.append(_link("营业总收入", trunk, revenue, "营业总收入"))
        links.append(_link(gap_name, trunk, shortfall, derived=True,
                           explain=("差额来自这一期的亏损，以及利息、减值这些图上没单画的项"
                                    if net_profit <= 0 else
                                    "投资收益、其他收益、利息收入等营业收入以外的进项，图上没单画")))
        rest = 0.0

    scale = revenue + shortfall          # 图上一根流量的"满格"是多少
    # **归母净利润这一根排在最前面。**
    #
    # 它后面还接着分红那两根，而最后一列只有那两个节点 —— 桑基图把每一列都
    # 从顶上开始摆，所以它们必然在最上面。净利润排在费用后面的话，那条绿带子
    # 就要从图的底部一路兜到右上角，横穿整张图。使用者截图圈的就是这个交叉，
    # 原话是「要不放在最下面，要不对面的放在下面」——
    # 让它和它的下游都待在最上面一层，是这两个选项里画出来更干净的那个。
    if kept > 0:
        links.append(_link(trunk, "归母净利润", kept, "归属于母公司所有者的净利润"))
    for label, value, item in drawn:
        if value / scale < MIN_SHARE:
            tiny.append((label, value))     # 太细，单画是一条一像素的线
            continue
        links.append(_link(trunk, label, value, item))
    # **被并掉的小额要合成一根，不能凭空消失。**
    # 第一版是"跳过不画、但算进已知"，结果茅台的研发费用 1.9 亿从图上整个消失，
    # 流量合计比收入少 1.9 亿。桑基图不平是最难发现的一种错：形状没变，只是有一根细了。
    if tiny:
        links.append(_link(trunk, "其他费用", sum(v for _, v in tiny),
                           "、".join(name for name, _ in tiny)))
    if rest > 0:
        # 名字跟着"拆开了没有"走。**一个塞了 85% 收入的桶不能叫「税金与其他」** ——
        # 那是这张图上唯一一句彻底的假话。
        residual = "税金与其他" if drawn else "没拆开的支出"
        links.append(_link(trunk, residual, rest, derived=True,
                           explain=("主要是税金及附加与所得税，还含少数股东损益"
                                    "（图上的净利润是归母口径）" if drawn else
                                    "这家公司的利润表不是制造业那一套，"
                                    "图上还拆不开它的支出")))
    if not links:
        return None

    # ── 最后：净利里有多少真的分给了你
    dividend = items.get(_CASH_DIVIDEND) or 0.0
    # **小到画不出来的分红不画。**
    #
    # 线上第一张真图（寒武纪）分红只有 0.04 亿、净利 20.6 亿 —— 画出来是一根
    # 「分红与利息 0.0 亿」的零宽线，标签还跟旁边两根叠在一起。
    # 而"几乎不分红"这件事本身是有意义的，所以它不消失，只是改成用一句话说。
    paid_out = 0 < dividend < net_profit and dividend / net_profit >= MIN_SHARE
    if paid_out:
        links.append(_link("归母净利润", "分红与利息", dividend, _CASH_DIVIDEND,
                           explain=f"{paid_word(span)}的现金，通常对应上一年度的利润 ——"
                                   f"接在净利润后面是看量级，不是严格的会计勾稽"))
        links.append(_link("归母净利润", "留在公司", net_profit - dividend, derived=True,
                           explain="归母净利润减去当期实际支付的分红与利息"))

    # ── 图下面那段：**只留这一期特有的提醒。**
    #
    # 原来每一张图下面都挂着三行小字：倒算是什么、分红什么口径、这一页不下判断。
    # 那些话对每一张图都成立，所以每一张图上都是废话 —— 使用者的原话就是这个。
    # 常年成立的话进 boundary（一句），只在某一根上成立的话进那一根的提示框，
    # 这里剩下的只有「这一期跟别的期不一样在哪」。
    notes: list[str] = []
    # **口径先说。** 一张「前三季度」的图和一张「全年」的图形状没有任何区别，
    # 而把三季报当年报读，后面每一个结论都是错的。所以这句话排在最前面。
    if span != "全年":
        notes.append(f"**这是{span}的数**，不是全年 —— A 股季报是累计口径。")
    if left_note:
        notes.append(left_note)
    # **拆不开的时候必须说。** 中国平安 8922 亿（收入的 85%）顶着「税金与其他」
    # 这个名字，而它实际上是赔付支出与退保金 —— 那是这张图上唯一一句彻底的假话。
    if not drawn and rest > 0:
        notes.append("**这家公司的支出还拆不开**：它的利润表不是制造业那一套"
                     "（银行、保险的科目完全不同）。中间那一大块是减出来的，**不是税** ——"
                     "点一次「同步财务数据」会把新加的科目取回来。")
    elif drawn and kind and kind != "一般企业":
        notes.append(f"支出按**{kind}**的科目拆 —— 这类公司的利润表上没有营业成本。")
    if shortfall > 0 and net_profit <= 0:
        notes.append(f"**支出比收入多 {shortfall / 1e8:.1f} 亿**，多的那一路从左边进来"
                     f"（桑基图画不出负的流量）；归母净利润 {net_profit / 1e8:.1f} 亿。")
    elif shortfall > 0:
        notes.append(f"**有 {shortfall / 1e8:.1f} 亿不是卖东西赚来的**"
                     f"（投资收益、其他收益、利息收入），画成左边那一路「{gap_name}」。")
    elif net_profit <= 0:
        notes.append(f"**归母净利润 {net_profit / 1e8:.1f} 亿**，是亏的，所以没有净利润那一路；"
                     f"亏在减值、财务费用这些图上没单画的科目里，含在「税金与其他」中。")
    if rest <= 0 and shortfall <= 0:
        notes.append("各项加起来正好等于营业总收入，没有单独的「税金与其他」——"
                     "**不代表没交税**，它含在各项里。")
    paid = paid_word(span)
    if paid_out:
        pass                      # 口径写在那一根的提示框里了，不占图下面的地方
    elif dividend >= net_profit > 0:
        notes.append(f"{paid}的分红与利息 {dividend / 1e8:.1f} 亿，"
                     f"**超过了这一期的归母净利润**，所以没画成「从利润里分出去」。")
    elif dividend > 0 and net_profit > 0:
        notes.append(f"{paid}的分红与利息只有 {dividend / 1e8:.2f} 亿，细到画不出来 ——"
                     f"**这一期赚的钱基本都留在公司里**。")
    elif net_profit > 0:
        notes.append("现金流量表里没有分红那一项，所以这张图说不出赚的钱有多少分给了股东。")
    return {"total": round(revenue + shortfall, 2), "links": links,
            "note": " ".join(notes), "left_fix": left_fix}


def cash_use(items: dict[str, float]) -> dict[str, Any] | None:
    """赚到的钱去了哪：经营现金流 → 分红与利息 / 资本开支 / 留下的。

    **这张图的价值在于它可能不平。** 派息加资本开支超过当年经营现金流是常事
    （2025 年茅台就超了 88.5 亿），那意味着动用了账上的存量或者借了钱。
    表格里这要翻两页再减一次；这里是一根反向的流。

    所以缺口不做成"负的留存"，而是当成**一路进来的钱**画在左边 ——
    负流量在桑基图上画不出来，而把它藏进别的流里就等于没说。
    """
    operating = items.get(_CASH_OPERATING)
    if operating is None or operating <= 0:
        return None

    dividend = items.get(_CASH_DIVIDEND) or 0.0
    capex = items.get(_CASH_CAPEX) or 0.0
    if dividend <= 0 and capex <= 0:
        return None

    spent = dividend + capex
    shortfall = max(0.0, spent - operating)
    inflow = operating + shortfall

    links: list[dict[str, Any]] = [
        _link("经营活动现金流净额", "这一年的钱", operating, _CASH_OPERATING),
    ]
    if shortfall > 0:
        links.append(_link("动用账上存量或融资", "这一年的钱", shortfall, "", derived=True))
    if dividend > 0:
        links.append(_link("这一年的钱", "分红与利息", dividend, _CASH_DIVIDEND))
    if capex > 0:
        links.append(_link("这一年的钱", "资本开支", capex, _CASH_CAPEX))
    left = inflow - spent
    if left > 0:
        links.append(_link("这一年的钱", "留在账上", left, "", derived=True))

    return {
        "total": round(inflow, 2),
        "links": links,
        "shortfall": round(shortfall, 2),
        "note": (
            f"这一年派息与资本开支合计 {spent / 1e8:.1f} 亿，"
            f"**超过经营现金流 {shortfall / 1e8:.1f} 亿** —— 差额只能来自账上的存量或者融资。"
            if shortfall > 0 else
            "「留在账上」是经营现金流减掉派息与资本开支之后**倒算**出来的，"
            "它不是报表上的某一行（真实的现金变动还受投资与筹资活动影响）。"),
    }


def build(period: dict[str, Any], items: dict[str, float],
          segments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """把一期报表拼成那一张图。凑不齐就返回 available=False，**不用零填**。

    年报、中报、三季报、一季报都画得出来 —— 利润表和现金流量表的科目每一期都有。
    **口径靠 `period_span` 传下去**，因为四种期画出来长得一模一样。
    """
    report_date = str(period.get("report_date") or "")
    span = period_span(report_date)
    income = income_flow(period.get("revenue"), period.get("net_profit"), items, segments, span)
    return {
        "period_label": period_label(report_date),
        "span": span,
        "report_date": period.get("report_date"),
        "income": income,
        "available": bool(income),
        # **一句话。** 常年成立的话每张图上都成立，所以每张图上都是废话；
        # 剩下这一句留着，是因为它决定了别的数字能不能被相信。
        "boundary": ("停在任意一根流量上能看到它的报表科目原名与口径；"
                     "**画成虚线的那几根是减出来的**，报表上没有这一行。"),
    }
