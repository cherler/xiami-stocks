/**
 * 管理层承诺兑现台账：公司说过的话，到期之后有没有人回头看。
 *
 * ## 为什么它长得像收件箱，不像图表
 *
 * 这一页的用途不是"看趋势"，是**在到期那天把一句话顶到你面前**。
 * 所以它是一列待办：到期的排最上面，没期限的排最下面，
 * 每一条都能一键给出结论。做成饼图或者"承诺兑现率 78%" 那种数字，
 * 你会看一眼然后再也不管——而承诺台账的全部价值在于**它会催你**。
 *
 * ## 自动核对的结果不着色成红绿
 *
 * 「没对上」是算术，不是判决。染成红色就等于替你判了「管理层食言」，
 * 而真实原因可能是会计口径变了、可能是并表范围变了。
 * 所以四种核对结果用同一套中性色，只在文字上分开——
 * 跟决策归因、假设漂移同一条规矩。
 *
 * ## 抽取出来的不直接入账
 *
 * 一条编出来的承诺会变成你对管理层的成见，而成见不会被复核。
 * 所以每条都摆出原文和出处链接，勾选之后才进台账。
 */

import { useEffect, useState } from "react";
import { Boundary } from "./Boundary";

import {
  extractPromises, getJob, getPromises, savePromises, settlePromise,
  type PromiseFound, type PromiseRow, type PromiseView,
  estimatePromises,
} from "../api";
import type { BackgroundJob } from "../types";
import { useSpendGuard } from "../lib/credits";

function rich(text: string) {
  return text.split("\n\n").map((paragraph, block) =>
    <p key={block}>{paragraph.split(/\*\*/).map((part, index) =>
      index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>)}</p>);
}

const STATUSES = ["待到期", "已兑现", "部分兑现", "未兑现", "无法核对", "已放弃"];

