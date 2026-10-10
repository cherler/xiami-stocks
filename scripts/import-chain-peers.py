#!/usr/bin/env python3
"""把 earth-atlas 导出的「代码 → 产业链环节」灌进本仓，给涨跌归因当对照组。

    python scripts/import-chain-peers.py <chain-peers.json>
    python scripts/import-chain-peers.py ../earth-atlas/site/exports/stocklab/chain-peers.json

那份 JSON 由 earth-atlas 的 `scripts/export-peers-for-stocklab.mjs` 生成。

## 为什么走文件，不直接读对面的目录

两个仓各有各的真源。本仓写死一条 `../earth-atlas/ontology/...` 的路径之后：
对方改一次目录结构这边就静静地取不到数（而页面上只会显示「同环节没有别的公司」，
看不出是坏了还是真的没有）；部署时对方那个仓也未必在机器上。
**一份导出文件是两边唯一的接缝**，路径由调用方给。

## 整表替换，不做增量

环节归属会变（某家公司改了主业、某个环节被拆开）。增量更新留不下"删除"这个动作，
灌几次之后表里会堆着早就不成立的归属，而它们跟新的长得一模一样。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from stock_decision.database import connection, initialize_database, now_iso  # noqa: E402

REQUIRED = ("symbol", "chain", "segment")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = Path(argv[1]).expanduser()
    if not path.exists():
        print(f"找不到 {path}\n先在 earth-atlas 里跑一次："
              f"node scripts/export-peers-for-stocklab.mjs")
        return 1

    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        print("这份文件里没有 rows —— 是不是导出那一步失败了？")
        return 1

    # **必填字段缺了就整份拒收。** 灌进去一半再报错，比不灌更难收拾：
    # 表里会混着新旧两批，而看不出哪些是新的。
    bad = [i for i, row in enumerate(rows)
           if not all(str(row.get(key) or "").strip() for key in REQUIRED)]
    if bad:
        print(f"第 {bad[:5]} 条缺 {REQUIRED} 里的必填字段，整份拒收。")
        return 1

    initialize_database()
    stamp = now_iso()
    with connection() as conn:
        before = conn.execute("SELECT COUNT(*) AS n FROM chain_segment_members").fetchone()["n"]
        conn.execute("DELETE FROM chain_segment_members")
        for row in rows:
            conn.execute(
                """INSERT INTO chain_segment_members
                   (symbol, chain, segment, name, chain_label, stage, segment_label, what,
                    source_url, source_title, source_quote, accessed, imported_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(row["symbol"]).strip()[-6:], row["chain"], row["segment"],
                 row.get("name", ""), row.get("chain_label", ""), row.get("stage", ""),
                 row.get("segment_label", ""), row.get("what", ""),
                 row.get("source_url", ""), row.get("source_title", ""),
                 row.get("source_quote", ""), row.get("accessed", ""), stamp))
        after = conn.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT symbol) AS s,"
            " COUNT(DISTINCT chain || ':' || segment) AS g FROM chain_segment_members").fetchone()
        matched = conn.execute(
            """SELECT COUNT(DISTINCT m.symbol) AS n FROM chain_segment_members m
               JOIN market_universe u ON u.symbol = m.symbol""").fetchone()["n"]

    print(f"导入完成（整表替换：{before} → {after['n']} 条）")
    print(f"  {after['s']} 只 A 股，{after['g']} 个环节，导出于 {payload.get('generated_at', '未标日期')}")
    # **对不上全市场底座的那些要报出来。** 退市、改名、代码写错都会落在这里，
    # 而它们在页面上的表现只是"这家同行没有行情"，看不出是数据问题。
    print(f"  其中 {matched} 只能在全市场底座里找到行情"
          + (f"，{after['s'] - matched} 只对不上（退市/代码有误/底座还没同步）"
             if matched < after["s"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
