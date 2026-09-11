/**
 * 综合榜 · 打底层的结果页。
 *
 * ## 名字改过：原来叫「智能体荐股池」
 *
 * 那个名字是按"做完之后的样子"起的（commit 2106544 标题里就写着「方案第 1、2 步」），
 * 而后面几步一直没做。它实际是：五套规则取并集，再排个序——
 * **没有决策、没有循环、没有工具，同样的数据跑一百次给一模一样的答案。**
 *
 * 2026 年说「智能体」，所有人理解的都是 LLM 驱动的自主体。
 * 这个产品里只有一个东西配得上那个词：反方 Agent（9 个工具、最多 6 轮、
 * 查哪几张表它自己定）。把一段排序代码也叫智能体，是借了它没有的信用。
 *
 * ## 总分也去掉了
 *
 * 原来把六个维度按 25/20/15/15/15/10 加权求和成一个 0–100 的分，
 * 而页面自己必须写一句「权重写在代码里，不同意就改，别把它当成一个客观评分」——
 * **一个需要免责声明的分数，就是不该给的分数。**
 *
 * 现在按「命中了几套规则」排：那是数出来的。同一档里没有客观先后，
 * 页面上直说。编一个小数点后一位的分来打破平局，是在制造不存在的区分度。
 *
 * ## 这一层没有智能体
 *
 * 名字里有「智能体」，但这一层**一次模型都不调**：规则取并集，代码打分排序。
 * 页面上必须说清楚，否则一份纯规则的结果被当成模型的判断，那比没有更糟。
 * 模型视角是后面加上去的一层。
 *
 * ## 口味是三个池子，不是三组权重
 *
 * 价值和动量在构造上是负相关的：一只票涨过一波，PE 就上去了，价值规则不会再选它。
 * 所以「找不出趋势股」不是权重问题，是打底那一层的结构问题——**把两种分数平均，
 * 选出来的是"两边都平庸"的票**。三个口味是三个独立的池子：各自的规则、各自的尺子。
 *
 * 换口味必须清掉上一份结果。留着最危险：标签已经变成「趋势型」，
 * 下面还是上一次价值池的票，而两者长得一模一样，没人看得出来。
 *
 * ## 为什么权重不画成图
 *
 * 五个权重加起来 100，看着很像一张饼图或堆叠条。但这五个数的信息量只有
 * 「25/25/20/15/15」，而真正要读的是**标签**——哪五项、为什么是这五项。
 * 画成图之后人要先在色块和图例之间来回找，才能知道那截色块是"生意质量"。
 * 一行文字直接就说清楚了。**不是所有数据都该变成图。**
 *
 * ## 分数条为什么是同一个颜色
 *
 * 五项不是五个互相竞争的系列，是**同一把尺子量的五个侧面**——都是 0–100 的
 * 池内分位，都是越高越靠前。给它们五个色相等于说"这是五类东西"，
 * 那会让人去比较颜色而不是比较长度。同一个颜色，标签负责区分身份。
 *
 * 唯一的例外标记是价值口味里的人气：它的原始含义是反的（人气越低分越高），
 * 所以标签上挂一个「反」。**用记号不用颜色**——颜色标反向，色觉障碍者读不到，
 * 而这条恰恰是最不能读错的。趋势口味里人气是正向的，不挂这个记号。
 *
 * ## 行业分布是这一页最该被质疑的地方
 *
 * 价值类规则天然把银行、保险、公用事业推到前面（实测前十有五家银行保险），
 * 趋势榜单则会整片整片地扎堆——一个板块动起来，里面的票会一起上榜。
 * 两种都是规则的结构性偏好，不是"这个行业眼下特别好"。只给排序不给分布，
 * 读的人会把这个偏好当成一个发现，所以它跟结果并排，不折叠。
 *
 * 条的长度是**真实只数**，不换算成百分比——十只里三只就是三只。
 */

import { useState } from "react";
import { Boundary } from "./Boundary";

import { importWatchlist, runAgentPool, type AgentPool as Pool, type AgentPoolRow } from "../api";
import { chartPalette } from "./chartTokens";

const BAR = chartPalette.blue;
// **默认 5 只，不是 30。** 个人一个月能真正研究透 4–8 家，
// 而原来一次给 30——四到七倍的过量供给。给一份处理不完的清单，跟没给是一回事。
const WIDTHS = [5, 10, 20] as const;

