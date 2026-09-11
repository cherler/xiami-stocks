/**
 * 首屏那一件事。
 *
 * ## 这个产品跟同花顺的分工
 *
 * 行情、指标、K 线、新闻——同花顺都有，而且比这里做得好。**这里不做那些。**
 * 这是补充，不是替代。
 *
 * 那补充什么？只有一件事是所有炒股软件都不做的：
 *
 *     三个月前你写下「如果集中度还高于 85%，我就错了」。
 *     今天年报出来了，88.66%。
 *
 * 没有任何一个软件会拿你自己说过的话来撞你。这就是这一屏该只放的东西。
 *
 * ## 三种状态，一次只出一种
 *
 *     有命中     那一条占满整屏：你写的条件、撞上它的事实、一个动作
 *     没命中     那就主动找一条——反方 Agent，读你自己的库，引不出数据的当场丢掉
 *     没判断     先写一条。没有判断就没有东西可以被推翻，这个产品对你还没开始
 *
 * **不叠加。** 三种都摆出来就又变回一个面板列表了，而这一屏的全部意义
 * 在于它只有一件事。
 *
 * ## 为什么合并了原来的两块
 *
 * 反证命中原来是页顶一条细横幅（CounterHitBanner），反方入口是页中一块面板
 * （ChallengeEntry），中间还隔着待办卡、简报、综合榜。
 * 两块加起来正好是这个产品的全部卖点，却被摊在一列十二块面板里，
 * **谁都不显眼**。合成一块，放在第一屏，其余全部下沉。
 */

import { useEffect, useState } from "react";

import { getAccess, getOpenCounterHits, type OpenCounterHit } from "../api";
import type { DashboardSummary } from "../types";

/** 判断的第一句。库里那条是用「；」串起来的长句，后面挂着分位和公告日期。 */
function headline(claim: string): string {
  return String(claim || "").split("；")[0] || claim;
}

export function Headline({ theses, companyCount, onOpenCompany, onWrite }: {
  theses: DashboardSummary["theses"];
  companyCount: number;
  /** intent 见 App.tsx 的 openCompany：**「让它驳这条」要把人送到那一块，不是送到那一页。** */
  onOpenCompany: (id: number, tab?: string, intent?: string) => void;
  onWrite: () => void;
}) {
  const [hits, setHits] = useState<OpenCounterHit[] | null>(null);
  // 游客：库里一行都看不到（RLS 给的是空域），所以 companyCount 必然是 0，
  // 会落进「第一次进入」那一档——而那一档的按钮点下去是 401。
  // 先问一句自己是不是游客，是的话给登录，不给建档。
  const [guest, setGuest] = useState(false);
  useEffect(() => {
    let live = true;
    getAccess().then((view) => { if (live) setGuest(view.is_guest); }).catch(() => undefined);
    return () => { live = false; };
  }, []);

  useEffect(() => {
    let live = true;
    getOpenCounterHits()
      .then((rows) => { if (live) setHits(rows); })
      .catch(() => { if (live) setHits([]); });
    return () => { live = false; };
  }, []);

  // 还没取回来就先不占位置：先渲染一个空壳再跳成命中，比晚 200ms 更晃眼。
  if (hits === null) return null;

  // ── 状态一：你写下的认错条件被踩到了 ──────────────────────
  if (hits.length > 0) {
    const first = hits[0];
    return (
      <section className="headline headline--hit" aria-label="认错条件被踩到">
        <div className="headline-tag">
          <i aria-hidden="true" />有事实撞到了你写下的判断
          {hits.length > 1 && <em>还有 {hits.length - 1} 条</em>}
        </div>

        {/* 原文照抄。**改写过的条件没法拿去跟自己当初写的对。** */}
        <p className="lead"><em>「{first.clause}」</em></p>
        <p className="headline-who">你写在 {first.company_name} 上</p>

        <div className="zhu-note">
          <b>{first.event_date}　{first.event_title}</b>
          {first.reason && <span>{first.reason}</span>}
        </div>

        <div className="headline-acts">
          <button className="page-action" onClick={() => onOpenCompany(first.company_id, "research")}>
            去改这条判断 →
          </button>
        </div>
      </section>
    );
  }

  // ── 游客：能看市场，写不了东西 ────────────────────────────
  if (guest) {
    return (
      <section className="headline headline--first" aria-label="登录后开始使用">
        <div className="headline-tag headline-tag--calm">先看看，不用注册</div>
        <p className="lead">记下你<em>为什么买</em>，在事实变化时提醒你</p>
        <p className="headline-why">
          行情、财报、公告原文不用登录也能看。
          建立公司档案、写下判断、让它反驳你——这些要登录后才有地方存。
        </p>
        <div className="headline-acts">
          <a className="page-action" href="/?login=1">登录虾米伙伴 →</a>
        </div>
      </section>
    );
  }

  // ── 状态零：第一次进入。先解释产品，再要求用户写判断。 ──────
  if (companyCount === 0) {
    return (
      <section className="headline headline--first" aria-label="开始使用虾米看股">
        <div className="headline-tag headline-tag--calm">从一家公司开始</div>
        <p className="lead">把你的投资理由写下来，<em>等事实来验证</em></p>
        <p className="headline-why">虾米看股不替你荐股，而是帮你记住：当初为什么关注它，后来哪些事实支持或推翻了这个判断。</p>
        <ol className="headline-steps">
          <li><b>建立公司档案</b><span>用股票代码确认真实公司</span></li>
          <li><b>写下一条判断</b><span>为什么值得研究，什么情况下你会认错</span></li>
          <li><b>回来检查事实</b><span>公告、财报和经营变化会进入复核</span></li>
        </ol>
        <div className="headline-acts">
          <button className="page-action" onClick={onWrite}>建立第一家公司 →</button>
        </div>
      </section>
    );
  }

  // ── 状态三：已有公司但还没有判断。把数字翻译成下一步。 ──────
  if (!theses || theses.length === 0) {
    return (
      <section className="headline headline--blank" aria-label="开始写下投资判断">
        <div className="headline-tag headline-tag--calm">公司已经准备好了</div>
        <p className="lead">为第一家公司写下一句<em>愿意被事实推翻</em>的话</p>
        <p className="headline-why">你已经关注 {companyCount} 家公司，但还没有一条可以被验证的投资判断。先写“为什么”，再写“什么情况下我认错”。</p>
        <div className="headline-acts">
          <button className="page-action" onClick={onWrite}>写下第一条判断 →</button>
        </div>
      </section>
    );
  }

  // ── 状态二：今天没有命中。那就主动找一条 ──────────────────
  const target = theses[0];
  return (
    <section className="headline headline--quiet" aria-label="今天要检查的投资判断">
      <div className="headline-quiet-head">
        <div>
          <div className="headline-tag headline-tag--calm">今天没有发现事实推翻你的判断</div>
          <p className="headline-why">先看这一条判断，检查它最可能错在哪里。</p>
        </div>
        <button className="page-action"
          onClick={() => onOpenCompany(target.company_id, "research", "advocate")}>
          检查这条判断 →
        </button>
      </div>
      <div className="headline-thesis-focus">
        <span>{target.company_name} · 你写下的判断</span>
        <strong title={headline(target.claim)}>{headline(target.claim)}</strong>
      </div>
    </section>
  );
}
