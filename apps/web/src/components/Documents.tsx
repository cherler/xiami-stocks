/**
 * 读文档：上传一份 PDF 或贴一个链接，然后问它。
 *
 * ## 这一页的规矩：能核对
 *
 * 每个回答后面都带页码，点得开原文那一页。**做不到这一条，它就退回成了
 * 「随便找个模型问问」** —— 而那种东西在研究里是负资产：看起来像答案，
 * 而你没有任何线索知道它是不是编的。
 *
 * 所以三件事在页面上必须一直看得见：
 *
 * 1. **读成了什么样**：几页表格、几页双栏、**哪几页是扫描件读不到**
 * 2. **这次问答喂了哪几页**：不是"我读了整份年报"，是"我看了第 30、31、45 页"
 * 3. **一个都没命中时说没找到**，不拿前几页凑一个回答
 */

import { useEffect, useId, useState } from "react";

import {
  askDocument, createEvidence, deleteDocument, digestDocument, extractFundraising,
  getDocument, getDocuments, readDocumentUrl, retitleDocument, uploadDocument,
  type DigestBody, type DigestItem, type DocAnswer, type DocDetail, type DocDigest, type DocRow,
} from "../api";
import { numeric, tableGrid, type DigestTable } from "../lib/digest";
import { errorMessage } from "../lib/errormessage";
import type { EvidencePolarity } from "../types";



/** 把 `**粗体**` 渲染出来。跟另外两张图同一个写法。 */
function rich(text: string) {
  return text.split("**").map((part, index) =>
    index % 2 === 1 ? <b key={index}>{part}</b> : <span key={index}>{part}</span>);
}

/**
 * 这份文件读成了什么样，**只说读的人要拿来做判断的那部分**。
 *
 * 原来这里还挂着一排读法标签（「双栏 4」「版面 8」「表格 11」）。那是解析器的内部
 * 计数：一份 23 页的研报报出「表格 11」，指的是 pdfplumber 认出 11 处像表格的区域，
 * 不是这份研报有 11 张表 —— **它连我都要想一下才说得清，读的人拿它做不了任何判断。**
 *
 * 留下来只有两个尺寸。**"有几页读不出"故意不在这里报数**：`read_pages` 数的是
 * 「有文字的页」、下面那条 `.doc-unreadable` 数的是「有问题的页」，一页可以同时算进
 * 两边 —— 两个数摆在一起会互相矛盾（上面说 2 页，下面列了 5 页）。
 * 所以坏消息只在一个地方说，而且带页码：**没消息就是好消息，坏消息要具体。**
 */
function facts(row: DocRow): string {
  return `${row.page_count} 页 · ${(row.char_count / 10000).toFixed(1)} 万字`;
}

