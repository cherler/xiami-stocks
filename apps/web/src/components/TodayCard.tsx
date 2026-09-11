/**
 * 一页纸：不滚动就能回答这一页标题问的那句话——「今天，哪些判断需要重新检查？」
 *
 * ## 为什么原来不直观
 *
 * 信息其实都在，问题是它们**平铺成了八块面板**：摘要条、看板、逻辑账本、
 * 事件、行情、集中度、关注列表……每块都对，加起来要滚三屏，而且每个数字
 * 都长得一样重要。人打开一个页面时想知道的是「先干哪件」，不是「一共有多少种事」。
 *
 * ## 待办为什么不画成条形图
 *
 * 直觉是按数量画条：129 条公告一根长条、9 只待补全一根短条。**但那样正好把
 * 信号画反了**——紧急程度跟数量几乎是反相关的：反证命中 0 条是最要紧的一档
 * （它一旦不是 0 就得立刻看），129 条待核公告反而是可以慢慢清的日常。
 * 按数量画长度，最不该被忽略的那一档会是最短的一根，甚至没有。
 *
 * 所以这里不画条：**顺序本身就是编码**。从上到下就是该做的先后，
 * 数字只是数字。这是"有时候答案不是一张图"的情况。
 *
 * 次序取自后端的 _ACTION_WEIGHT（反证 > 复核 > 公告 > 补全），
 * 不在前端另定一套——两处各排一次，迟早会不一致，而不一致的那次没人会发现。
 *
 * ## 颜色
 *
 * 四档用的是**状态色**（critical / serious / warning / 中性），不是分类色。
 * 状态色是保留的，不参与系列配色。每一行都带文字标签和数字，
 * 颜色只是加速定位——色觉障碍、打印、强制配色下这一格照样读得懂。
 *
 * 计数为 0 的档**不隐藏**，压成灰色留在原地：「反证 0 条」是一条有意义的
 * 信息（今天没有东西推翻你的判断），隐藏掉就变成了"没这回事"。
 */

import type { DashboardSummary } from "../types";

/** `!== null` 拦不住 `undefined`。isFinite 同时挡住 null、undefined 和 NaN。 */
function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export type TodoBucket = {
  key: string;
  label: string;
  hint: string;
  count: number;
  tone: "critical" | "serious" | "warning" | "plain";
  go: () => void;
};

/** 判断状态的三段。用堆叠比例条：三段合起来是一个整体，看的是占比不是绝对值。 */
export function ThesisBar({ dashboard, onGo }: { dashboard: DashboardSummary; onGo: () => void }) {
  const total = dashboard.total_theses;
  const due = dashboard.theses_to_review;
  const intact = dashboard.intact_theses;
  // 刚写下、还没到复核期的那些两边都不算，所以第三段是减出来的而不是取字段
  const watching = Math.max(0, total - due - intact);
  const segments = [
    { key: "intact", label: "成立", value: intact, className: "tstate--intact" },
    { key: "watching", label: "观察中", value: watching, className: "tstate--watching" },
    { key: "due", label: "待复核", value: due, className: "tstate--due" },
  ].filter((s) => s.value > 0);

  return (
    <button type="button" className="today-block today-block--theses thesis-status-card" onClick={onGo}>
      <span className="today-block-label">投资逻辑</span>
      {total === 0
        ? <p className="today-empty">还没有写下任何判断。没有判断就没有东西可以被推翻，也就无从复核。</p>
        : <>
            <strong className="today-figure">{total}<em>条</em></strong>
            {/* **只有一种状态时不画条。** 四条逻辑全在观察中，条就是满格的——
                一根恒为 100% 的进度条不携带任何信息，而它占的位置和
                真有分布时一样大。没有分布就直接说是哪一种。 */}
            {segments.length < 2 ? (
              // **只有一种状态时不画条。** 四条逻辑全在观察中，条就是满格的——
              // 一根恒为 100% 的进度条不携带任何信息，而它占的位置跟真有分布时一样大。
              // 没有分布就直接说是哪一种，图例也跟着一起省掉。
              <span className="today-mix-note">{total} 条都是「{segments[0]?.label ?? "未标状态"}」</span>
            ) : (
              <>
                <div className="tstate-bar" role="img"
                     aria-label={`共 ${total} 条：成立 ${intact}、观察中 ${watching}、待复核 ${due}`}>
                  {/* 段与段之间留 2px 缝：贴在一起时相邻两段会读成一整块 */}
                  {segments.map((s) => (
                    <i key={s.key} className={`tstate ${s.className}`}
                       style={{ flexGrow: s.value }} title={`${s.label} ${s.value} 条`} />
                  ))}
                </div>
                <div className="tstate-legend">
                  {segments.map((s) => (
                    <span key={s.key}><i className={`tstate ${s.className}`} />{s.label} {s.value}</span>
                  ))}
                </div>
              </>
            )}
          </>}
    </button>
  );
}

