"""申万行业分类：把「白酒Ⅱ」这种口径同步进来。

## 为什么非要它不可

行业特有指标（合同负债、拨贷比、已售未结转）全靠行业分类才能选对那几条。
而 `market_universe.sw_level1 / sw_level2` **这两列建了之后从来没有写入方**——
实测全库 5538 行，有值的 0 行。

后果是这个功能对 12 家档案公司**一条专属指标都没算出来过**：
分类三级回退（申万二级 → 申万一级 → 档案行业）实际只剩最后一级，
而档案里存的是证监会门类「酒、饮料和精制茶制造业」，
跟别名表里的「白酒Ⅱ」对不上，于是每家都落到"这个行业还没有专属指标"。

**别名表本来就是照申万写的**，把数据同步进来就行，不需要改匹配逻辑。

## 为什么不从东财取

`stock_individual_info_em` 一句话就能拿到行业，但东财的 push2 在这个部署里
是通的不了的（ProxyError）。申万宏源自己那两个接口不走东财，实测可用。

## 131 次请求，两分半

二级行业 131 个，每个取一次成分股，实测每次约 1.1 秒。这是个**低频作业**——
行业成分一年调整一两次，跟着底座刷新一起跑就够，没必要单独排期。
失败不该拖垮整个底座刷新，所以调用方要把它包起来。
"""

from __future__ import annotations

import time
from typing import Any

from .base import QuoteProviderError

# 每次请求之间歇一下。申万那边没有公开的频率限制，但 131 次连打不礼貌，
# 而这个作业本来就不赶时间。
_PAUSE = 0.1


def fetch_sw_industry_map(pause: float = _PAUSE) -> dict[str, Any]:
    """{symbol: {"sw_level1": ..., "sw_level2": ...}}，外加一份同步小结。

    **取不到的行业跳过并记下来**，不要因为一个行业挂了就整批失败——
    129/131 个行业的分类是有用的，全丢掉才是浪费。
    """
    import akshare as ak

    try:
        second = ak.sw_index_second_info()
    except Exception as exc:  # noqa: BLE001
        raise QuoteProviderError(f"申万二级行业清单取不到：{exc}") from exc

    mapping: dict[str, dict[str, str]] = {}
    failed: list[str] = []
    for row in second.to_dict("records"):
        name = str(row.get("行业名称") or "").strip()
        parent = str(row.get("上级行业") or "").strip()
        code = str(row.get("行业代码") or "").split(".")[0].strip()
        if not name or not code:
            continue
        try:
            members = ak.index_component_sw(symbol=code)
        except Exception:  # noqa: BLE001
            failed.append(name)
            continue
        for member in members.to_dict("records"):
            symbol = str(member.get("证券代码") or "").strip()
            if symbol:
                mapping[symbol] = {"sw_level1": parent, "sw_level2": name}
        if pause:
            time.sleep(pause)

    return {"mapping": mapping, "industries": len(second), "failed": failed,
            "source": "申万宏源行业分类"}