export function Documents({ companyId }: { companyId?: number }) {
  // companyId 传进来时这就是公司档案里那个快捷入口：只列这家公司的文件，
  // 新读进来的也自动归到它名下，**回答能一键存成这家公司的证据**。
  const [rows, setRows] = useState<DocRow[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [url, setUrl] = useState("");
  const [open, setOpen] = useState<DocDetail | null>(null);

  async function load() {
    try {
      const view = await getDocuments(companyId);
      setRows(view.rows);
    } catch (caught) { setError(errorMessage(caught)); }
  }
  useEffect(() => { void load(); }, [companyId]);

  async function run(label: string, work: () => Promise<unknown>) {
    setBusy(label); setError("");
    try { await work(); await load(); }
    catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(""); }
  }

  // 刚读进来的那一份自动展开 —— **读完就该看见结果**，不该再点一次「打开来问」。
  async function openLatest(id: number) {
    try { setOpen(await getDocument(id)); } catch { /* 列表已经刷新，展开失败不致命 */ }
  }

  return <div className="documents">
    <div className="doc-intake">
      <label className="page-action doc-upload">
        {busy === "upload" ? "正在读…" : "上传 PDF"}
        <input type="file" accept="application/pdf" hidden disabled={!!busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";           // 同一份文件连传两次也要触发
            if (file) void run("upload", async () => { await openLatest((await uploadDocument(file, companyId)).id); });
          }} />
      </label>
      <input type="url" placeholder="或贴一个 PDF 链接（巨潮、交易所、券商官网）"
        value={url} onChange={(event) => setUrl(event.target.value)} disabled={!!busy} />
      <button className="page-action" type="button" disabled={!!busy || !url.trim()}
        onClick={() => void run("url", async () => {
          const made = await readDocumentUrl(url.trim(), companyId); setUrl(""); await openLatest(made.id);
        })}>
        {busy === "url" ? "正在取…" : "读这个链接"}
      </button>
    </div>
    {error && <p className="form-error">{error}</p>}
    {/* **老文件也要能补好，而且不该再花一次钱。**
        标题从第一页读、标签这两件事是后加的，之前读进来的文件没有。
        那几页原文就在库里，重认一次不调模型。

        条件看的是**有没有标签**，不是"标题像不像文件名" —— 第一版按文件名判，
        而线上那四份的标题是手工给的，于是它们永远补不上标签：
        一份有标签四份没有，比全都没有更难看。 */}
    {(rows ?? []).some((row) => (row.tags ?? []).length === 0) &&
      <p className="doc-retitle">
        <span>有 {(rows ?? []).filter((row) => (row.tags ?? []).length === 0).length} 份还缺标签。</span>
        <button className="text-button" type="button" disabled={!!busy}
          onClick={() => void run("retitle", async () => {
            for (const row of (rows ?? []).filter((r) => (r.tags ?? []).length === 0)) {
              await retitleDocument(row.id);
            }
          })}>{busy === "retitle" ? "正在补…" : "按第一页补上标签（不花积分）"}</button>
      </p>}
    {rows === null && <div className="empty-state">正在读列表…</div>}
    {rows !== null && rows.length === 0 && <div className="empty-state">
      还没读过文件。上传一份年报或研报试试 —— 读完可以逐页翻，也可以直接问它。
    </div>}

    {rows?.map((row) => <article className="doc-card" key={row.id}>
      <div className="doc-card-head">
        <div>
          <strong>{row.title}</strong>
          {/* 标签在标题底下：**类型 · 是谁 · 哪一期** —— 一眼分辨两份文件靠这个。
              跟上一版撤掉的读法标签是两回事：那些是解析器的内部计数，
              这些是文件的身份，而且抽不到的不给（不猜）。 */}
          {(row.tags ?? []).length > 0 && <p className="doc-tags">
            {(row.tags ?? []).map((tag) => <em key={tag}>{tag}</em>)}
          </p>}
          <p className="doc-facts">{facts(row)}</p>
        </div>
        <div className="doc-card-actions">
          <button className="text-button" type="button"
            onClick={() => void (async () => {
              try { setOpen(open?.id === row.id ? null : await getDocument(row.id)); }
              catch (caught) { setError(errorMessage(caught)); }
            })()}>{open?.id === row.id ? "收起" : "打开来问"}</button>
          <button className="text-button text-button--danger" type="button"
            onClick={() => void run("delete", () => deleteDocument(row.id))}>删除</button>
        </div>
      </div>
      {/* **读不到的页逐条列出来，给页码。** 「读了 108 页」会让人以为
          剩下那 2 页里没有他要找的东西。 */}
      {row.unreadable.length > 0 && <p className="doc-unreadable">
        <strong>这几页读不出内容：</strong>
        {row.unreadable.slice(0, 6).map((miss) => `第 ${miss.page} 页`).join("、")}
        {row.unreadable.length > 6 ? ` 等 ${row.unreadable.length} 页` : ""}
        　——　{row.unreadable[0].why}
      </p>}
      {open?.id === row.id && <Reading doc={open} companyId={companyId ?? row.company_id ?? undefined} />}
    </article>)}

  </div>;
}

/**
 * 一份文件读完之后的那一屏：**结果在最上面，追问收在下面。**
 *
 * 上一版是一个空输入框 —— 那要求使用者先想出一个好问题，而想问题恰恰是最难的
 * 那一步。使用者的原话：「读文档就是为了直接得到结果」。他是对的。
 */
