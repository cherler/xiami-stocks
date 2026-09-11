import { ArrowRight, BookOpen, Building2, CheckCircle2, CircleAlert, Copy, Link2, Network, Pencil, Plus, Search, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import {
  addIndustryChainEdge,
  addIndustryChainNode,
  addIndustryChainPosition,
  addIndustryChainStage,
  createIndustryChain,
  deleteIndustryChainRecord,
  forkIndustryChain,
  getCompanies,
  getIndustryChain,
  getIndustryChainDraftJob,
  getIndustryChains,
  startIndustryChainDraft,
} from "../api";
import type {
  BackgroundJob,
  CompanyRecord,
  IndustryChainDraftResult,
  IndustryChainThemeSummary,
  IndustryChainView,
} from "../types";
import { confirmAction } from "../lib/confirm";
import { useSpendGuard } from "../lib/credits";

type RecordKind = "theme" | "stage" | "node" | "edge" | "position";

function messageOf(caught: unknown): string {
  return caught instanceof Error ? caught.message : "操作失败，请稍后重试。";
}

function formText(form: FormData, key: string): string {
  return String(form.get(key) ?? "").trim();
}

/**
 * 跨公司的产业链底图。
 *
 * 这不是力导向关系网：研究者真正要扫的是「价值如何一段一段交付」，所以固定用
 * 从左到右的阶段列。节点先归到产品/服务阶段，公司再钉到节点；这两个层级不能反过来。
 */
export function IndustryChainPage({ onOpenCompany }: { onOpenCompany: (id: number) => void }) {
  const [themes, setThemes] = useState<IndustryChainThemeSummary[]>([]);
  const [view, setView] = useState<IndustryChainView | null>(null);
  const [companies, setCompanies] = useState<CompanyRecord[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [themeCategory, setThemeCategory] = useState("推荐主题");
  const [themeQuery, setThemeQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [draftJob, setDraftJob] = useState<BackgroundJob | null>(null);
  const [addingStage, setAddingStage] = useState(false);
  const [addingNodeAt, setAddingNodeAt] = useState<number | null>(null);
  const [positioningNode, setPositioningNode] = useState<number | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const confirmSpend = useSpendGuard();
  const focusCompany = Number(new URLSearchParams(window.location.search).get("company") ?? "") || null;

  async function reloadThemes(preferId?: number) {
    const list = await getIndustryChains();
    setThemes(list);
    const nextId = preferId ?? activeId ?? list[0]?.id ?? null;
    setActiveId(nextId);
    if (nextId !== null) setView(await getIndustryChain(nextId));
    else setView(null);
  }

  useEffect(() => {
    let live = true;
    Promise.all([getIndustryChains(), getCompanies(), getIndustryChainDraftJob()]).then(async ([themeList, companyList, latestDraft]) => {
      if (!live) return;
      setThemes(themeList); setCompanies(companyList);
      setDraftJob(latestDraft);
      const fromUrl = Number(new URLSearchParams(window.location.search).get("theme") ?? "") || null;
      const first = fromUrl && themeList.some((item) => item.id === fromUrl) ? fromUrl : themeList[0]?.id ?? null;
      setActiveId(first);
      if (first !== null) setView(await getIndustryChain(first));
    }).catch((caught) => { if (live) setError(messageOf(caught)); });
    return () => { live = false; };
  }, []);

  const draftRunning = draftJob !== null && (draftJob.status === "运行中" || draftJob.status === "排队中");
  const draftResult = draftJob?.status === "已完成" && draftJob.result
    ? draftJob.result as unknown as IndustryChainDraftResult : null;

  useEffect(() => {
    if (!draftRunning) return;
    const timer = window.setInterval(() => {
      void getIndustryChainDraftJob().then(async (next) => {
        setDraftJob(next);
        if (next?.status === "已完成" && next.result) {
          const result = next.result as unknown as IndustryChainDraftResult;
          await reloadThemes(result.theme_id);
          setThemeCategory("我的主题"); setThemeQuery(""); setCreating(false); setDrafting(false);
        }
      }).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [draftRunning]);

  async function selectTheme(id: number) {
    setActiveId(id); setEditing(false); setError(""); setBusy("theme");
    try {
      setView(await getIndustryChain(id));
      const url = new URL(window.location.href);
      url.searchParams.set("theme", String(id));
      window.history.replaceState({}, "", `${url.pathname}${url.search}`);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(""); }
  }

  async function createTheme(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("create"); setError("");
    const form = new FormData(event.currentTarget);
    try {
      const next = await createIndustryChain({
        name: formText(form, "name"),
        chain_type: formText(form, "chain_type"),
        description: formText(form, "description"),
      });
      setThemeCategory("我的主题"); setThemeQuery("");
      setCreating(false); setEditing(true); setView(next); setActiveId(next.id);
      await reloadThemes(next.id);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(""); }
  }

  async function generateDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const topic = formText(new FormData(event.currentTarget), "topic");
    if (!topic) { setError("先写一个产品、服务或场景主题。"); return; }
    if (!(await confirmSpend("industry-chain-draft", `为「${topic}」检索公开资料并生成产业链初稿。`))) return;
    setBusy("draft"); setError("");
    try {
      setDraftJob(await startIndustryChainDraft(topic));
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(""); }
  }

  async function copyTheme() {
    if (!view) return;
    setBusy("fork"); setError("");
    try {
      const next = await forkIndustryChain(view.id);
      setThemeCategory("我的主题"); setThemeQuery(""); setEditing(true);
      setView(next); setActiveId(next.id);
      await reloadThemes(next.id);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(""); }
  }

  async function createStage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!view) return;
    setBusy("stage"); setError("");
    const form = new FormData(event.currentTarget);
    try {
      const next = await addIndustryChainStage(view.id, {
        name: formText(form, "name"), stage_kind: formText(form, "stage_kind"),
      });
      setView(next); setAddingStage(false); await reloadThemes(next.id);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(""); }
  }

  async function createNode(event: FormEvent<HTMLFormElement>, stageId: number) {
    event.preventDefault();
    if (!view) return;
    setBusy(`node-${stageId}`); setError("");
    const form = new FormData(event.currentTarget);
    const sourceName = formText(form, "source_name");
    const sourceUrl = formText(form, "source_url");
    try {
      const upstream = Number(formText(form, "upstream_node_id")) || null;
      const next = await addIndustryChainNode(view.id, {
        stage_id: stageId,
        name: formText(form, "name"),
        node_type: formText(form, "node_type"),
        description: formText(form, "description"),
        source_name: sourceName,
        source_url: sourceUrl,
        verification: sourceName && sourceUrl ? "已核验" : "待补证",
        upstream_node_id: upstream,
        relation_type: formText(form, "relation_type") || "流向",
      });
      setView(next); setAddingNodeAt(null); await reloadThemes(next.id);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(""); }
  }

  async function createPosition(event: FormEvent<HTMLFormElement>, nodeId: number) {
    event.preventDefault();
    if (!view) return;
    setBusy(`position-${nodeId}`); setError("");
    const form = new FormData(event.currentTarget);
    const sourceName = formText(form, "source_name");
    const sourceUrl = formText(form, "source_url");
    try {
      const next = await addIndustryChainPosition(view.id, {
        node_id: nodeId,
        company_id: Number(formText(form, "company_id")),
        role: formText(form, "role") || "参与者",
        detail: formText(form, "detail"),
        source_name: sourceName,
        source_url: sourceUrl,
        verification: sourceName && sourceUrl ? "已核验" : "待补证",
      });
      setView(next); setPositioningNode(null); await reloadThemes(next.id);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(""); }
  }

  async function createEdge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!view) return;
    setBusy("edge"); setError("");
    const form = new FormData(event.currentTarget);
    const sourceName = formText(form, "source_name");
    const sourceUrl = formText(form, "source_url");
    try {
      const next = await addIndustryChainEdge(view.id, {
        from_node_id: Number(formText(form, "from_node_id")),
        to_node_id: Number(formText(form, "to_node_id")),
        relation_type: formText(form, "relation_type") || "流向",
        detail: formText(form, "detail"), source_name: sourceName, source_url: sourceUrl,
        verification: sourceName && sourceUrl ? "已核验" : "待补证",
      });
      setView(next); setConnecting(false); await reloadThemes(next.id);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(""); }
  }

  async function remove(kind: RecordKind, id: number, label: string) {
    if (!(await confirmAction({
      title: `删除「${label}」？`,
      detail: "与它直接相连的底图记录也会一起删除。",
      confirmText: "删除", danger: true,
    }))) return;
    setBusy(`delete-${kind}-${id}`); setError("");
    try {
      await deleteIndustryChainRecord(kind, id);
      if (kind === "theme") await reloadThemes();
      else if (view) { setView(await getIndustryChain(view.id)); await reloadThemes(view.id); }
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(""); }
  }

  const nodes = useMemo(() => view?.stages.flatMap((stage) => stage.nodes) ?? [], [view]);
  const names = useMemo(() => new Map(nodes.map((node) => [node.id, node.name])), [nodes]);
  const incoming = useMemo(() => {
    const map = new Map<number, Array<{ id: number; from: string; relation: string; sourceName: string; sourceUrl: string; verification: string }>>();
    for (const edge of view?.edges ?? []) {
      const items = map.get(edge.to_node_id) ?? [];
      items.push({
        id: edge.id, from: names.get(edge.from_node_id) ?? "上一步", relation: edge.relation_type,
        sourceName: edge.source_name, sourceUrl: edge.source_url, verification: edge.verification,
      });
      map.set(edge.to_node_id, items);
    }
    return map;
  }, [view, names]);
  const themeCategories = useMemo(() => {
    const available = new Set(themes.map((theme) => theme.category));
    return ["推荐主题", "全部", "金融服务", "消费与食品", "数字科技", "新能源与制造", "材料与化工", "交通与物流", "我的主题"]
      .filter((category) => category === "推荐主题" || category === "全部" || available.has(category));
  }, [themes]);
  const visibleThemes = useMemo(() => {
    const query = themeQuery.trim().toLowerCase();
    const matched = themes.filter((theme) => {
      const matchesQuery = !query || `${theme.name} ${theme.description} ${theme.category}`.toLowerCase().includes(query);
      if (!matchesQuery) return false;
      if (query || themeCategory === "全部") return true;
      if (themeCategory === "推荐主题") return theme.recommended;
      return theme.category === themeCategory;
    });
    return !query && themeCategory === "推荐主题" ? matched.slice(0, 4) : matched;
  }, [themes, themeCategory, themeQuery]);

  return <div className="industry-chain-page">
    <section className="deck chain-deck" aria-labelledby="industry-chain-title">
      <div className="deck-head">
        <div>
          <span className="deck-kicker">PRODUCT · SERVICE · DELIVERY</span>
          <h1 id="industry-chain-title">产业链底图</h1>
          <p>系统已经整理好常用主题。选择一张，从左到右看产品怎样变成客户价值。</p>
        </div>
        <div className="chain-head-actions">
          {view?.is_default && <button className="chain-head-action chain-head-action--context" type="button" disabled={busy === "fork"}
                                    onClick={() => void copyTheme()}>
            <Copy size={14} /> {busy === "fork" ? "复制中…" : "复制后编辑"}
          </button>}
          {view && <button className={`chain-head-action chain-head-action--context${editing ? " is-active" : ""}`} type="button"
                           onClick={() => setEditing((value) => !value)}>
            <Pencil size={14} /> {editing ? "完成" : view.is_default ? "标注公司" : "编辑与标注"}
          </button>}
          {view && <span className="chain-head-divider" aria-hidden="true" />}
          <button className={`chain-head-action chain-head-action--generate${drafting ? " is-active" : ""}`} type="button" onClick={() => setDrafting((value) => !value)}>
            <Sparkles size={14} /> 从主题生成
          </button>
          <button className="chain-head-action chain-head-action--blank" type="button" onClick={() => setCreating((value) => !value)}>
            <Plus size={14} /> 从空白开始
          </button>
        </div>
      </div>

      {drafting && <form className="chain-draft-bar deck-rule" onSubmit={(event) => void generateDraft(event)}>
        <div className="chain-draft-copy">
          <span className="deck-kicker">RESEARCH DRAFT · SOURCED</span>
          <strong>输入主题，先得到一张可核验的初稿</strong>
          <span>系统会检索公开资料、整理产品与服务节点，并把每项标为待确认；不会凭印象把公司钉上去。</span>
        </div>
        <label>
          <span>研究主题</span>
          <input name="topic" required maxLength={80} placeholder="例如：具身智能、低空经济、AI 数据中心" autoFocus />
        </label>
        <button className="deck-generate-button" disabled={busy === "draft" || draftRunning}>
          <Sparkles size={15} /> {draftRunning ? "后台生成中…" : busy === "draft" ? "正在提交…" : "生成初稿"}
        </button>
        <button className="deck-link" type="button" onClick={() => setDrafting(false)}>收起</button>
        <p className="chain-draft-note"><BookOpen size={13} />约需一分钟。结果会保存在“我的主题”，切走页面也会继续。</p>
      </form>}

      {draftJob && draftRunning && <section className="chain-draft-progress deck-rule" aria-live="polite">
        <Sparkles size={17} /><div><strong>{draftJob.label}</strong><span>正在服务端检索与整理；你可以继续查看其他底图。</span></div>
      </section>}
      {draftJob?.status === "失败" && <section className="chain-draft-failed deck-rule" role="alert">
        <CircleAlert size={17} /><div><strong>这次没有生成初稿</strong><span>{draftJob.error || "公开资料或模型服务暂时不可用。"}</span></div>
        <button className="deck-link" type="button" onClick={() => setDrafting(true)}>换个主题重试</button>
      </section>}
      {draftResult && !draftRunning && <section className="chain-draft-result deck-rule">
        <CheckCircle2 size={17} /><div><strong>初稿已保存：{draftResult.theme_name}</strong><span>{draftResult.stages} 个阶段 · {draftResult.nodes} 个节点 · {draftResult.edges} 条关系 · {draftResult.sources} 条公开资料</span></div>
        <button className="deck-link" type="button" onClick={() => void selectTheme(draftResult.theme_id)}>打开初稿 <ArrowRight size={13} /></button>
        {draftResult.unknowns.length > 0 && <details><summary>仍待补的 {draftResult.unknowns.length} 个问题</summary><ul>{draftResult.unknowns.map((item) => <li key={item}>{item}</li>)}</ul></details>}
      </section>}

      {themes.length > 0 && <section className="chain-theme-browser deck-rule" aria-label="查找产业链主题">
        <div className="chain-theme-tools">
          <div className="chain-theme-search">
            <Search size={15} aria-hidden="true" />
            <input value={themeQuery} onChange={(event) => setThemeQuery(event.target.value)}
                   placeholder="搜索产业链、产品或场景" aria-label="搜索产业链主题" />
            {themeQuery && <button type="button" aria-label="清空搜索" onClick={() => setThemeQuery("")}><X size={13} /></button>}
          </div>
          <span>{themeQuery ? `找到 ${visibleThemes.length} 张底图` : themeCategory === "推荐主题" ? "研究池相关度最高的 4 张" : `${themeCategory} · ${visibleThemes.length} 张`}</span>
        </div>
        <div className="chain-theme-categories" role="tablist" aria-label="产业链分类">
          {themeCategories.map((category) => <button type="button" role="tab"
            aria-selected={!themeQuery && themeCategory === category}
            className={!themeQuery && themeCategory === category ? "is-active" : ""}
            key={category} onClick={() => { setThemeCategory(category); setThemeQuery(""); }}>
            {category}
            <small>{category === "推荐主题"
              ? Math.min(4, themes.filter((theme) => theme.recommended).length)
              : category === "全部" ? themes.length : themes.filter((theme) => theme.category === category).length}</small>
          </button>)}
        </div>
        <div className="chain-theme-shelf" role="tablist" aria-label={themeQuery ? "搜索结果" : themeCategory}>
          {visibleThemes.map((item) => <button type="button" role="tab" aria-selected={item.id === activeId}
            className={`chain-theme-tab${item.id === activeId ? " is-active" : ""}`}
            key={item.id} onClick={() => void selectTheme(item.id)}>
            <span>{item.recommended ? "为你推荐" : item.is_default ? item.category : "我的主题"}</span>
            <strong>{item.name}</strong>
            {item.recommended && item.recommendation_reason
              ? <em>{item.recommendation_reason}</em>
              : <em>{item.description}</em>}
            <small>{item.stage_count} 个阶段 · {item.node_count} 个节点</small>
          </button>)}
          {visibleThemes.length === 0 && <div className="chain-theme-no-result">
            <Search size={19} /><strong>没有匹配的底图</strong><span>换一个关键词，或从“全部”浏览。</span>
          </div>}
        </div>
      </section>}

      <div className="chain-read-guide">
        <span><b>1</b>切换主题</span><ArrowRight size={13} />
        <span><b>2</b>从左到右读</span><ArrowRight size={13} />
        <span><b>3</b>点来源核验；需要时再标注公司</span>
      </div>

      {creating && <form className="chain-create-bar deck-rule" onSubmit={(event) => void createTheme(event)}>
        <div className="chain-create-intro"><strong>建立自己的研究主题</strong><span>默认主题不会被覆盖；这里适合研究新的行业或产品。</span></div>
        <label>主题名称<input name="name" required placeholder="例如：AI 数据中心" /></label>
        <label>交付结构<select name="chain_type" defaultValue="制造链"><option>制造链</option><option>服务链</option><option>平台生态</option></select></label>
        <label className="chain-create-wide">研究范围<input name="description" placeholder="例如：从算力设备、供配电、液冷到云服务" /></label>
        <button className="page-action" disabled={busy === "create"}>{busy === "create" ? "创建中…" : "从空白开始"}</button>
        <button className="deck-link" type="button" onClick={() => setCreating(false)}>取消</button>
      </form>}

      {error && <p className="chain-error">{error}</p>}
      {!view && !creating && <div className="chain-empty deck-rule">
        <Network size={34} aria-hidden="true" />
        <strong>还没有产业链底图</strong>
        <span>默认主题没有加载出来。请刷新页面；仍无内容时再从空白主题开始。</span>
        <button className="page-action" onClick={() => void reloadThemes()}>重新加载默认底图</button>
      </div>}

      {view && <>
        <div className="chain-blueprint-meta deck-rule">
          <div className="chain-blueprint-title">
            <span className={view.is_default ? "is-system" : "is-personal"}>
              {view.is_default ? <><CheckCircle2 size={12} />系统底图</> : "我的主题"}
            </span>
            <strong>{view.name}</strong><i>{view.chain_type}</i>
            <em>{view.description || "尚未写研究边界"}</em>
          </div>
          <dl><div><dt>阶段</dt><dd>{view.stages.length}</dd></div><div><dt>节点</dt><dd>{view.node_count}</dd></div><div><dt>公司</dt><dd>{view.company_count}</dd></div></dl>
          {editing && !view.is_default && <div className="chain-blueprint-actions">
            {nodes.length > 1 && <button className="deck-link" onClick={() => setConnecting((value) => !value)}><Link2 size={13} />连接节点</button>}
            <button className="deck-link" onClick={() => setAddingStage((value) => !value)}><Plus size={13} />添加阶段</button>
            {!view.is_default && <button className="deck-link chain-delete-link" disabled={busy.startsWith("delete-theme")}
                    onClick={() => void remove("theme", view.id, view.name)}><Trash2 size={13} />删除底图</button>
            }
          </div>}
        </div>

        {editing && addingStage && <form className="chain-inline-form chain-stage-form" onSubmit={(event) => void createStage(event)}>
          <strong>添加阶段</strong><input name="name" required placeholder="阶段名称" />
          <select name="stage_kind" defaultValue="core"><option value="input">投入</option><option value="core">核心</option><option value="output">交付</option><option value="support">支撑</option></select>
          <button className="page-action page-action--small" disabled={busy === "stage"}>保存</button>
          <button type="button" className="icon-button" aria-label="取消" onClick={() => setAddingStage(false)}><X size={15} /></button>
        </form>}

        {editing && connecting && <form className="chain-inline-form chain-edge-form" onSubmit={(event) => void createEdge(event)}>
          <strong>连接已有节点</strong>
          <select name="from_node_id" required defaultValue=""><option value="" disabled>从这里</option>{nodes.map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</select>
          <ArrowRight size={15} aria-hidden="true" />
          <select name="to_node_id" required defaultValue=""><option value="" disabled>流向这里</option>{nodes.map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</select>
          <input name="relation_type" defaultValue="流向" aria-label="关系类型" />
          <input name="source_name" placeholder="来源名称" aria-label="来源名称" />
          <input name="source_url" type="url" placeholder="来源链接" aria-label="来源链接" />
          <button className="page-action page-action--small" disabled={busy === "edge"}>连接</button>
          <button type="button" className="icon-button" aria-label="取消" onClick={() => setConnecting(false)}><X size={15} /></button>
        </form>}

        <div className="chain-blueprint" style={{ gridTemplateColumns: `repeat(${Math.max(view.stages.length, 1)}, minmax(230px, 1fr))` }}>
          {view.stages.map((stage, stageIndex) => <section className={`chain-stage chain-stage--${stage.stage_kind}`} key={stage.id}>
            <header className="chain-stage-head">
              {stageIndex > 0 && <span className="chain-stage-flow"><ArrowRight size={15} /></span>}
              <div><small>{String(stageIndex + 1).padStart(2, "0")}</small><strong>{stage.name}</strong></div>
              {editing && !view.is_default && <button className="icon-button" aria-label={`删除${stage.name}`} onClick={() => void remove("stage", stage.id, stage.name)}><Trash2 size={13} /></button>}
            </header>
            <div className="chain-stage-nodes">
              {stage.nodes.map((node) => <article className={`industry-node${node.positions.some((position) => position.company_id === focusCompany) ? " industry-node--focused" : ""}`} key={node.id}>
                {(incoming.get(node.id)?.length ?? 0) > 0 && <div className="industry-node-inputs">
                  {incoming.get(node.id)?.map((edge) => <span key={edge.id}>
                    {edge.from}<i>{edge.relation}</i>
                    {edge.sourceUrl && <a href={edge.sourceUrl} target="_blank" rel="noreferrer"
                      aria-label={`查看“${edge.from} ${edge.relation} ${node.name}”的来源：${edge.sourceName || "公开资料"}`}>
                      <Link2 size={10} />
                    </a>}
                  </span>)}
                </div>}
                <div className="industry-node-head"><span>{node.node_type}</span><strong>{node.name}</strong>
                  {editing && !view.is_default && <button className="icon-button" aria-label={`删除${node.name}`} onClick={() => void remove("node", node.id, node.name)}><X size={13} /></button>}
                </div>
                {node.description && <p>{node.description}</p>}
                <div className="industry-node-proof">
                  <span className={node.verification === "已核验" ? "is-verified" : "is-draft"}>{node.verification === "待确认" ? "有来源 · 待确认" : node.verification}</span>
                  {node.source_url
                    ? <a href={node.source_url} target="_blank" rel="noreferrer"><Link2 size={11} />{node.source_name || "查看来源"}</a>
                    : <em>{node.source_name || "尚未挂来源"}</em>}
                </div>
                {node.positions.length > 0 && <div className="chain-company-pins">
                  {node.positions.map((position) => <span className={position.verification === "已核验" ? "is-verified" : "is-draft"} key={position.id}>
                    <button onClick={() => onOpenCompany(position.company_id)}><Building2 size={12} />{position.company_name}<em>{position.role}</em></button>
                    {editing && <button className="chain-pin-remove" aria-label={`移除${position.company_name}的定位`}
                            onClick={() => void remove("position", position.id, `${position.company_name} · ${node.name}`)}><X size={11} /></button>
                    }
                  </span>)}
                </div>}
                {editing && <button className="chain-node-add" onClick={() => setPositioningNode(positioningNode === node.id ? null : node.id)}><Plus size={12} />标注研究池公司</button>}
                {editing && positioningNode === node.id && <form className="chain-node-form" onSubmit={(event) => void createPosition(event, node.id)}>
                  <select name="company_id" required defaultValue=""><option value="" disabled>选择研究池公司</option>{companies.map((company) => <option value={company.id} key={company.id}>{company.name} · {company.symbol}</option>)}</select>
                  <input name="role" required defaultValue="参与者" placeholder="角色，例如产品提供方" />
                  <input name="detail" placeholder="业务证据摘要（可选）" />
                  <input name="source_name" placeholder="来源名称" />
                  <input name="source_url" type="url" placeholder="来源链接" />
                  <button className="page-action page-action--small" disabled={busy === `position-${node.id}`}>保存定位</button>
                </form>}
              </article>)}
              {stage.nodes.length === 0 && <div className="chain-stage-empty">还没有产品或服务节点</div>}
            </div>
            {editing && !view.is_default && <button className="chain-stage-add" onClick={() => setAddingNodeAt(addingNodeAt === stage.id ? null : stage.id)}><Plus size={13} />补充节点</button>}
            {editing && !view.is_default && addingNodeAt === stage.id && <form className="chain-node-form chain-node-form--new" onSubmit={(event) => void createNode(event, stage.id)}>
              <div className="chain-node-form-line"><input name="name" required placeholder="产品、服务或关键环节" /><select name="node_type" defaultValue="产品"><option>产品</option><option>服务</option><option>原材料</option><option>部件</option><option>设备</option><option>渠道</option><option>应用</option></select></div>
              <input name="description" placeholder="这一节点创造或交付什么价值" />
              {nodes.length > 0 && <div className="chain-node-form-line"><select name="upstream_node_id" defaultValue=""><option value="">暂不连接上一步</option>{nodes.filter((node) => node.stage_id !== stage.id).map((node) => <option value={node.id} key={node.id}>{node.name}</option>)}</select><input name="relation_type" defaultValue="流向" placeholder="关系" /></div>}
              <input name="source_name" placeholder="来源名称（年报、公告、官网等）" />
              <input name="source_url" type="url" placeholder="来源链接" />
              <button className="page-action page-action--small" disabled={busy === `node-${stage.id}`}>{busy === `node-${stage.id}` ? "保存中…" : "保存节点"}</button>
            </form>}
          </section>)}
        </div>
        <div className="chain-source-note"><BookOpen size={15} /><span><strong>怎么判断可信度：</strong>绿色“已核验”表示节点结构有公开资料依据；公司位置仍要单独挂年报、公告或官网来源。</span></div>
        <p className="chain-boundary">{view.boundary}</p>
      </>}
    </section>
  </div>;
}
