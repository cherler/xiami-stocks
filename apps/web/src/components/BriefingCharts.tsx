/**
 * 今日简报的图表部分。
 *
 * ## 为什么原来是一大坨文字
 *
 * 不是模型写得啰嗦，是**分工错了**：涨跌家数、中位数、行业涨跌幅、持仓成本与
 * 浮盈，这些数字全都是代码自己算好、喂给模型的，模型只是把它们抄进段落里。
 * 于是一份简报里最占篇幅的部分，信息量等于零——那些数我们本来就有。
 * 而且模型抄的时候还可能抄错，抄错了页面也发现不了。
 *
 * 所以拆开：**数字由这里画，模型只说这些数意味着什么。**
 * 提示词里也明确禁止了复述数字。
 *
 * ## 三块图
 *
 * - **市场宽度**：涨/平/跌一条堆叠比例条。它回答"今天是普涨还是普跌"，
 *   而这个问题只有比例有意义——绝对家数（3642 家）对一个业余投资者不构成信息。
 * - **行业涨跌**：发散条，涨的向右、跌的向左，共用一根零轴。
 *   零轴对齐是关键：不对齐的话，"涨 4.35%"和"跌 2.59%"哪个幅度大要靠读数字。
 * - **持仓浮盈**：每行一只，条长是浮盈百分比，零轴居中。
 *
 * ## 颜色
 *
 * 涨红跌绿，A 股惯例。**取的是全站那一份**（chartTokens 的 marketInk），
 * 不再自己配一对——这里原来写的是 #d03b3b / #1baf7a，跟 .quote-up 的 #bd493a
 * 差 ΔE 4.0、跟 .quote-down 的 #277b66 差 ΔE 15.4：一个是看不出差别的重复，
 * 另一个是同一句话在两页上说成两个颜色。
 *
 * 换过来之后色觉障碍下仍然过关（涨/平、涨/跌、平/跌三对，最差 ΔE 8.5）。
 * 而且每条都带文字数值，颜色不是唯一线索——打印、强制配色下照样读得懂。
 */

import { marketInk } from "./chartTokens";

const { up: UP, down: DOWN, flat: FLAT } = marketInk.paper;

export type BriefingContext = {
  breadth?: { advancing?: number; declining?: number; unchanged?: number;
              median_change?: number; covered?: number; note?: string } | null;
  industries?: Array<{ name?: string; metric_value?: number; count?: number }> | null;
  positions?: Array<{ name?: string; symbol?: string; latest_price?: number;
                      average_cost?: number; unrealized_pct?: number; shares?: number }> | null;
};

/** `!== null` 拦不住 undefined；isFinite 同时挡住 null、undefined 和 NaN。 */
function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function Breadth({ breadth }: { breadth: NonNullable<BriefingContext["breadth"]> }) {
  const up = num(breadth.advancing) ?? 0;
  const down = num(breadth.declining) ?? 0;
  const flat = num(breadth.unchanged) ?? 0;
  const total = up + down + flat;
  if (total === 0) return null;
  const median = num(breadth.median_change);

  return (
    <figure className="bfig">
      <figcaption>
        今天的市场
        {/* 中位数是"典型的那只涨了多少"，比涨跌家数更能说明体感 */}
        {median !== null && <span className={median < 0 ? "quote-down" : "quote-up"}>
          中位数 {median > 0 ? "+" : ""}{median.toFixed(2)}%
        </span>}
      </figcaption>
      {/* 比例条而不是家数：3642 家对一个业余投资者不构成信息，"三分之二在涨"才是 */}
      <div className="bbar" role="img"
           aria-label={`上涨 ${up} 家、平盘 ${flat} 家、下跌 ${down} 家，共 ${total} 家`}>
        <i style={{ flexGrow: up, background: UP }} title={`上涨 ${up} 家`} />
        {flat > 0 && <i style={{ flexGrow: flat, background: FLAT }} title={`平盘 ${flat} 家`} />}
        <i style={{ flexGrow: down, background: DOWN }} title={`下跌 ${down} 家`} />
      </div>
      <div className="bbar-legend">
        <span><i style={{ background: UP }} />涨 {up}</span>
        {flat > 0 && <span><i style={{ background: FLAT }} />平 {flat}</span>}
        <span><i style={{ background: DOWN }} />跌 {down}</span>
        <em>{Math.round((up / total) * 100)}% 在涨</em>
      </div>
    </figure>
  );
}

