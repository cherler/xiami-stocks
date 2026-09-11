/**
 * 对话式反方：钉在一家公司上，专门找你这条判断可能错在哪。
 *
 * ## 为什么是反方，不是一个会聊天的荐股助手
 *
 * 一个附和你的 Agent 是这个产品里最没价值也最危险的东西：你已经买了、
 * 已经写了逻辑，这时候多一个声音说"有道理"，只是把确信度往上推一格。
 *
 * 反方替你想你不愿意想的那一面。这件事你自己做不了——人没法认真反驳
 * 自己刚写下的东西；找人做又太贵，投研团队里那个专门唱反调的角色，
 * 一个人的项目配不起。
 *
 * ## 每条主张下面必须挂着它的证据
 *
 * 所以这一页不是聊天气泡。气泡会把「有数据支撑的一句」和「听起来像那么回事
 * 的一句」显示成完全一样的东西，而这两者的差别正是这个功能的全部价值。
 * 所以做成卡片：主张一行，**证据逐条列在下面，写着来自哪个工具**。
 *
 * ## 「找不到出处的数」用醒目的方式标出来
 *
 * 代码会把模型说的每个数回原始数据里找一遍。找不到不等于错（可能是它算的差值），
 * 但你必须知道该核哪几个。埋在小字里等于没标。
 *
 * ## 转化按钮而不是"采纳"按钮
 *
 * 它只能提议。反证条件要不要加进你的逻辑、任务要不要建，是你的决定——
 * 所以按钮写的是「加进认错条件」，点了之后打开你自己的修订框，不是直接写库。
 */

import { useEffect, useRef, useState } from "react";
import { Boundary } from "./Boundary";

import { askAdvocate, getAdvocateHistory, getJob, type AdvocatePoint, type AdvocateView } from "../api";
import { useSpendGuard } from "../lib/credits";
import type { BackgroundJob, ThesisRecord } from "../types";


const STARTERS = [
  "我这条逻辑最可能错在哪？",
  "如果三年后我在这只票上亏了 50%，最可能是什么原因？",
  "我的认错条件写得够紧吗，会不会永远触发不了？",
  "这家公司的报表里，有哪个数跟我的判断是矛盾的？",
];

type SavedRun = {
  id: number;
  view: AdvocateView;
  createdAt: string;
};

function shortQuestion(text: string): string {
  const compact = text.replace(/\s+/g, " ").trim();
  return compact.length > 28 ? `${compact.slice(0, 28)}…` : compact;
}

function formatRunDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(date);
}

/** 一条反驳 = 一张可点开的卡片。
 *
 *  **默认收起。** 一轮能出三到五条，每条底下挂着两三条证据、还有"这几个数
 *  找不到出处"的告警和两个转化按钮——全摊开就是一屏读不完的墙，
 *  而你要做的第一件事只是扫一眼「它到底说了哪几件事」。
 *
 *  卡片头就是那一句主张，够你判断要不要展开。 */
function Point({ point, index, onCounter, onTask }: {
  point: AdvocatePoint;
  index: number;
  onCounter: (text: string) => void;
  onTask: (text: string) => void;
}) {
  const [open, setOpen] = useState(false);
  // 有数找不到出处的，收起时也要看得见——**那是你必须自己核的**。
  const flagged = point.untraceable.length > 0;
  return <article className={`ad-point${open ? " ad-point--open" : ""}`}>
    <button className="ad-point-head" type="button" aria-expanded={open}
      onClick={() => setOpen((value) => !value)}>
      <span className="ad-point-no">{index + 1}</span>
      <span className="ad-claim">{point.claim}</span>
      <span className="ad-point-meta">
        {flagged && <i className="ad-point-flag" title="有数字在库里找不到出处">!</i>}
        {point.evidence.length} 条证据
        <i className="ad-point-caret" aria-hidden="true">{open ? "▾" : "▸"}</i>
      </span>
    </button>
    {open && <div className="ad-point-body">
    <ul className="ad-evidence">
      {point.evidence.map((item, index) => <li key={index}>
        <span className="ad-tool">{item.tool}</span>{item.shows}
      </li>)}
    </ul>
    {/* 超出复核上限的没被独立再查过。**不标的话它会假装自己也核过了**，
        而"核过的"和"没核过的"在这一页上的分量完全不同。 */}
    {point.unchecked && <p className="ad-unchecked">
      这一条没有经过独立复核（一轮最多复核前几条）——用它之前请自己多看一眼。
    </p>}
    {/* 埋在小字里等于没标——这几个数是你必须自己核的。 */}
    {point.untraceable.length > 0 && <p className="ad-untraceable">
      <strong>这几个数在库里找不到出处：{point.untraceable.join("、")}。</strong>
      可能是它自己算的差值，也可能是编的。用之前请自己核一眼。
    </p>}
    {/* **这是整条链的收口。**
        反驳 → 提议一条认错条件 → 你点它 → 打开你自己的修订框 → 保存 →
        以后公告撞上它 → 首屏那一块亮起来。
        它原来长得跟一个链接一样，而它是这个功能唯一的产出。 */}
    <div className="ad-convert">
      {point.counter_condition && <button className="ad-take" type="button"
        onClick={() => onCounter(point.counter_condition)}>
        <span className="ad-take-do">加进认错条件 →</span>
        <span className="ad-take-text">{point.counter_condition}</span>
      </button>}
      {point.task && <button className="text-button" type="button"
        onClick={() => onTask(point.task)}>记成下一步要查的：「{point.task}」</button>}
    </div>
    </div>}
  </article>;
}