/** 持仓。金额只有站主看得到，非站主那边后端返回的就是比例口径。 */
function HoldingBlock({ dashboard, onGo }: { dashboard: DashboardSummary; onGo: () => void }) {
  const byHolding = dashboard.exposure_basis === "持仓市值";
  const exposure = dashboard.portfolio_exposure ?? [];
  const invested = exposure.reduce((sum, item) => sum + (num(item.weight) ?? 0), 0);
  const gain = num(dashboard.holding_unrealized_percent);

  return (
    <button type="button" className="today-block" onClick={onGo}>
      <span className="today-block-label">{byHolding ? "持仓" : "研究池分布"}</span>
      {exposure.length === 0
        ? <p className="today-empty">还没有持仓记录。</p>
        : <>
            <strong className="today-figure">
              {byHolding && num(dashboard.holding_market_value) !== null
                ? <>¥{Math.round(num(dashboard.holding_market_value)!).toLocaleString("zh-CN")}</>
                : <>{Math.round(invested)}<em>%</em></>}
            </strong>
            {gain !== null && byHolding && (
              // 涨红跌绿：跟站内 .quote-up / .quote-down 一致，A 股惯例
              <em className={`today-gain ${gain < 0 ? "quote-down" : "quote-up"}`}>
                浮动盈亏 {gain > 0 ? "+" : ""}{gain.toFixed(2)}%
              </em>
            )}
            {/* 集中度：每一格一个标的，剩下的是没投出去的部分。
                一眼看出是压在一只上还是摊开的——这是集中度唯一要回答的问题。 */}
            <div className="today-mix" role="img"
                 aria-label={exposure.map((e) => `${e.name} ${e.weight}%`).join("，")}>
              {exposure.map((item) => (
                <i key={item.name} style={{ flexGrow: num(item.weight) ?? 0 }}
                   title={`${item.name} ${item.weight}%`} />
              ))}
              {invested < 100 && <i className="today-mix-rest" style={{ flexGrow: 100 - invested }}
                                    title={`其余 ${(100 - invested).toFixed(1)}%`} />}
            </div>
            <span className="today-mix-note">
              最大一只 {Math.max(...exposure.map((e) => num(e.weight) ?? 0)).toFixed(1)}%
              {exposure.length > 1 ? ` · 共 ${exposure.length} 只` : " · 只有这一只"}
            </span>
          </>}
    </button>
  );
}

export function TodayCard({ dashboard, buckets, onGoHoldings, onGoData }: {
  dashboard: DashboardSummary;
  buckets: TodoBucket[];
  onGoHoldings: () => void;
  onGoData: () => void;
}) {
  const pressing = buckets.filter((b) => b.count > 0);
  const clear = buckets.filter((b) => b.count === 0);
  const [first, ...rest] = pressing;

  return (
    <>
      {/* ── 主角 ───────────────────────────────────────────────
          **第一件事单独占一层。** 原来它是卡片里的一行小字，跟"已清"
          和"底座"排在一起，重量一样——而这一页的标题问的就是"先做哪件"，
          答案不该跟脚注长得一样。

          现在：一个大号数字 + 一句人话 + 一个动作。其余的压成一行。 */}
      <section className="panel today-hero" aria-label="今天先做哪件">
        <span className="today-block-label">先做哪件</span>

        {first ? (
          <>
            <button type="button" className="today-hero-main" onClick={first.go}>
              <strong className={`today-hero-num today-hero-num--${first.tone}`}>{first.count}</strong>
              <span className="today-hero-copy">
                <b>{first.label}</b>
                <em>{first.hint}</em>
              </span>
              <span className="today-hero-go" aria-hidden="true">→</span>
            </button>
            {/* 其余的排成一行。**它们是真的要做，但不是现在做**——
                给一整行等于把主角的分量分掉。 */}
            {(rest.length > 0 || clear.length > 0) && (
              <div className="today-rest">
                {rest.map((bucket) => (
                  <button type="button" key={bucket.key} onClick={bucket.go}>
                    <i className={`today-dot today-dot--${bucket.tone}`} aria-hidden="true" />
                    {bucket.label} <b>{bucket.count}</b>
                  </button>
                ))}
                {clear.length > 0 && (
                  <span className="today-rest-clear">已清：{clear.map((b) => b.label).join("、")}</span>
                )}
              </div>
            )}
          </>
        ) : (
          <p className="today-clear">今天没有到期的事。反证没出现、逻辑没到复核期、公告都核完了。</p>
        )}
      </section>

      {/* ── 状态条 ─────────────────────────────────────────────
          持仓和数据只是背景信息，不与待办争夺注意力。 */}
      <div className="today-strip">
        <HoldingBlock dashboard={dashboard} onGo={onGoHoldings} />
        <button type="button" className="today-block today-block--data" onClick={onGoData}>
          <span className="today-block-label">数据底座</span>
          <span className="today-data-line">{dashboard.data_health}</span>
        </button>
      </div>
    </>
  );
}
