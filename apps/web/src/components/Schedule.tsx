/**
 * 未来有哪些日子在等着 —— 甘特图。
 *
 * ## 别跟 CompanyTimeline 搞混
 *
 * 那一个是**估值走势 + 公告/交易/判断的时点标记**，问的是"我买的时候贵不贵、
 * 之后出了什么事"。这一个是**承诺与解禁的区间**，问的是"还有多久、会不会撞在一起"。
 * 前者每一项是一个时点，后者每一项是一段时长 —— 画不到一张图上。
 * 第一版这个也叫 Timeline，接口路径也撞在同一个 `/timeline` 上。
 *
 * ## 为什么不用 ECharts
 *
 * 甘特图就是一排按时间定位的条。用 HTML + 百分比定位写，比塞进图表库的
 * custom series 短得多，也不用把另一个图表类型加进首屏预算。**唯一要小心的是
 * 时间到位置的换算只能有一处** —— 条、点、今天那根线、年份刻度，全走 `at()`。
 *
 * ## 今天那根线是这张图的重点
 *
 * 承诺和解禁真正要问的是「还有多久」。少了今天的位置，一排条只能回答
 * 「有哪些」—— 那是列表就能做的事，不值得画一张图。
 */

import { useMemo } from "react";

export type ScheduleItem = {
  title: string; start: string; end: string | null; point: boolean;
  state: string; detail: string; url?: string | null; kind: string;
  /** 终点是按原话的相对期限推出来的，会偏几周 —— 画成虚边。 */
  estimated?: boolean;
  /** 解禁市值（亿元）。有就用来决定条的深浅，没有就一律用基准色。 */
  weight?: number | null;
};
export type ScheduleLane = { key: string; label: string; note: string; items: ScheduleItem[] };
export type ScheduleView = {
  available: boolean; today: string; start: string; end: string;
  lanes: ScheduleLane[];
  missing: Array<{ key: string; why: string }>;
  note?: string; boundary?: string;
};

/** 把 `**粗体**` 渲染出来。跟桑基图那边同一个写法。 */
function rich(text: string) {
  return text.split("**").map((part, index) =>
    index % 2 === 1 ? <b key={index}>{part}</b> : <span key={index}>{part}</span>);
}

const DAY = 86_400_000;
const ms = (iso: string) => Date.parse(`${iso}T00:00:00Z`);

/** 状态 → 条的样子。**过去的事退到背景里**，要看的是还没发生的那些。 */
const TONE: Record<string, string> = {
  进行中: "on", 未解禁: "on", 已到期: "due", 已了结: "done", 已解禁: "done",
};

export function Schedule({ view }: { view: ScheduleView }) {
  // 轨道右边留出 `TAIL`% 给日期标签。
  //
  // 标签跟在条的末尾（`left: calc(条尾 + 8px)`），所以最长那一根的日期会被推到
  // 轨道外面 —— 「公司开展的外汇衍生品交易业务的期限均不超过 3 年」那根一直顶到
  // 2029，日期被面板边缘切成「20…」。**把时间压进左边 88%**，
  // 今天那根线和年份刻度走同一个换算，所以整体不会错位。
  const TAIL = 12;
  const scale = useMemo(() => {
    // 两头各留半个月，否则最早和最晚那两根会贴在边框上。
    const from = ms(view.start) - 15 * DAY;
    const to = ms(view.end) + 15 * DAY;
    const span = Math.max(to - from, DAY);
    return (iso: string) => ((ms(iso) - from) / span) * (100 - TAIL);
  }, [view.start, view.end]);

  // 年份刻度：起止之间的每个 1 月 1 日。跨度小的时候（一年之内）它可能一根都没有，
  // 那也没关系 —— 今天那根线才是必须在的。
  const years = useMemo(() => {
    const out: Array<{ year: number; at: number }> = [];
    for (let y = new Date(ms(view.start)).getUTCFullYear();
         y <= new Date(ms(view.end)).getUTCFullYear() + 1; y += 1) {
      const at = scale(`${y}-01-01`);
      if (at >= 0 && at <= 100 - TAIL) out.push({ year: y, at });
    }
    return out;
  }, [view.start, view.end, scale]);

  if (!view.available) {
    return <div className="empty-state">{view.note || "还排不出时间线。"}</div>;
  }
  const todayAt = scale(view.today);

  return <div className="gantt">
    <div className="gantt-body">
      {/* 年份刻度与今天那根线铺在所有泳道下面，所以定位元素是 .gantt-body。 */}
      <div className="gantt-grid" aria-hidden="true">
        {years.map((tick) => <span key={tick.year} className="gantt-year"
          style={{ left: `calc(var(--gantt-label) + (100% - var(--gantt-label)) * ${tick.at / 100})` }}>
          <em>{tick.year}</em>
        </span>)}
        <span className="gantt-today"
          style={{ left: `calc(var(--gantt-label) + (100% - var(--gantt-label)) * ${todayAt / 100})` }}>
          <em>今天</em>
        </span>
      </div>

      {view.lanes.map((lane) => <section key={lane.key} className="gantt-lane">
        <h5>{lane.label}<em>{lane.items.length} 条</em></h5>
        {lane.items.map((item, index) => {
          const left = scale(item.start);
          const width = item.point ? 0 : Math.max(scale(item.end ?? item.start) - left, 0.6);
          const tone = TONE[item.state] ?? "done";
          const tip = `${item.start} → ${item.end ?? item.start}\n${item.detail}`
            + (item.url ? "\n点一下打开出处" : "");
          // **整行都能点，不是只有那根条。** 条本身只有 8px 高，点不中；
          // 而使用者要的是「这一条到底说了什么」—— 点开出处才回答得了。
          // 没有 url 的就不做成链接：一个点了没反应的东西比不能点更糟。
          const Row = item.url ? "a" : "div";
          return <Row className={`gantt-row${item.url ? " gantt-row--link" : ""}`}
                      key={`${item.title}-${index}`} title={tip}
                      {...(item.url ? { href: item.url, target: "_blank", rel: "noreferrer" } : {})}>
            <span className="gantt-label">{item.title}</span>
            <span className="gantt-track">
              {item.point
                // **零长度的条画成点，不画成一根竖线。** 竖线看着像"某天开始的一段"。
                ? <i className={`gantt-point gantt--${tone}`} style={{ left: `${left}%` }} />
                : <i className={`gantt-bar gantt--${tone}${item.estimated ? " gantt--guess" : ""}`}
                     style={{ left: `${left}%`, width: `${width}%` }} />}
              {/* 日期跟在条后面。**桑基图那次学到的**：图形只给得出"大概几倍"，
                  而这一页是拿来核公告的 —— 没有日子就没法核。 */}
              <em className="gantt-when" style={{ left: `calc(${left + width}% + 8px)` }}>
                {(item.end ?? item.start).slice(0, 7)}{item.estimated ? " 估" : ""}
              </em>
            </span>
          </Row>;
        })}
        {lane.note && <p className="gantt-lane-note">{rich(lane.note)}</p>}
      </section>)}
    </div>

    {/* **画不出来的那几条要写出来。** 悄悄少一条泳道，看的人会以为这家公司
        没有募投项目；写一句"没有这项数据"，他才知道该去别处找。 */}
    {view.missing.length > 0 && <div className="gantt-missing">
      {view.missing.map((row) => <p key={row.key}>
        <strong>{row.key}</strong>：画不出来 —— {row.why}
      </p>)}
    </div>}
    {view.boundary && <p className="chart-note">{rich(view.boundary)}</p>}
  </div>;
}