function Row({ row, onChanged }: { row: PromiseRow; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  async function settle(status: string) {
    setBusy(true);
    try { await settlePromise(row.id, status); await onChanged(); }
    finally { setBusy(false); }
  }
  return <article className={`pm-row${row.overdue ? " pm-row--due" : ""}`}>
    <header>
      <span className="pm-cat">{row.category}</span>
      <span className="pm-subject">{row.subject}</span>
      <span className={`pm-status pm-status--${row.status === "待到期" ? "open" : "closed"}`}>{row.status}</span>
      <em>{row.due_date ? `到期 ${row.due_date}` : "没有明确期限"}</em>
    </header>
    {/* 原文照抄，不改写——改写过的承诺没法拿去跟公告对。 */}
    <blockquote className="pm-statement">{row.statement}</blockquote>
    <p className="pm-source">
      {row.promised_on} 说的 ·{" "}
      {row.source_url
        ? <a href={row.source_url} target="_blank" rel="noreferrer">{row.source_title || "打开出处"}</a>
        : <span>{row.source_title || "无出处链接"}</span>}
    </p>

    {/* 「没对上」是算术不是判决，所以不染红。 */}
    <p className={`pm-check pm-check--${row.check.verdict === "对上了" ? "hit" : "plain"}`}>
      <b>{row.check.verdict}</b>
      <span>{row.check.note.replace(/\*\*/g, "")}</span>
    </p>

    {row.overdue && <p className="pm-nudge">
      <strong>这条已经到期了，还没有结论。</strong>核对之后点一下下面的按钮——
      台账的全部价值在于它会催你，而不是等你哪天想起来。
    </p>}

    <div className="pm-actions">
      {STATUSES.filter((s) => s !== row.status).map((s) =>
        <button key={s} className="text-button" type="button" disabled={busy}
          onClick={() => void settle(s)}>标为{s}</button>)}
    </div>
    {row.outcome_note && <p className="pm-note">{row.outcome_note}</p>}
  </article>;
}

export function Promises({ companyId }: { companyId: number }) {
  const [view, setView] = useState<PromiseView | null>(null);
  const [found, setFound] = useState<PromiseFound[] | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [job, setJob] = useState<BackgroundJob | null>(null);
  const [busy, setBusy] = useState("");
  // **候选清单要能收起来。** 一次抽取能出十几条、每条带一整段公告原话，
  // 铺开之后下面那张台账被挤到两屏以外 —— 而台账才是这一页的主角。
  // 默认展开（刚跑完就是要看的），收起之后仍然显示条数，不让人以为结果丢了。
  const [foundOpen, setFoundOpen] = useState(true);
  // **台账自己也要能收起来。** 上一版只给候选清单加了折叠，而使用者说的是
  // 「已录入承诺还是无法折叠」—— 一家跟了两年的公司台账有几十条，每条带原文、
  // 出处和复核按钮，从这一页往下翻到别的模块要滚很久。
  const [savedOpen, setSavedOpen] = useState(true);
  const [error, setError] = useState("");
  // 价钱不挂在按钮上，扣之前弹一句（见 lib/credits.ts 的 useSpendGuard）。
  const confirmSpend = useSpendGuard();

  const running = job !== null && (job.status === "运行中" || job.status === "排队中");

  async function load() {
    try { setView(await getPromises(companyId)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "读取失败"); }
  }
  useEffect(() => { void load(); }, [companyId]);

  // 抽取在服务端跑：几十条公告要读一两分钟，切页面不该让它白跑。
  // 跟反方 Agent 同一条：**进来先问一次**，否则跑完的结果白跑（花钱的动作）。
  //
  // **这里原来只把任务捡回来，没把结果捡回来。** 于是：任务跑完之后离开这一页，
  // 回来时 job 是「已完成」但 running 是 false，下面那个轮询压根不启动，
  // found 永远是 null —— 候选一条都不显示。而按钮旁边写着"可以切到别的页面，
  // 回来还在"。实测那一轮是 8 分、3 次调用、34 份公告正文，
  // 想再看一眼只能再花一次。
  useEffect(() => {
    let live = true;
    getJob("promise_extract", companyId).then((next) => {
      if (!live || !next) return;
      setJob(next);
      if (next.status === "已完成" && next.result) {
        setFound(((next.result as unknown) as { found?: PromiseFound[] }).found ?? []);
      }
    }).catch(() => undefined);
    return () => { live = false; };
  }, [companyId]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      void getJob("promise_extract", companyId).then((next) => {
        setJob(next);
        if (next?.status === "已完成" && next.result) {
          setFound(((next.result as unknown) as { found?: PromiseFound[] }).found ?? []);
          setPicked(new Set());
        }
      }).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [running, companyId]);

  async function scan() {
    // 报价按**这一次**真的要喂多少字算 —— 典型值表报 17 分，而实扣 3 分。
    if (!(await confirmSpend("promise-extract", "让模型去读这家公司的公告原文，抽出管理层做过的承诺。",
                             () => estimatePromises(companyId)))) return;
    setBusy("scan"); setError(""); setFound(null);
    try { setJob(await extractPromises(companyId)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "提交失败"); }
    finally { setBusy(""); }
  }

  if (error && !view) return <p className="form-error">{error}</p>;
  if (!view) return <div className="empty-state">正在读台账…</div>;

  // 已经记进台账的不再当候选摆出来。
  //
  // 把上一轮的结果捡回来之后就需要这一步：不然勾过、存过的那几条会在
  // 下次进来时**原样再出现一遍**，看上去像"又找到了这些"，而它们已经在下面
  // 那张台账里了。按原话认——保存时存的就是这一句。
  const recorded = new Set(view.rows.map((row) => row.statement));
  const pending = found?.filter((item) => !recorded.has(item.statement)) ?? null;

  async function keep() {
    if (!pending) return;
    setBusy("save");
    try {
      await savePromises(companyId, [...picked].sort((a, b) => a - b).map((i) => pending[i]));
      setFound(null); setPicked(new Set()); await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "保存失败"); }
    finally { setBusy(""); }
  }

  const openCount = view.rows.filter((row) => row.status === "待到期").length;
  const dueCount = view.rows.filter((row) => row.overdue).length;
  const settledCount = view.rows.length - openCount;

  return <div className="promises promise-ledger">
    <div className="promise-ledger-head">
      <div className="promise-ledger-copy">
        <span className="eyebrow">可追踪承诺</span>
        <div className="pm-headline">{rich(view.headline)}</div>
      </div>
      <div className="promise-stats" aria-label="承诺状态摘要">
        <div><strong>{openCount}</strong><span>待结论</span></div>
        <div><strong>{dueCount}</strong><span>已到期</span></div>
        <div><strong>{settledCount}</strong><span>已处理</span></div>
      </div>
    </div>
    {view.note && <details className="promise-method-note">
      <summary>这部分怎么工作</summary>
      <div className="pm-hint">{rich(view.note)}</div>
    </details>}
    {error && <p className="form-error">{error}</p>}

    <div className="promise-actions form-actions">
      <button className="page-action" type="button" disabled={busy !== "" || running}
        onClick={() => void scan()}>
        {running ? "正在读公告…" : busy === "scan" ? "正在提交…" : "从公告里找承诺"}
      </button>
      {running && <span className="form-note">
        <strong>任务在服务端跑</strong>，可以切到别的页面，回来还在。
      </span>}
    </div>

    {/* **任务失败必须摆出来。**
        这里原来什么都不显示：任务 500 了，页面上看起来就是"这家公司没有承诺"，
        跟真的没有承诺一模一样。实测使用者连点了几次、每次都失败，
        而他得到的唯一信息是一片空白。 */}
    {job && (job.status === "失败" || job.status === "已中断") && <p className="form-error">
      <strong>这次没跑成：{job.error || job.status}</strong>
      {job.status === "已中断" && "　服务重启会中断任务，再点一次就行。"}
    </p>}

    {pending !== null && <section className="pm-found">
      <div className="promise-section-heading">
        <div><span className="eyebrow">本次抽取</span><h4>模型找到 {pending.length} 条候选承诺</h4></div>
        <div className="pm-found-actions">
          <em>勾选后才会写入台账</em>
          {pending.length > 0 && <button className="text-button" type="button"
            aria-expanded={foundOpen}
            onClick={() => setFoundOpen(!foundOpen)}>
            {foundOpen ? "收起这批候选" : `展开这批候选（${pending.length} 条${picked.size ? `，已勾 ${picked.size}` : ""}）`}
          </button>}
        </div>
      </div>
      {job?.note && <p className="pm-hint">{job.note}</p>}
      {pending.length === 0
        ? <p className="form-note">没有找到符合标准的承诺——要有原文、有数字或期限、能被证伪。</p>
        : !foundOpen
        ? <p className="form-note">
            这批候选收起来了{picked.size ? `，已经勾了 ${picked.size} 条` : ""}——展开就能继续挑。
          </p>
        : <>
          {pending.map((item, index) => <label key={index} className="pm-candidate">
            <input type="checkbox" checked={picked.has(index)}
              onChange={(e) => { const next = new Set(picked); e.target.checked ? next.add(index) : next.delete(index); setPicked(next); }} />
            <div className="pm-candidate-body">
              <div className="pm-candidate-head"><strong>{item.subject}</strong><span className="pm-cat">{item.category}</span><em>{item.due_date ? `到期 ${item.due_date}` : "未注明期限"}</em></div>
              <blockquote>{item.statement}</blockquote>
              {/* **这句话是不是真的在那份公告里，代码已经对过了。**
                  对不上的在服务端就丢了，所以这里只会看到"原文"或"已按原文补回"——
                  摆出来是让你知道它被对过，而不是让你自己去猜。 */}
              {item.verbatim && <span className={item.verbatim === "原文" ? "pm-verbatim" : "pm-verbatim pm-fixed"}>
                {item.verbatim === "原文" ? "已回公告原文核对" : item.verbatim_note || item.verbatim}
              </span>}
              <p className="pm-candidate-meta">{item.promised_on} 说的{item.check_metric ? ` · 可自动核对：${item.check_metric}` : ""}</p>
              {item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">
                {item.source_title || "打开出处"}</a>}
            </div>
          </label>)}
          <div className="form-actions">
            <button className="page-action" type="button" disabled={busy !== "" || picked.size === 0}
              onClick={() => void keep()}>记入选中的 {picked.size} 条</button>
            <button className="text-button" type="button"
              onClick={() => setPicked(new Set(pending.map((_, i) => i)))}>全选</button>
            <button className="text-button" type="button" onClick={() => setFound(null)}>不记了</button>
          </div>
        </>}
    </section>}

    <section className="promise-saved">
      <div className="promise-section-heading">
        <div><span className="eyebrow">已入账</span><h4>承诺台账</h4></div>
        <div className="pm-found-actions">
          <em>{view.rows.length} 条</em>
          {view.rows.length > 0 && <button className="text-button" type="button"
            aria-expanded={savedOpen}
            onClick={() => setSavedOpen(!savedOpen)}>
            {savedOpen ? "收起台账" : `展开台账（${view.rows.length} 条）`}
          </button>}
        </div>
      </div>
      {view.rows.length === 0
        ? <div className="empty-state promise-empty">还没有入账承诺。点击“从公告里找承诺”，先看候选结果，再勾选保存。</div>
        : !savedOpen
        // **收起来之后还得说得出有没有到期的。** 台账的全部价值在于它会催你；
        // 一句"已收起"就把催促也一起收掉了。
        ? <p className="form-note">
            台账收起来了，共 {view.rows.length} 条
            {dueCount > 0
              ? <>，其中 <strong>{dueCount} 条已经到期</strong>还没核 —— 展开就能一条条销。</>
              : "，没有到期未核的。"}
          </p>
        : view.rows.map((row) => <Row key={row.id} row={row} onChanged={load} />)}
    </section>
    <Boundary text={view.boundary} />
  </div>;
}