function Reading({ doc, companyId }: { doc: DocDetail; companyId?: number }) {
  const [digest, setDigest] = useState<DocDigest | null>(
    doc.digest ? { digest: doc.digest, kind: doc.digest_kind, pages: doc.digest_pages,
                   missed: doc.digest_missed, unverified: doc.digest_unverified,
                   credits: 0, cached: true } : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // **读完自动出结果，不用点。** 已经有结果的（重新打开）直接显示，不重付。
  useEffect(() => {
    if (digest) return;
    let live = true;
    setBusy(true);
    digestDocument(doc.id)
      .then((got) => { if (live) setDigest(got); })
      .catch((caught) => { if (live) setError(errorMessage(caught)); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [doc.id]);

  // 旧版式的结果要重读一次才能变成分层的样子。**重读要花钱，所以由他点** ——
  // 偷偷替他重跑一次是这一页最不该干的事。
  function redo() {
    setBusy(true); setError("");
    digestDocument(doc.id, { redo: true })
      .then(setDigest)
      .catch((caught) => setError(errorMessage(caught)))
      .finally(() => setBusy(false));
  }

  return <div className="doc-reading">
    {busy && <div className="empty-state">正在按「{doc.digest_kind || "研究清单"}」逐条读这份文件…
      通常十几秒。</div>}
    {error && <p className="form-error">{error}</p>}
    {digest && (digest.digest
      ? <div className="doc-digest">
          <p className="doc-digest-head">按<strong>{digest.kind}</strong>的清单读的
            {digest.pages.length > 0 && <>，用了第 {digest.pages.join("、")} 页</>}
            {digest.credits > 0 && <>　本次 {digest.credits} 分</>}。</p>
          <DigestBoard digest={digest} onRedo={redo} busy={busy} />
          {/* **清单里没找到的那几条要列出来。** 一份缺了两条的结果和一份完整的结果
              看起来一模一样，而它们的价值完全不同。 */}
          {digest.missed.length > 0 && <p className="doc-unreadable">
            <strong>这几条在文件里没找到：</strong>{digest.missed.join("；")}
          </p>}
          {/* **数字要能翻回原文核，核不到就得说。**
              提示词里写着「每一个数都必须能在原文里找到」，那是承诺，这行是管它的人。
              2026-08-19 实测有一条写着「同业存放款项净增加 739.9 亿」，
              而它引的那一页写的是 7,383,004,563.78（73.83 亿）—— 差十倍，
              且那个数正是它论证「现金流不是主营回款」的唯一论据。
              页码、格式、语气全对，只有数是坏的：这类错最难自己发现。 */}
          {(digest.unverified?.length ?? 0) > 0 && <p className="doc-unreadable">
            <strong>这几个数没能在它标注的页里核到：</strong>
            {digest.unverified!.map((x) => x.where === "没有"
              ? `${x.value}（整份文件里都没有这个数）`
              : `${x.value}（在别的页上，页码标错了）`).join("；")}
            　核之前先别用。
          </p>}
        </div>
      : <p className="form-note">{digest.note}</p>)}

    {/* **募投进度：读文档的结果喂给甘特图。**
        只在这份文件看起来是募集资金专项报告、而且已经归到一家公司时才出现 ——
        一个按了没结果的按钮比没有按钮更糟。 */}
    {companyId && /募集资金|募投/.test(doc.title) && <Fund doc={doc} companyId={companyId} />}

    {/* 追问降到二级：给已经看完结果、想再挖一层的情况。 */}
    <details className="doc-followup">
      <summary>还想问点别的</summary>
      <Ask doc={doc} companyId={companyId} />
    </details>
  </div>;
}

/**
 * 结果的版式：**结论、数字、出处分成三层**，不是一堵墙。
 *
 * 上一版把模型的一整段 markdown 用 pre-wrap 渲染出来 —— 使用者的原话是
 * 「我受够了一堆文字」「没有组织、没有层级」。他说过不止一次。
 *
 * 现在：最该跟进的三条置顶（它们是这份结果唯一会改变行动的部分），
 * 下面一条清单项一张卡：**一句话结论**在上、**数字离开句子**在下、页码收成角标。
 *
 * 数字有两个去处：孤立的一个数排进网格，**成组的（同一科目多个年份、多个分部、
 * 多家可比公司）排成表**。后者是第二轮才补的 —— 第一轮只有网格，于是研报里的
 * 盈利预测被压成了「2023A 709 → 2024E 1536 → 2025E 2674」这样一串，
 * 每个数都对，**但谁都对不齐**，也就看不出增速是在哪一年掉下来的。
 *
 * 没找到的那几条折叠到最后 —— 它们要在（漏掉的那条最需要知道），但不该占版面。
 */
function DigestBoard({ digest, onRedo, busy }:
                     { digest: DocDigest; onRedo: () => void; busy: boolean }) {
  let body: DigestBody | null = null;
  try { body = JSON.parse(digest.digest) as DigestBody; } catch { body = null; }
  // **排不出层级时要说清楚为什么，别让人以为是分层坏了。**
  //
  // 换版式之前存下来的结果是一整段 markdown。原来这里把它原样打出来 ——
  // 于是使用者看到的是「一堵文字」，合理的结论是"你那个分层根本没生效"。
  // 而实际情况是：这份结果是分层这件事存在之前读的，库里就是一段文字，
  // 没有重读过它永远不会变。
  //
  // 两种原因分得开：`structured === false` 只有**这一次新读**才带，说明模型这次
  // 没输出成 JSON（多半是写太长被截断）；老结果从库里取出来没有这个字段。
  // 两种的解法都是重读一次，但**说错原因会让人去修错的东西**。
  if (!body?.items?.length) return <div className="digest-legacy">
    <p>{digest.structured === false
      ? <>这一次的输出<strong>没成形</strong>（多半是写太长被截断了），所以排不出分层。
        重读一次通常就好。</>
      : <>这份结果是<strong>旧版式</strong>读的（当时还没有分层和表格），存下来就是一段文字。
        重读一次就会变成分条、带表格的样子。</>}
    </p>
    <button className="page-action" type="button" disabled={busy} onClick={onRedo}>
      {busy ? "正在重读…" : "按新版式重读"}
    </button>
    <details><summary>看旧版式那段原文</summary>
      <div className="doc-digest-body">{digest.digest}</div>
    </details>
  </div>;

  const found = body.items.filter((item) => item.found !== false && item.verdict);
  const missing = body.items.filter((item) => item.found === false || !item.verdict);
  return <div className="digest">
    {(body.watch ?? []).length > 0 && <ol className="digest-watch">
      {(body.watch ?? []).map((row, i) => <li key={i}>
        <span>{rich(row.point)}</span><Pages pages={row.pages} />
      </li>)}
    </ol>}

    <div className="digest-cards">
      {found.map((item, i) => <Card key={i} item={item} />)}
    </div>

    {/* **没找到的要在，但不该占版面。** 一份缺了两条的结果和一份完整的结果
        看起来一模一样，而它们的价值完全不同。 */}
    {missing.length > 0 && <details className="digest-missing">
      <summary>这 {missing.length} 条在文件里没找到</summary>
      <ul>{missing.map((item, i) => <li key={i}>{item.title}</li>)}</ul>
    </details>}
  </div>;
}

function Pages({ pages }: { pages?: number[] }) {
  if (!pages?.length) return null;
  return <em className="digest-pages">第 {pages.join("、")} 页</em>;
}

function Card({ item }: { item: DigestItem }) {
  const tables = (item.tables ?? []).filter((table) => (table.rows ?? []).length > 0);
  return <article className="digest-card">
    <h6>{item.title}</h6>
    {/* 结论里的 `**…**` 要渲染出来 —— 模型偶尔会带，原样打出来就是两个星号。 */}
    <p>{rich(item.verdict)}</p>
    {/* 一个数一行：名字、数、口径三列。**口径要单独成一格** ——
        塞进数字那一格里，它就只有那一列的宽度，长一点就折成五行小字。 */}
    {(item.figures ?? []).length > 0 && <dl className="digest-figs">
      {(item.figures ?? []).map((fig, i) => <div key={i}>
        <dt>{fig.label}</dt>
        <dd>{fig.value}</dd>
        {fig.note && <dd className="digest-fig-note">{fig.note}</dd>}
      </div>)}
    </dl>}
    {tables.map((table, i) => <Table key={i} table={table} />)}
    <Pages pages={item.pages} />
  </article>;
}

/**
 * 成组的数字排成表。**数字右对齐、等宽字形**，不然这张表就没有意义 ——
 * 它存在的理由是让人一眼看出哪一列跳了，那要求同一位数上下对得齐。
 *
 * 第一列是行名（科目），永远左对齐；其余格子以数字打头的靠右。
 * 宽表自己横向滚，**不带着整页一起横滚**。
 */
function Table({ table }: { table: DigestTable }) {
  const grid = tableGrid(table);
  // 标题留在滚动区**外面**（长表横滚时它不该跟着划走），所以不能用 `<caption>` ——
  // 那就要自己把 `<table>` 指回标题，否则读屏念到这张表时没有标题。
  const captionId = useId();
  return <figure className="digest-table">
    {table.title && <figcaption id={captionId}>{table.title}</figcaption>}
    <div className="digest-table-scroll">
      <table aria-labelledby={table.title ? captionId : undefined}>
        <thead><tr>{grid.columns.map((head, i) =>
          <th key={i} scope="col" className={i === 0 ? "" : "num"}>{head}</th>)}</tr></thead>
        <tbody>{grid.rows.map((row, r) => <tr key={r}>
          {row.map((cell, c) => c === 0
            ? <th key={c} scope="row">{cell}</th>
            : <td key={c} className={numeric(cell) ? "num" : ""}>{cell}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
    {table.note && <p className="digest-table-note">{table.note}</p>}
  </figure>;
}

/** 把募投项目抽出来排进甘特图。 */
function Fund({ doc, companyId }: { doc: DocDetail; companyId: number }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");
  const [error, setError] = useState("");
  if (done) return <p className="form-note">{done}</p>;
  return <div className="doc-save">
    <span>这份报告里有募投项目表：</span>
    <button className="text-button" type="button" disabled={busy}
      onClick={() => void (async () => {
        setBusy(true); setError("");
        try {
          const got = await extractFundraising(doc.id, companyId);
          setDone(got.saved
            ? `抽出 ${got.saved} 个募投项目（出自第 ${got.pages.join("、")} 页），已排进上面的「还有哪些日子在等着」。本次 ${got.credits} 分。`
            : got.note || "没找到募投项目表。");
        } catch (caught) { setError(errorMessage(caught)); }
        finally { setBusy(false); }
      })()}>{busy ? "正在抽…" : "抽出来排进时间线"}</button>
    {error && <span className="form-error">{error}</span>}
  </div>;
}

/** 追问一份文件。 */
function Ask({ doc, companyId }: { doc: DocDetail; companyId?: number }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<DocAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [asked, setAsked] = useState(0);
  const [saved, setSaved] = useState("");

  async function ask() {
    setBusy(true); setError(""); setAnswer(null);
    try {
      setAnswer(await askDocument(doc.id, question, { followup: asked > 0 }));
      setAsked(asked + 1);
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  return <div className="doc-ask">
    <div className="doc-ask-row">
      <input type="text" placeholder="问这份文件一个具体问题，比如「前五大客户占多少」"
        value={question} disabled={busy}
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter" && question.trim().length > 1) void ask(); }} />
      {/* **一步，不是两步。** 原来是「先看看要几分」→ 再「问它」——
          使用者的原话：「毫无意义，你就直接启动就好了」。他是对的：
          一次问答两三分钱，为了两分钱让人多点一次、还多等一次检索，
          是把成本焦虑转嫁给了他。价钱在结果里如实报，够了。 */}
      <button className="page-action" type="button" disabled={busy || question.trim().length < 2}
        onClick={() => void ask()}>{busy ? "正在读…" : "问它"}</button>
    </div>
    {error && <p className="form-error">{error}</p>}
    {answer && <div className="doc-answer">
      {answer.pages.length === 0
        ? <p className="form-note">{answer.note}</p>
        : <>
          <p className="doc-answer-body">{answer.answer}</p>
          <p className="form-note">{answer.note}　本次 {answer.credits} 分。</p>
          {/* 引到的那几页原文摆在下面，**能当场核**，不用另开一个阅读器。 */}
          <details className="doc-sources">
            <summary>看这几页的原文（{answer.pages.join("、")} 页）</summary>
            {doc.pages.filter((page) => answer.pages.includes(page.page)).map((page) =>
              <div className="doc-source" key={page.page}>
                <h6>第 {page.page} 页 · {page.mode}</h6>
                <pre>{page.text.slice(0, 4000)}</pre>
              </div>)}
          </details>
          {/* **存成证据是这一页跟产品其他部分接上的地方。**
              读完就走的话，它只是一个孤立的问答框；存进档案，它才进了
              「主张 → 证据 → 复核」那条链子。出处写清楚是哪一份文件的哪几页 ——
              以后复盘时那句摘录要能翻回原文。 */}
          {companyId && (saved
            ? <p className="form-note">{saved}</p>
            : <div className="doc-save">
                <span>把这个回答存成证据：</span>
                {([["support", "支持"], ["counter", "反证"], ["neutral", "中性"]] as const)
                  .map(([polarity, label]) => <button key={polarity} className="text-button"
                    type="button" disabled={busy}
                    onClick={() => void (async () => {
                      setBusy(true); setError("");
                      try {
                        await createEvidence(companyId, {
                          source_name: `${doc.title} · 第 ${answer.pages.join("、")} 页`,
                          source_url: doc.url || undefined,
                          excerpt: `【问】${question}\n【答】${answer.answer}`.slice(0, 2000),
                          polarity: polarity as EvidencePolarity,
                          // **不是"已核对"。** 这是模型读出来的，页码在出处里，
                          // 核对那一步得他自己做 —— 替他标成已核对是这一页最不该干的事。
                          verification: "待核验",
                        });
                        setSaved(`已存成${label}证据（出处记了第 ${answer.pages.join("、")} 页），到「逻辑与证据」里看。`);
                      } catch (caught) { setError(errorMessage(caught)); }
                      finally { setBusy(false); }
                    })()}>{label}</button>)}
              </div>)}
        </>}
    </div>}
  </div>;
}