// 口味在跑之前就要能选，所以不能只靠返回值里的 stances。
// 这三个是后端 STANCES 的镜像；后端跑完会带回真的那一份，以它为准。
const STANCES = [
  { key: "value", label: "价值型", blurb: "便宜、赚钱、没人讨论。人气反着读。" },
  { key: "trend", label: "趋势型", blurb: "在涨、有量、有人参与。人气正着读。" },
  { key: "both", label: "两边都在", blurb: "同时过价值和趋势两边。交集，通常很少。" },
] as const;

function errorText(caught: unknown): string {
  return caught instanceof Error ? caught.message : String(caught);
}

/** 后端那些说明文字里的 `**着重**` 渲染成 <strong>。
 *
 * **这是个已经上过线的显示 bug**：后端字符串（boundary、concentration、
 * 每个打分项的 reading）里带着 `**…**`，而 JSX 把字符串原样输出，
 * 于是页面上真的印着一串星号。着重号本身是有意义的——那几句正是最不能被
 * 一扫而过的——所以补一个渲染器，而不是把着重从文案里删掉。
 *
 * 只认这一种记号，不引入 markdown 库：多一个语法就多一处会渲染错的地方。
 */
function rich(text: string): React.ReactNode[] {
  return text.split(/\*\*/).map((part, index) =>
    index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>);
}

/** 一只票的几项分数。长度就是分位，0–100，同一把尺子。
 *
 * 池子太小排不出分位时（`unranked`）**不画条，直接列原始值**：
 * 那时候这几个数就是这张卡上仅有的信息，画一排空槽等于把一张能读的卡变成空卡。
 */