/** 首屏那个「让它驳这条」带过来的意图。**它要把人送到这一块，不是送到这一页。**
 *
 *  原来只做到 tab=research，人落在页面顶部，而这一块在投资逻辑和证据档案
 *  下面、屏幕外——点完像什么都没发生（使用者原话："然后就没有了"）。
 *
 *  滚过来 + 把问题填好，但**不自动跑**：跑一次要花几十分，
 *  从别的页面点一个按钮就扣钱，是这个站最不该有的事。
 *  最后那一下必须是他在这个按钮上按的。 */
function wantedByUrl(): boolean {
  return new URLSearchParams(window.location.search).get("do") === "advocate";
}

export function Advocate({ companyId, theses, onRevise }: {
  companyId: number;
  theses: ThesisRecord[];
  /** 把反证条件交回给页面上已有的「修订这条逻辑」表单。**这里不直接写库。** */
  onRevise: (thesisId: number, counterCondition: string) => void;
}) {
  const [question, setQuestion] = useState("");
  // 在驳哪一条。**这个功能叫"驳你的判断"，那就得先说清是哪一条判断。**
  const [targetId, setTargetId] = useState<number | undefined>(theses[0]?.id);
  const [job, setJob] = useState<BackgroundJob | null>(null);
  // 每一轮都有后台任务 id，结果从存档恢复后仍能在上方胶囊之间切换。
  const [runs, setRuns] = useState<SavedRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // 价钱不挂在按钮上，扣之前弹一句（见 lib/credits.ts 的 useSpendGuard）。
  const confirmSpend = useSpendGuard();

  const running = job !== null && (job.status === "运行中" || job.status === "排队中");

  /** 收下一轮结果。
   *
   *  **同一轮会被轮询取到很多次**，所以要去重；但去重的键必须是任务 id，
   *  不能是问题内容——同一个问题问第二遍是完全正当的（改了判断之后再驳一次），
   *  按内容去重会把第二轮当成重复丢掉，而那一轮的钱已经花了。 */
  const adopted = useRef<Set<number>>(new Set());
  function adopt(jobId: number, next: AdvocateView, createdAt = new Date().toISOString()) {
    if (adopted.current.has(jobId)) return;
    adopted.current.add(jobId);
    setRuns((prev) => [{ id: jobId, view: next, createdAt }, ...prev]);
    setSelectedRunId(jobId);
  }

  // 被首屏点进来的：滚过来，把问题填好，光标停在按钮上。
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!box || !wantedByUrl()) return;
    box.scrollIntoView({ behavior: "smooth", block: "start" });
    setQuestion((current) => current || STARTERS[0]);
  }, [box]);

  // **进来先读一叠：有没有还在跑、或者已经跑完的。**
  //
  // 原来只在 running 为真时轮询，而挂载时 job 是 null、running 就是 false——
  // 之前只读 latest_job，历史结果虽然在库里，刷新后却从页面消失。
  useEffect(() => {
    let live = true;
    Promise.all([getAdvocateHistory(companyId), getJob("advocate", companyId)]).then(([history, latest]) => {
      if (!live) return;
      const completed = history.filter((item) => item.status === "已完成" && item.result);
      const saved = completed.map((item) => ({
        id: item.id,
        view: item.result as unknown as AdvocateView,
        createdAt: item.created_at,
      }));
      completed.forEach((item) => adopted.current.add(item.id));
      setRuns(saved);
      setSelectedRunId(saved[0]?.id ?? null);
      const active = history.find((item) => item.status === "运行中" || item.status === "排队中");
      setJob(latest ?? active ?? history[0] ?? null);
    }).catch(() => undefined);
    return () => { live = false; };
  }, [companyId]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      void getJob("advocate", companyId).then((next) => {
        setJob(next);
        if (next?.status === "已完成" && next.result) {
          adopt(next.id, (next.result as unknown) as AdvocateView, next.created_at);
        }
      }).catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [running, companyId]);

  async function ask(text: string) {
    if (!text.trim()) return;
    if (!(await confirmSpend("devils-advocate", "让它去查库、找出你这条判断可能错在哪。"))) return;
    setBusy(true); setError("");
    // 上一轮的 messages 接着传：它记得刚才查过什么，不用重查。
    try { setJob(await askAdvocate(companyId, text.trim(), runs[0]?.view.messages ?? [])); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "提交失败"); }
    finally { setBusy(false); }
  }

  function takeCounter(text: string) {
    // **原来这里永远写 theses[0]。** 有三条判断时，你驳的是第二条，
    // 认错条件却加到第一条上——而且加完没有任何提示说加错了地方。
    const target = theses.find((row) => row.id === targetId) ?? theses[0];
    if (!target) { setError("这家公司还没有投资逻辑，先写一条再谈反证条件。"); return; }
    onRevise(target.id, target.counter_condition
      ? `${target.counter_condition}\n${text}` : text);
  }

  const target = theses.find((row) => row.id === targetId) ?? theses[0];
  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null;
  const selectedView = selectedRun?.view ?? null;

  const target_row = theses.length > 0 && <div className="ad-target">
      <span>正在检查</span>
      {theses.length > 1
        ? <select aria-label="选择要反驳的投资逻辑" value={targetId}
            onChange={(event) => setTargetId(Number(event.target.value))}>
            {theses.map((row) => <option key={row.id} value={row.id}>
              {row.claim.split("；")[0].slice(0, 40)}
            </option>)}
          </select>
        : <b>{target?.claim.split("；")[0]}</b>}
    </div>;

  return <div className="advocate" ref={setBox}>
    <section className="ad-history" aria-label="已保存的反驳结果">
      <div className="ad-history-heading">
        <span>已保存的反驳</span>
        <em>{runs.length ? `${runs.length} 轮` : "还没有结果"}</em>
      </div>
      {runs.length > 0
        ? <div className="ad-run-chips" role="tablist" aria-label="反驳结果列表">
            {runs.map((run, index) => <button key={run.id} type="button" role="tab"
              aria-selected={run.id === selectedRun?.id}
              className={`ad-run-chip${run.id === selectedRun?.id ? " ad-run-chip--on" : ""}`}
              onClick={() => setSelectedRunId(run.id)}>
              <span className="ad-run-chip-index">#{runs.length - index}</span>
              <span className="ad-run-chip-question">{shortQuestion(run.view.question)}</span>
              <time>{formatRunDate(run.createdAt)}</time>
            </button>)}
          </div>
        : <p className="ad-history-empty">提交一次问题后，反驳结果会出现在这里。</p>}
    </section>

    <section className="ad-composer" aria-label="发起一次反驳">
      {/* 驳的是哪一条 —— 摆在输入框正上方：它是这次提问的上下文，
          而下面每条反驳给出的认错条件都会加到它上面。 */}
      {target_row}
      <div className="ad-composer-label">
        <span>提出一个问题</span>
        <em>每次结果都会保存在上方</em>
      </div>
      <div className="ad-ask">
        <textarea value={question} rows={2} placeholder="问它一句。越具体越有用。"
          onChange={(event) => setQuestion(event.target.value)} />
        <button className="page-action" type="button" disabled={busy || running || !question.trim()}
          onClick={() => void ask(question)}>
          {running ? "正在查库…" : busy ? "正在提交…" : "让它反驳我"}
        </button>
      </div>
      <details className="ad-starters-wrap">
        <summary>常用问题</summary>
        <div className="ad-starters">
          {STARTERS.map((text) => <button key={text} className="text-button" type="button"
            disabled={busy || running}
            onClick={() => { setQuestion(text); void ask(text); }}>{text}</button>)}
        </div>
      </details>
    </section>

    {error && <p className="form-error">{error}</p>}
    {running && <p className="restore-message">
      {job?.label}…　<strong>它在服务端一张表一张表地查</strong>，可以切走，回来还在。
    </p>}
    {job && (job.status === "失败" || job.status === "已中断") &&
      <p className="form-error">{job.status}：{job.error || job.note}</p>}

    {selectedView && <section className="ad-run" aria-label={`反驳结果：${selectedView.question}`}>
      <div className="ad-run-head">
        <div>
          <span className="ad-run-kicker">第 {runs.findIndex((run) => run.id === selectedRun?.id) + 1} 轮反驳</span>
          <p className="ad-question">{selectedView.question}</p>
        </div>
        <p className="ad-trace">
          {selectedView.tool_calls.length === 0 ? "未查到可用数据"
            : `已查 ${selectedView.tool_calls.length} 张表`}
        </p>
      </div>

      <div className="ad-result-body">
        {selectedView.points.length === 0
          ? <p className="form-note">这一轮没有拿得出数据支撑的反方主张——宁可空手。</p>
          : selectedView.points.map((point, index) => <Point key={index} point={point} index={index}
            onCounter={takeCounter}
            onTask={(text) => setNotes((prev) => [...prev, text])} />)}

        {selectedView.not_challenged && <p className="ad-standing">
          <strong>仍然站得住：</strong>{selectedView.not_challenged}
        </p>}
        {selectedView.gaps.length > 0 && <details className="ad-gaps">
          <summary>解释说明 · {selectedView.gaps.length} 条数据边界</summary>
          <ul>
            {selectedView.gaps.map((gap) => <li key={gap}>{gap}</li>)}
          </ul>
        </details>}
      </div>
      <Boundary text={selectedView.boundary} />
    </section>}

    {notes.length > 0 && <div className="ad-notes">
      <strong>你标下来要查的：</strong>
      <ul>{notes.map((note, index) => <li key={index}>{note}</li>)}</ul>
    </div>}
  </div>;
}
