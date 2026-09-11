/**
 * 反证命中横幅：你自己写下的那件事，真的发生了。
 *
 * ## 为什么值得占一条常驻横幅
 *
 * 查库统计：12 家建档公司，**做过复核 0 家**。
 * 而这个产品叫「长期研究工作台」，侧栏一整组写着「写下来、跟踪、复盘」——
 * 复盘那一环一次都没发生过。
 *
 * 「到了复核日」这种日历提醒不够，因为它是你跟自己约的，改一改就过去了。
 * 而**反证命中不一样**：那是你在清醒的时候写下「如果 X 发生我就错了」，
 * 然后 X 真的发生了。这是唯一一种人不会想绕开的提醒。
 *
 * ## 为什么是横幅而不是弹窗
 *
 * 弹窗会被条件反射关掉，关掉之后就再也不出现了。
 * 横幅不阻断你做别的事，但**在你确认之前它不消失**——
 * 换页、刷新、明天再来，它都还在。
 * 这条提醒的价值全在"绕不开"，做成可以随手关掉的就等于没做。
 *
 * ## 「确认」这个动作原来没接上
 *
 * 上面那句「在你确认之前它不消失」写了，**但确认的按钮一直没有**：
 * 接口 `POST /counter-hits/{id}/acknowledge` 从第一天就在，而前端一次都没调过
 * （2026-08-15 普查：178 条路由里，前端源码一处都搜不到的有 12 条，这是其中之一）。
 * 而 `acknowledged` 只有那一个接口能置 1 —— 也就是说命中一旦出现就**永远消不掉**，
 * 侧栏那个徽章也永远清不了。
 *
 * 这恰恰是这个徽章当初要避开的东西：schemas.py 里写着"未读公告长期停在 646——
 * 一个永远清不完的红点第三天就成了背景色"。为了避开它而做的徽章，
 * 自己成了一个永远清不完的红点。
 *
 * 按钮的措辞是「我处理过了」而不是「知道了」：这一步该记的是"你动过了"，
 * 不是"你看见了"。看见不改变任何事。
 */

import { useEffect, useState } from "react";

import { acknowledgeCounterHit, getOpenCounterHits, type OpenCounterHit } from "../api";

export function CounterHitBanner({ onOpenCompany }: { onOpenCompany: (id: number) => void }) {
  const [hits, setHits] = useState<OpenCounterHit[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function settle(hitId: number) {
    setBusy(true); setError("");
    try {
      await acknowledgeCounterHit(hitId);
      // 从本地列表里摘掉这一条：还有别的命中就接着显示下一条，
      // 没有了横幅自己消失 —— 不用整页重载。
      setHits((rows) => rows.filter((row) => row.id !== hitId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally { setBusy(false); }
  }

  useEffect(() => {
    let live = true;
    getOpenCounterHits().then((rows) => { if (live) setHits(rows); }).catch(() => undefined);
    return () => { live = false; };
  }, []);

  if (hits.length === 0) return null;
  const first = hits[0];

  return (
    <aside className="counter-banner" role="status">
      <div className="counter-banner-mark" aria-hidden="true" />
      <div className="counter-banner-body">
        <strong>
          你写下的认错条件被踩到了
          {hits.length > 1 && <em>　还有另外 {hits.length - 1} 条</em>}
        </strong>
        {/* 原文照抄：改写过的条件没法拿去跟自己当初写的对。 */}
        <p className="counter-banner-clause">「{first.clause}」</p>
        <p className="counter-banner-why">
          <b>{first.company_name}</b>　{first.event_date}　{first.event_title}
          {first.reason && <>　——　{first.reason}</>}
        </p>
      </div>
      <div className="counter-banner-actions">
        <button className="page-action" onClick={() => onOpenCompany(first.company_id)}>
          去看这条判断
        </button>
        {/* **先给"去看"，再给"处理过了"。** 顺序反过来的话，
            随手点掉比读一遍更省事，而这条提醒的全部价值就在于你得读它。 */}
        <button className="text-button" disabled={busy}
          onClick={() => void settle(first.id)}>
          {busy ? "正在记下…" : "我处理过了"}
        </button>
      </div>
      {error && <p className="form-error">{error}</p>}
    </aside>
  );
}