function ScoreBars({ row }: { row: AgentPoolRow }) {
  if (row.unranked) {
    return (
      <dl className="ap-raw">
        {row.scores.map((score) => (
          <div key={score.key}>
            <dt>{score.label}</dt>
            <dd>{score.detail}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <div className="ap-bars" role="img"
         aria-label={row.scores.map((s) => `${s.label} ${s.score ?? "无数据"}`).join("，")}>
      {row.scores.map((score) => (
        <div className="ap-bar" key={score.key} title={score.detail}>
          <span className="ap-bar-name">
            {score.label}
            {/* 反向由后端显式声明。**别再靠标签里有没有「反向」两个字**——
                改一次文案记号就无声消失，而同一个人气字段在两个口味里方向相反。 */}
            {score.reverse && <i className="ap-rev" title="反向：人气越低分越高">反</i>}
          </span>
          <div className="ap-bar-track">
            {score.score === null
              ? <em className="ap-bar-none">没数据</em>
              : <i style={{ width: `${score.score}%`, background: BAR }} />}
          </div>
          <span className="ap-bar-value">{score.score === null ? "—" : score.score}</span>
        </div>
      ))}
    </div>
  );
}

function Row({ row, onAdopted, onWrite }: {
  row: AgentPoolRow; onAdopted: (symbol: string) => void; onWrite?: (symbol: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");

  /** 建档。**这一页原来一个可执行的动作都没有**——
   *  整个功能的落点是"接下来研究哪几家"，看完却只能手抄代码去别处搜。 */
  async function adopt() {
    setBusy(true); setSaid("");
    try {
      const outcome = await importWatchlist({ symbols: [row.symbol], watch_group: "候选池" });
      setSaid(outcome.results[0]?.status ?? "已处理");
      onAdopted(row.symbol);
    } catch (caught) { setSaid(errorText(caught)); } finally { setBusy(false); }
  }

  return (
    <article className="ap-row">
      <div className="ap-head">
        <div className="ap-id">
          <strong>{row.name}</strong>
          {row.in_research_pool ? (
            <span className="ap-adopt ap-adopt--done">已在研究池</span>
          ) : (
            <button type="button" className="text-button ap-adopt" disabled={busy} onClick={() => void adopt()}>
              {busy ? "正在建档…" : "建档到候选池"}
            </button>
          )}
          <span className="ap-symbol">{row.symbol}</span>
          {row.industry && <em>{row.industry}</em>}
        </div>
        {/* **英雄数字换成了「命中几套规则」。**
            原来这里是一个 0–100 的加权总分，而那个分需要一句免责声明才敢摆出来。
            命中数是数出来的：这只票同时过了几套互不相同的规则，
            点开下面那排标签就能一条条核对是哪几套。 */}
        <div className="ap-total">
          <strong>{row.matched.length}</strong>
          <span className="ap-total-unit">套规则同时命中</span>
          <em>{row.coverage}</em>
        </div>
      </div>

      <div className="ap-matched">
        {row.matched.map((name) => <span className="ap-chip" key={name}>{name}</span>)}
        {/* **这一页的终点应该是「写下一个判断」，不是「再看一份清单」。**
            建档只是归档动作，写下判断才是这整个系统真正的产出——
            一年大约十个决定，其余全是输入。 */}
        {onWrite && (
          <button type="button" className="text-button ap-write" onClick={() => onWrite(row.symbol)}>
            写下判断
          </button>
        )}
        {said && <span className="ap-said">{said}</span>}
      </div>

      <ScoreBars row={row} />

      {row.attention_rank !== null && (
        <p className="ap-note">
          全市场人气排第 <strong>{Math.round(row.attention_rank)}</strong> 位
          {row.sentiment_as_of ? `（${row.sentiment_as_of}）` : ""}。
          排得越靠后说明讨论得越少。
        </p>
      )}

      {row.context.length > 0 && <>
        <button type="button" className="text-button ap-more" onClick={() => setOpen((v) => !v)}>
          {open ? "收起" : "看情绪面原始数"}
        </button>
        {open && <dl className="ap-context">
          {row.context.map((item) => (
            <div key={item.key}>
              <dt>{item.label}</dt>
              <dd>{item.value === null ? "—" : Number(item.value).toLocaleString()}<em>{item.note}</em></dd>
            </div>
          ))}
          <p className="ap-context-note">
            综合得分与机构参与度是东方财富自己的模型算的，口径不公开。
            <strong>它们只在这里展示，没有算进上面的总分</strong>——
            把一个黑箱的输出乘上权重，这个总分就没法解释了。
          </p>
        </dl>}
      </>}
    </article>
  );
}

/** 行业分布。长度 = 真实只数，不换算成百分比。 */
function Industries({ rows, total }: { rows: Pool["industries"]; total: number }) {
  if (rows.length === 0) return null;
  const max = Math.max(...rows.map((r) => r.count), 1);
  return (
    <figure className="ap-fig">
      <figcaption>这批候选落在哪些行业<span>条的长度 = 只数，共 {total} 只</span></figcaption>
      <div className="ap-inds" role="img"
           aria-label={rows.map((r) => `${r.name} ${r.count} 只`).join("，")}>
        {rows.map((item) => (
          <div className="ap-ind" key={item.name}>
            <span className="ap-ind-name">{item.name}</span>
            <div className="ap-ind-track"><i style={{ width: `${(item.count / max) * 100}%`, background: BAR }} /></div>
            <span className="ap-ind-count">{item.count}</span>
          </div>
        ))}
      </div>
    </figure>
  );
}

export function AgentPool({ onWrite, onSaveTask, savingTask = false, limit, onLimitChange }: {
  onWrite?: (symbol: string) => void;
  /** 把当前已经生成的榜单固化成研究任务，不重新跑一遍规则。 */
  onSaveTask?: (symbols: string[]) => Promise<void>;
  savingTask?: boolean;
  /** 榜单取前几只。**由父层持有**——下面那块「让模型看」要用同一个数：
   *  两个数各管各的话，页面会出现「榜单 5 家、让模型看前 20 名」这种
   *  读起来像会看 20 家、实际只有 5 家的组合。 */
  limit: number;
  onLimitChange: (next: number) => void;
}) {
  const setLimit = onLimitChange;
  const [stance, setStance] = useState<string>("value");
  const [pool, setPool] = useState<Pool | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [collapsed, setCollapsed] = useState(false);

  async function run(which = stance) {
    setRunning(true); setError("");
    try {
      setPool(await runAgentPool(limit, which));
    } catch (caught) { setError(errorText(caught)); setPool(null); } finally { setRunning(false); }
  }

  // 换口味就把上一份结果清掉。**留着旧结果最危险**：标签已经变成「趋势型」，
  // 下面还是上一次价值池的票，而两者长得一模一样，没人看得出来。
  function pick(next: string) {
    if (next === stance) return;
    setStance(next); setPool(null); setError("");
  }

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">第一步·规则打底</span>
          <h2>综合榜</h2>
          <p>
            规则各筛一遍取并集，按命中规则数排序。需要模型逐家复核，请在下方启动。
          </p>
        </div>
        <div className="intro-actions">
          <label className="ap-limit">
            榜单取前
            {/* 改数量也要清掉旧结果。换口味清了、换数量不清的话，
                选了 50 而下面还是 30 只，`dropped` 也是旧的——控件看起来生效了，其实没有。 */}
            <select value={limit} disabled={running}
                    onChange={(e) => { setLimit(Number(e.target.value)); setPool(null); setError(""); }}>
              {WIDTHS.map((n) => <option value={n} key={n}>{n} 只</option>)}
            </select>
          </label>
          <button className="page-action" disabled={running} onClick={() => void run()}>
            {running ? "正在跑…" : pool ? "重新生成榜单" : "生成榜单"}
          </button>
          {pool && onSaveTask && <button
            className="text-button"
            type="button"
            disabled={running || savingTask || pool.rows.length === 0}
            onClick={() => void onSaveTask(pool.rows.map((row) => row.symbol))}
          >
            {savingTask ? "正在保存…" : "存为研究任务"}
          </button>}
          <button className="text-button" type="button" onClick={() => setCollapsed((value) => !value)}>
            {collapsed ? "展开第一步" : "收起第一步"}
          </button>
        </div>
      </div>

      {collapsed && <p className="ap-collapsed-note">
        {running ? "规则筛选正在运行，展开可查看进度。" : pool ? `规则结果已保留，共 ${pool.rows.length} 家。` : "展开查看规则筛选与结果。"}
      </p>}

      {!collapsed && <>
      {/* 口味是**三个池子**，不是一个池子的三组权重。
          价值和动量在构造上负相关：涨过一波 PE 就上去了，价值规则不会再选它。
          把两种分数平均，选出来的是"两边都平庸"的票——所以分池子。 */}
      <div className="ap-stances" role="group" aria-label="选口味">
        {(pool?.stances ?? STANCES).map((item) => (
          <button type="button" key={item.key} disabled={running}
                  className={`ap-stance${item.key === stance ? " ap-stance--on" : ""}`}
                  onClick={() => pick(item.key)}>
            <strong>{item.label}</strong>
            <em>{rich(item.blurb)}</em>
          </button>
        ))}
      </div>

      {/* **不再印权重，因为不再有总分。**
          原来这里写「总分怎么来的：趋势强度 25% · 生意质量 20% · …」，
          而紧接着要补一句"别把它当成一个客观评分"——那句话说明这个分不该给。 */}
      {pool && <p className="ap-weights">
        按命中规则数排序；同档位不代表优劣。每项分位独立展示，不合成总分。
      </p>}

      {error && <p className="form-error">{error}</p>}
      {running && <div className="empty-state">正在跑全市场规则筛…</div>}

      {!running && !pool && !error && <div className="empty-state">
        选好口味，点「生成榜单」。
      </div>}

      {!running && pool && <>
        <p className="ap-summary">{rich(pool.note)}</p>
        {!pool.ranked && <p className="ap-warn">{rich(pool.unranked_reason)}</p>}
        {pool.concentration && <p className="ap-warn">{rich(pool.concentration)}</p>}

        <Industries rows={pool.industries} total={pool.returned} />

        <div className="ap-list">
          {pool.rows.map((row) => (
            <Row row={row} key={row.symbol} onWrite={onWrite}
                 onAdopted={(symbol) => setPool((current) => current && {
                   ...current,
                   rows: current.rows.map((r) =>
                     r.symbol === symbol ? { ...r, in_research_pool: true } : r),
                 })} />
          ))}
        </div>

        {pool.dropped > 0 && <p className="ap-note ap-note--drop">
          池子里还有 <strong>{pool.dropped}</strong> 只没显示出来。
          {pool.capacity_note ? rich(pool.capacity_note) : "把「榜单取前」调大可以看到更多。"}
        </p>}

        <div className="ap-readings">
          <h3>每一项是怎么读的</h3>
          <ul>{pool.dimensions.map((d) => (
            <li key={d.key}><strong>{d.label}</strong>：{rich(d.reading)}</li>
          ))}</ul>
        </div>

        <Boundary text={pool.boundary} />
      </>}
      </>}
    </section>
  );
}

export const AGENT_POOL_KEY = "__agent_pool__";