function Industries({ rows }: { rows: NonNullable<BriefingContext["industries"]> }) {
  const items = rows.map((r) => ({ name: r.name ?? "", value: num(r.metric_value), count: r.count }))
                    .filter((r) => r.value !== null && r.name) as
                { name: string; value: number; count?: number }[];
  if (items.length === 0) return null;
  // 共用一根零轴：不对齐的话「涨 4.35%」和「跌 2.59%」哪个幅度大要靠读数字
  const span = Math.max(...items.map((r) => Math.abs(r.value))) || 1;

  return (
    <figure className="bfig">
      <figcaption>涨得最多与跌得最多的行业<span>当日涨跌幅中位数</span></figcaption>
      <div className="bind">
        {items.map((row) => (
          <div className="bind-row" key={row.name}>
            <span className="bind-name">{row.name}</span>
            <div className="bind-track" role="img"
                 aria-label={`${row.name} ${row.value > 0 ? "上涨" : "下跌"} ${Math.abs(row.value).toFixed(2)}%`}>
              <i className="bind-zero" aria-hidden="true" />
              <i className="bind-fill"
                 style={{
                   background: row.value >= 0 ? UP : DOWN,
                   left: row.value >= 0 ? "50%" : `${50 - (Math.abs(row.value) / span) * 50}%`,
                   width: `${(Math.abs(row.value) / span) * 50}%`,
                 }} />
            </div>
            <span className={`bind-value ${row.value < 0 ? "quote-down" : "quote-up"}`}>
              {row.value > 0 ? "+" : ""}{row.value.toFixed(2)}%
            </span>
          </div>
        ))}
      </div>
    </figure>
  );
}

function Positions({ rows }: { rows: NonNullable<BriefingContext["positions"]> }) {
  const items = rows.filter((r) => r.name);
  if (items.length === 0) return null;
  const span = Math.max(...items.map((r) => Math.abs(num(r.unrealized_pct) ?? 0)), 1);

  return (
    <figure className="bfig">
      <figcaption>持仓<span>浮动盈亏，只描述现状</span></figcaption>
      <div className="bind">
        {items.map((row) => {
          const pct = num(row.unrealized_pct);
          return (
            <div className="bind-row" key={row.symbol ?? row.name}>
              <span className="bind-name">{row.name}</span>
              <div className="bind-track">
                <i className="bind-zero" aria-hidden="true" />
                {pct !== null && <i className="bind-fill"
                   style={{
                     background: pct >= 0 ? UP : DOWN,
                     left: pct >= 0 ? "50%" : `${50 - (Math.abs(pct) / span) * 50}%`,
                     width: `${(Math.abs(pct) / span) * 50}%`,
                   }} />}
              </div>
              <span className={`bind-value ${(pct ?? 0) < 0 ? "quote-down" : "quote-up"}`}>
                {pct === null ? "—" : `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`}
              </span>
              <em className="bind-note">
                现价 {num(row.latest_price)?.toFixed(2) ?? "—"} · 成本 {num(row.average_cost)?.toFixed(2) ?? "—"}
              </em>
            </div>
          );
        })}
      </div>
    </figure>
  );
}

export function BriefingCharts({ context }: { context?: BriefingContext | null }) {
  if (!context) return null;
  const blocks = [
    context.breadth ? <Breadth key="b" breadth={context.breadth} /> : null,
    context.industries?.length ? <Industries key="i" rows={context.industries} /> : null,
    context.positions?.length ? <Positions key="p" rows={context.positions} /> : null,
  ].filter(Boolean);
  // 老简报没存 context —— 什么都不画，页面自然回落到纯文字，不显示空图框
  if (blocks.length === 0) return null;

  return <div className="briefing-charts">{blocks}</div>;
}
