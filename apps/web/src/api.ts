import { apiUrl } from "./config";
import type { DigestTable } from "./lib/digest";
import type {
  ChainCompareView,
  BackupManifest,
  CreditState,
  DecisionBoard,
  InboxLearning,
  PortfolioUpdateInput,
  BackupRestoreResult,
  CompanyDetail,
  CompanyFromQuoteInput,
  CompanyInput,
  CompanyProfileRefreshResult,
  CompanyRecord,
  UniverseMatch,
  DataProviderStatus,
  DashboardSummary,
  EvidenceInput,
  EvidenceRecord,
  InboxActionResult,
  InboxArchiveInput,
  InboxClassifyResult,
  InboxTidyResult,
  BackgroundJob,
  DailyBriefing,
  NewsFeed,
  NewsPage,
  ResearchReport,
  SupplyChainView,
  IndustryChainThemeSummary,
  IndustryChainView,
  CompanyIndustryChainPositions,
  UniverseRederiveResult,
  ThesisMethod,
  ThesisMethodLibrary,
  InboxItem,
  InboxPage,
  FinancialRefreshResult,
  ResearchEventInput,
  ResearchEventRecord,
  ThesisInput,
  ThesisRecord,
  ThesisStatus,
  LocalDataSummary,
  MarketHistoryRefreshResult,
  RecordRevision,
  ReviewAttribution,
  ReviewQueueItem,
  SyncJobStatus,
  SyncJobUpdateInput,
  SyncRunRecord,
  SyncRunResult,
  ThesisReviewContext,
  ThesisReviewInput,
  ThesisUpdateInput,
  TradeUpdateInput,
  ValuationRefreshResult,
  CompanyPatch,
  AiPickOptions,
  HeatmapView,
  MarketFundFlowView,
  MarketLensStatus,
  IndustryComparison,
  IndustrySummary,
  ResearchTaskRecord,
  ScreenAdHocInput,
  ScreenField,
  ScreenResult,
  ScreenStrategy,
  ScreenStrategySaveInput,
  UniverseSummary,
  WatchGroupSummary,
  WatchlistImportInput,
  WatchlistImportResult,
  PortfolioDetail,
  PortfolioInput,
  PortfolioSummary,
  QuotePreview,
  TradeInput,
  TradeRecord,
} from "./types";

export class ApiError extends Error {}

/** 表单字段名 → 界面上的说法，让校验错误能直接对上用户看到的输入框。 */
const FIELD_LABELS: Record<string, string> = {
  rationale: "当时的理由",
  expectation: "当时的预期与证伪条件",
  shares: "股数",
  price: "成交价",
  fee: "费用合计",
  trade_date: "成交日期",
  review_due: "下次复核",
  company_id: "公司",
  thesis_id: "关联投资逻辑",
  claim: "主张",
  counter_condition: "反证条件",
  next_review_trigger: "复核触发条件",
  note: "说明",
  excerpt: "摘录",
  title: "标题",
  source_name: "来源名称",
  source_url: "来源链接",
  symbol: "证券代码",
  name: "名称",
  industry: "行业",
  verdict: "复核结论",
};

interface ValidationDetail {
  loc?: Array<string | number>;
  msg?: string;
  type?: string;
  ctx?: Record<string, unknown>;
}

function describeValidation(item: ValidationDetail): string {
  const field = (item.loc ?? []).filter((part) => typeof part === "string" && part !== "body").pop();
  const label = typeof field === "string" ? FIELD_LABELS[field] ?? field : "提交内容";
  const limit = item.ctx?.min_length ?? item.ctx?.max_length ?? item.ctx?.gt ?? item.ctx?.ge;
  switch (item.type) {
    case "string_too_short":
      return `${label}至少需要 ${limit} 个字符`;
    case "string_too_long":
      return `${label}最多 ${limit} 个字符`;
    case "missing":
      return `${label}不能为空`;
    case "greater_than":
      return `${label}必须大于 ${limit}`;
    case "greater_than_equal":
      return `${label}不能小于 ${limit}`;
    case "int_parsing":
    case "float_parsing":
      return `${label}需要填数字`;
    case "date_from_datetime_parsing":
    case "date_parsing":
      return `${label}的日期格式不正确`;
    default:
      return `${label}：${item.msg ?? "填写有误"}`;
  }
}

/** FastAPI 的 detail 可能是一句话，也可能是一组校验错误；两种都要变成人能读的文字。 */
export function describeError(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => describeValidation(item as ValidationDetail)).filter(Boolean);
    if (messages.length > 0) return messages.join("；");
  }
  return `请求失败（${status}）`;
}

/**
 * 被网关拦下时说的话。**跟"后端报错"是两回事，能做的事也不一样。**
 *
 * 后端的错误一律带 `{"detail": ...}`；拿不到 JSON 就说明请求没走到它那儿。
 * 最常见的一种是内容里带了像 XSS 的片段（`<script>`、`onerror=`），
 * 被前面那层按攻击特征挡掉 —— 这时候重试没有意义，改写内容才有。
 */
function blockedByGateway(status: number): string {
  return `这次请求被前面的网关挡下了（${status}），没有到后端。`
    + `多半是内容里有被当成攻击特征的片段（比如 <script>、onerror=）——`
    + `把那一段改写一下再存。`;
}

/**
 * 后端没应答时说的话。**开发和线上要说不同的话**，因为能做的事不一样：
 * 本地是"你还没把它起起来"，线上是"服务出问题了，不是你的操作有错"。
 */
function unreachable(status: number): string {
  return import.meta.env.DEV
    ? `看股的后端没有应答（网关回了 ${status}）——多半是它没在跑。`
      + `在 xiamimate-stock-lab 目录下执行 npm run dev:api，或者 npm run dev 一次起全套。`
    : `看股的服务暂时没有应答（${status}），过一会儿再试。这不是你这一步操作的问题。`;
}

import { isModelCall, timeoutFor } from "./lib/timeouts";


async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  // 调用方自己传了 signal 就尊重它（组件卸载时取消），否则挂一个超时的。
  // **两者不能互相覆盖**：传了 signal 又被超时掐掉，取消原因就说不清了。
  const budget = timeoutFor(path, options?.method ?? "GET");
  const signal = options?.signal ?? AbortSignal.timeout(budget);
  let response: Response;
  try {
    // **展开顺序有讲究**：`...options` 要在最前面。原来它排在 headers 后面，
    // 而 options 里若带 headers，整个合并好的头会被它顶掉（Content-Type 一起没）。
    // signal 放最后，保证超时那一个不会被 options 里的 undefined 覆盖掉。
    //
    // **调用方不要再传自己的 content-type。** 这里已经设了 `Content-Type`，
    // 调用方再传一个小写的 `content-type`，在 JS 对象里是**两个不同的键**，
    // 都会进 Headers，然后被合并成 `application/json, application/json` ——
    // Starlette 认不出这是 JSON，于是整个 body 原样当字符串交给 pydantic，
    // 回一个 `model_attributes_type` 的 422。
    //
    // 实测栽了四处：saveSettings（偏好存不进去）、updatePortfolio（改不了组合名）、
    // createTradesBatch（交割单确认入账）、purgeCompanyTrades（清流水）。
    // 四个都是**静默失败**：请求发出去了、后端回了 422、页面上什么也没变。
    // 判据见 apps/web/src/lib/apiheaders.test.ts。
    response = await fetch(apiUrl(path), {
      ...options,
      headers: { "Content-Type": "application/json", Accept: "application/json", ...options?.headers },
      signal,
    });
  } catch (error) {
    // 超时和主动取消都会走到这里，但它们对用户的意思完全不同：
    // 前者要说「这次没成」，后者是他自己离开了这一页，不该弹错。
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new ApiError(`请求超时（超过 ${Math.round(budget / 1000)} 秒没有响应），稍后再试。`);
    }
    throw error;
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    // **不是 JSON 的错误响应，一定不是本仓后端发的。**
    //
    // FastAPI 任何一种错误都回 `{"detail": ...}`。所以一个 5xx 配一段纯文本
    // （Next 的 rewrite 上游连不上时就是这样，正文只有 "Internal Server Error"）
    // 说明请求根本没走到后端，是中间那层代理在回话。
    //
    // 这两件事对使用者的意思完全相反：一个是"它算错了、可以重试"，
    // 一个是"它没起来、重试一万次也一样"。而原来两种都显示「请求失败（500）」，
    // 于是本地开发时第一反应永远是去翻后端日志 —— 那里什么都没有，因为它没在跑。
    if (payload === null && response.status >= 500) {
      throw new ApiError(unreachable(response.status));
    }
    // **4xx + 不是 JSON = 请求没走到后端，被前面的网关拦下了。**
    //
    // 后端任何一种错误都回 `{"detail": ...}`，所以拿不到 JSON 就说明这一层
    // 根本不是它。2026-08-19 实测：判断正文里写
    // `<img src=x onerror=alert(1)>` 或 `<script>alert(2)</script>`，
    // 网关回 403 + 一整页 HTML —— 而用户看到的是「请求失败（403）」。
    //
    // 那个裸状态码把人指向了错误的方向：它看起来像"没权限"，
    // 实际是"你写的内容里有被当成攻击特征的片段"，而且重试一万次都一样。
    if (payload === null && response.status >= 400) {
      throw new ApiError(blockedByGateway(response.status));
    }
    throw new ApiError(describeError(payload?.detail, response.status));
  }
  // **花过钱的调用要通知顶栏刷新余额。**
  //
  // 主站定了这个约定（xiamimate-tools-frontend/lib/api.ts）：AI 调用成功后
  // 派一个 `xm-credits-changed`，页眉的积分胶囊听到就重新拉余额。
  // 而 stock-lab 是独立前端，**从来没发过这个事件** —— 于是扣完分之后
  // 顶栏还显示旧数，要用户自己去点一下才刷新。使用者原话：「消费积分没有很快响应」。
  //
  // 只在**会花钱的那些路径**上发（isModelCall 就是模型调用那一批），
  // 而且只在成功时发：失败没扣钱，发了等于让人白白看一次跳动。
  if (typeof window !== "undefined" && isModelCall(path, options?.method ?? "GET")) {
    window.dispatchEvent(new CustomEvent("xm-credits-changed"));
  }
  // 204 没有 body，直接 .json() 会抛「Unexpected end of JSON input」——
  // 后端删干净了，前端却报错，用户看到的是「删不掉」。
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function getDashboard(): Promise<DashboardSummary> {
  return apiFetch<DashboardSummary>("/api/v1/dashboard");
}

/**
 * 同步行情。**返回一个后台任务，不是结果。**
 *
 * 这活要跑 25 秒到几分钟（底座是全市场 5544 只），占不住一个 HTTP 请求 ——
 * 详见后端 post_market_refresh 的说明。进度用 getJob("market_refresh", 0) 拉。
 */
export function refreshMarket(): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>("/api/v1/market/refresh", { method: "POST" });
}

export function getCompanies(query?: string): Promise<CompanyRecord[]> {
  const suffix = query?.trim() ? `?query=${encodeURIComponent(query.trim())}` : "";
  return apiFetch<CompanyRecord[]>(`/api/v1/companies${suffix}`);
}

/** 在**全市场**里按名称或代码找公司，附带"你建过档没有"。本地一条 SQL，不计费。 */
export function lookupUniverse(query: string, limit = 8): Promise<UniverseMatch[]> {
  const q = query.trim();
  if (!q) return Promise.resolve([]);
  return apiFetch<UniverseMatch[]>(`/api/v1/universe/lookup?q=${encodeURIComponent(q)}&limit=${limit}`);
}

export function getCompany(companyId: number): Promise<CompanyDetail> {
  return apiFetch<CompanyDetail>(`/api/v1/companies/${companyId}`);
}

export function createCompany(payload: CompanyInput): Promise<CompanyDetail> {
  return apiFetch<CompanyDetail>("/api/v1/companies", { method: "POST", body: JSON.stringify(payload) });
}

export function getQuotePreview(symbol: string): Promise<QuotePreview> {
  return apiFetch<QuotePreview>(`/api/v1/quotes/resolve?symbol=${encodeURIComponent(symbol.trim())}`);
}

export function createCompanyFromQuote(payload: CompanyFromQuoteInput): Promise<CompanyDetail> {
  return apiFetch<CompanyDetail>("/api/v1/companies/from-quote", { method: "POST", body: JSON.stringify(payload) });
}

export function getDataProviders(): Promise<DataProviderStatus[]> {
  return apiFetch<DataProviderStatus[]>("/api/v1/data-providers");
}

export function refreshCompanyMarketHistory(companyId: number): Promise<MarketHistoryRefreshResult> {
  return apiFetch<MarketHistoryRefreshResult>(`/api/v1/companies/${companyId}/market-history/refresh`, { method: "POST" });
}

export function refreshCompanyProfile(companyId: number): Promise<CompanyProfileRefreshResult> {
  return apiFetch<CompanyProfileRefreshResult>(`/api/v1/companies/${companyId}/profile/refresh`, { method: "POST" });
}

export function refreshCompanyValuation(companyId: number): Promise<ValuationRefreshResult> {
  return apiFetch<ValuationRefreshResult>(`/api/v1/companies/${companyId}/valuation/refresh`, { method: "POST" });
}

export function refreshCompanyFinancials(companyId: number): Promise<FinancialRefreshResult> {
  return apiFetch<FinancialRefreshResult>(`/api/v1/companies/${companyId}/financials/refresh`, { method: "POST" });
}

export function createThesis(companyId: number, payload: ThesisInput): Promise<ThesisRecord> {
  return apiFetch<ThesisRecord>(`/api/v1/companies/${companyId}/theses`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateThesis(thesisId: number, status: ThesisStatus): Promise<ThesisRecord> {
  return apiFetch<ThesisRecord>(`/api/v1/theses/${thesisId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function reviseThesis(thesisId: number, payload: ThesisUpdateInput): Promise<ThesisRecord> {
  return apiFetch<ThesisRecord>(`/api/v1/theses/${thesisId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function getRevisions(entity: "theses" | "trades", entityId: number): Promise<RecordRevision[]> {
  return apiFetch<RecordRevision[]>(`/api/v1/${entity}/${entityId}/revisions`);
}

export function createEvidence(companyId: number, payload: EvidenceInput): Promise<EvidenceRecord> {
  return apiFetch<EvidenceRecord>(`/api/v1/companies/${companyId}/evidences`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createResearchEvent(companyId: number, payload: ResearchEventInput): Promise<ResearchEventRecord> {
  return apiFetch<ResearchEventRecord>(`/api/v1/companies/${companyId}/events`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateResearchEvent(eventId: number, verification: string): Promise<ResearchEventRecord> {
  return apiFetch<ResearchEventRecord>(`/api/v1/events/${eventId}`, {
    method: "PATCH",
    body: JSON.stringify({ verification }),
  });
}

export function getPortfolios(): Promise<PortfolioSummary[]> {
  return apiFetch<PortfolioSummary[]>("/api/v1/portfolios");
}

export function getPortfolio(portfolioId: number): Promise<PortfolioDetail> {
  return apiFetch<PortfolioDetail>(`/api/v1/portfolios/${portfolioId}`);
}

export function createPortfolio(payload: PortfolioInput): Promise<PortfolioSummary> {
  return apiFetch<PortfolioSummary>("/api/v1/portfolios", { method: "POST", body: JSON.stringify(payload) });
}

export function createTrade(portfolioId: number, payload: TradeInput): Promise<TradeRecord> {
  return apiFetch<TradeRecord>(`/api/v1/portfolios/${portfolioId}/trades`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateTradeReview(tradeId: number, reviewDue: string | null): Promise<TradeRecord> {
  return apiFetch<TradeRecord>(`/api/v1/trades/${tradeId}`, {
    method: "PATCH",
    body: JSON.stringify({ review_due: reviewDue }),
  });
}

export function reviseTrade(tradeId: number, payload: TradeUpdateInput): Promise<TradeRecord> {
  return apiFetch<TradeRecord>(`/api/v1/trades/${tradeId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function getLocalData(): Promise<LocalDataSummary> {
  return apiFetch<LocalDataSummary>("/api/v1/local-data");
}

export function getBackups(): Promise<BackupManifest[]> {
  return apiFetch<BackupManifest[]>("/api/v1/backups");
}

export function createBackup(note: string): Promise<BackupManifest> {
  return apiFetch<BackupManifest>("/api/v1/backups", { method: "POST", body: JSON.stringify({ note }) });
}

export function restoreBackup(name: string): Promise<BackupRestoreResult> {
  return apiFetch<BackupRestoreResult>(`/api/v1/backups/${encodeURIComponent(name)}/restore`, { method: "POST" });
}

export function getInbox(status = "待核验", days = 90, limit = 40, relevance?: string): Promise<InboxPage> {
  const suffix = relevance ? `&relevance=${encodeURIComponent(relevance)}` : "";
  return apiFetch<InboxPage>(`/api/v1/inbox?status=${encodeURIComponent(status)}&days=${days}&limit=${limit}${suffix}`);
}

export function classifyInbox(useAi = true, limit = 400): Promise<InboxClassifyResult> {
  return apiFetch<InboxClassifyResult>(`/api/v1/inbox/classify?limit=${limit}&use_ai=${useAi}`, { method: "POST" });
}

export function archiveInboxBatch(relevance = "高", days = 90): Promise<{ archived: number; failed: number; note: string }> {
  return apiFetch(`/api/v1/inbox/archive-batch?relevance=${encodeURIComponent(relevance)}&days=${days}`, { method: "POST" });
}

export function ignoreInboxByRelevance(relevance = "低"): Promise<{ ignored: number }> {
  return apiFetch<{ ignored: number }>(`/api/v1/inbox/ignore-by-relevance?relevance=${encodeURIComponent(relevance)}`, { method: "POST" });
}

export function archiveInboxItem(itemId: number, payload: InboxArchiveInput): Promise<InboxActionResult> {
  return apiFetch<InboxActionResult>(`/api/v1/inbox/${itemId}/archive`, { method: "POST", body: JSON.stringify(payload) });
}

export function ignoreInboxItem(itemId: number): Promise<InboxItem> {
  return apiFetch<InboxItem>(`/api/v1/inbox/${itemId}/ignore`, { method: "POST" });
}

/** 误忽略了拿回来。**接口一直都在，前端从来没调过** —— 忽略原来是个单向门。 */
export function reopenInboxItem(itemId: number): Promise<InboxItem> {
  return apiFetch<InboxItem>(`/api/v1/inbox/${itemId}/reopen`, { method: "POST" });
}

export function getSyncJobs(): Promise<SyncJobStatus[]> {
  return apiFetch<SyncJobStatus[]>("/api/v1/sync/jobs");
}

export function updateSyncJob(jobId: string, payload: SyncJobUpdateInput): Promise<SyncJobStatus> {
  return apiFetch<SyncJobStatus>(`/api/v1/sync/jobs/${jobId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function runSyncJob(jobId: string): Promise<SyncRunResult> {
  return apiFetch<SyncRunResult>(`/api/v1/sync/jobs/${jobId}/run`, { method: "POST" });
}

export function getSyncRuns(limit = 20): Promise<SyncRunRecord[]> {
  return apiFetch<SyncRunRecord[]>(`/api/v1/sync/runs?limit=${limit}`);
}

export function getReviewQueue(): Promise<ReviewQueueItem[]> {
  return apiFetch<ReviewQueueItem[]>("/api/v1/reviews/queue");
}

export function getReviewAttribution(quarters = 4): Promise<ReviewAttribution> {
  return apiFetch<ReviewAttribution>(`/api/v1/reviews/attribution?quarters=${quarters}`);
}

export function getReviewContext(thesisId: number): Promise<ThesisReviewContext> {
  return apiFetch<ThesisReviewContext>(`/api/v1/theses/${thesisId}/review-context`);
}

export function createThesisReview(thesisId: number, payload: ThesisReviewInput): Promise<ThesisReviewContext> {
  return apiFetch<ThesisReviewContext>(`/api/v1/theses/${thesisId}/reviews`, { method: "POST", body: JSON.stringify(payload) });
}

export function getWatchGroups(): Promise<WatchGroupSummary[]> {
  return apiFetch<WatchGroupSummary[]>("/api/v1/companies/groups");
}

export function updateCompany(companyId: number, payload: CompanyPatch): Promise<CompanyDetail> {
  return apiFetch<CompanyDetail>(`/api/v1/companies/${companyId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function importWatchlist(payload: WatchlistImportInput): Promise<WatchlistImportResult> {
  return apiFetch<WatchlistImportResult>("/api/v1/companies/import", { method: "POST", body: JSON.stringify(payload) });
}

export function getIndustries(): Promise<IndustrySummary[]> {
  return apiFetch<IndustrySummary[]>("/api/v1/industries");
}

export function getIndustryComparison(industry: string): Promise<IndustryComparison> {
  return apiFetch<IndustryComparison>(`/api/v1/industries/comparison?industry=${encodeURIComponent(industry)}`);
}

export function getUniverseSummary(): Promise<UniverseSummary> {
  return apiFetch<UniverseSummary>("/api/v1/universe/summary");
}

export function getScreenStrategies(): Promise<ScreenStrategy[]> {
  return apiFetch<ScreenStrategy[]>("/api/v1/screen/strategies");
}

/** 跑一套规则。
 *
 * `sort` 是**只影响这一次查看**的覆盖，不写回策略——规则属于策略，
 * 排序和条数属于「你现在想怎么看」。原来两者绑在一起，想换个排法就得
 * 进「调整条件」改策略再保存，把策略库弄脏，于是实际上没人换。 */
export function runScreen(
  strategy: string,
  limit = 30,
  sort?: { field?: string; desc?: boolean },
): Promise<ScreenResult> {
  const query = new URLSearchParams({ strategy, limit: String(limit) });
  if (sort?.field) query.set("sort_field", sort.field);
  if (sort?.desc !== undefined) query.set("sort_desc", String(sort.desc));
  return apiFetch<ScreenResult>(`/api/v1/screen/run?${query}`, { method: "POST" });
}

export function getScreenFields(): Promise<ScreenField[]> {
  return apiFetch<ScreenField[]>("/api/v1/screen/fields");
}

export function previewScreen(payload: ScreenAdHocInput, limit = 30): Promise<ScreenResult> {
  return apiFetch<ScreenResult>(`/api/v1/screen/run?limit=${limit}`, { method: "POST", body: JSON.stringify(payload) });
}

export function saveScreenStrategy(payload: ScreenStrategySaveInput): Promise<ScreenStrategy> {
  return apiFetch<ScreenStrategy>("/api/v1/screen/strategies", { method: "POST", body: JSON.stringify(payload) });
}

export function deleteScreenStrategy(key: string): Promise<void> {
  return apiFetch<void>(`/api/v1/screen/strategies/${encodeURIComponent(key)}`, { method: "DELETE" });
}

/* ── AI 选股 ─────────────────────────────────────────────────────────
 * 一句话 → 模型翻成条件 → 代码在全 A 上筛 → 模型从命中里挑。
 * 两次模型调用 + 可能的联网，跑一分钟量级，所以进后台：
 * 绑在浏览器这一次请求上，等于「切走就白花钱」。 */

export function getAiPickOptions(): Promise<AiPickOptions> {
  return apiFetch<AiPickOptions>("/api/v1/screen/ai-pick/options");
}

export function startAiPick(question: string, web: boolean): Promise<BackgroundJob> {
  const query = new URLSearchParams({ question, web: String(web) });
  return apiFetch<BackgroundJob>(`/api/v1/screen/ai-pick?${query}`, { method: "POST" });
}

export function getAiPickStatus(): Promise<BackgroundJob | null> {
  return apiFetch<BackgroundJob | null>("/api/v1/screen/ai-pick/status");
}

export function getHeatmap(scope = "all", metric = "roe", limit = 60): Promise<HeatmapView> {
  return apiFetch<HeatmapView>(`/api/v1/heatmap?scope=${encodeURIComponent(scope)}&metric=${encodeURIComponent(metric)}&limit=${limit}`);
}

export function getMarketLensStatuses(): Promise<MarketLensStatus[]> {
  return apiFetch<MarketLensStatus[]>("/api/v1/market/lenses");
}

export function getMarketFundFlow(): Promise<MarketFundFlowView> {
  return apiFetch<MarketFundFlowView>("/api/v1/market/fund-flow");
}

export function getResearchTasks(limit = 20): Promise<ResearchTaskRecord[]> {
  return apiFetch<ResearchTaskRecord[]>(`/api/v1/tasks?limit=${limit}`);
}

export function createResearchTask(payload: { title: string; strategy_key: string; symbols?: string[]; due_date?: string | null; limit?: number }): Promise<ResearchTaskRecord> {
  return apiFetch<ResearchTaskRecord>("/api/v1/tasks", { method: "POST", body: JSON.stringify(payload) });
}

export function updateResearchTask(taskId: number, payload: { status?: string; conclusion?: string; due_date?: string | null }): Promise<ResearchTaskRecord> {
  return apiFetch<ResearchTaskRecord>(`/api/v1/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteResearchTask(taskId: number): Promise<void> {
  return apiFetch<void>(`/api/v1/tasks/${taskId}`, { method: "DELETE" });
}

export function updateTaskItem(itemId: number, payload: { status?: string; note?: string }): Promise<ResearchTaskRecord> {
  return apiFetch<ResearchTaskRecord>(`/api/v1/tasks/items/${itemId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function getMethodLibrary(): Promise<ThesisMethodLibrary> {
  return apiFetch<ThesisMethodLibrary>("/api/v1/methods");
}

export function getMethod(key: string): Promise<ThesisMethod> {
  return apiFetch<ThesisMethod>(`/api/v1/methods/${encodeURIComponent(key)}`);
}

export type UserSettings = { inbox_auto_grade: boolean };

export function getSettings(): Promise<UserSettings> {
  return apiFetch<UserSettings>("/api/v1/settings");
}

export function saveSettings(patch: Partial<UserSettings>): Promise<UserSettings> {
  return apiFetch<UserSettings>("/api/v1/settings", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function tidyInbox(useAi = true): Promise<InboxTidyResult> {
  return apiFetch<InboxTidyResult>(`/api/v1/inbox/tidy?use_ai=${useAi}`, { method: "POST" });
}

export type AssessmentItem = {
  method_key: string; method_name: string; category: string;
  // 方法自带的判据表：只给结论不给这些，用户看不出它凭什么这么判
  one_liner: string; core_question: string; steps: string[]; caution: string;
  verdict: string; summary: string;
  evidence: { fact: string; value: string; as_of: string }[];
  gaps: string[]; stale: boolean; checked_at: string | null;
};
export type ManualMethod = {
  method_key: string; method_name: string; category: string;
  core_question: string; steps: string[];
};
export type AssessmentView = {
  company_id: number; company_name: string; checked: boolean;
  results: AssessmentItem[]; manual: ManualMethod[]; boundary: string;
  billing?: { credits: number; tokens: number; calls: number; metered: boolean };
};

export type CounterCheckResult = { checked: number; hits: number; note: string };

/** 把还没核验的公告拿去和已写下的反证条件比对。判定从严，宁可漏报不误报。 */
export function checkCounterHits(companyId?: number): Promise<CounterCheckResult> {
  const q = companyId ? `?company_id=${companyId}` : "";
  return apiFetch<CounterCheckResult>(`/api/v1/counter-hits/check${q}`, { method: "POST" });
}

/** 还没处理的反证命中。**这是唯一一种"你自己写下的那件事真的发生了"的提醒。** */
export type OpenCounterHit = {
  id: number; event_id: number; thesis_id: number; company_id: number;
  company_name: string; claim: string; clause: string; reason: string;
  event_title: string; event_date: string; created_at: string;
};
export function getOpenCounterHits(): Promise<OpenCounterHit[]> {
  return apiFetch<OpenCounterHit[]>("/api/v1/counter-hits");
}

/** 处理掉一条命中。**接口一直都在，只是前端从来没调过** —— 见 CounterHitBanner。 */
export function acknowledgeCounterHit(hitId: number): Promise<{ acknowledged: boolean }> {
  return apiFetch<{ acknowledged: boolean }>(`/api/v1/counter-hits/${hitId}/acknowledge`,
    { method: "POST" });
}


export type CandidateRow = {
  symbol: string; name: string; industry?: string | null;
  pe_ttm?: number | null; pb?: number | null; roe?: number | null;
  verdict: string; reason: string; conclusion?: string; reasons?: string[]; concerns: string[];
};

export type ValueCandidates = {
  strategy: { key: string; name: string } | string;
  width: number; rows: CandidateRow[]; assessed: boolean;
  estimated_credits: number; note: string; boundary?: string;
};

export type SavedCandidateReview = {
  id: number;
  strategy_key: string;
  strategy_name: string;
  width: number;
  rows: CandidateRow[];
  note: string;
  boundary: string;
  estimated_credits: number;
  created_at: string;
};

/**
 * 全市场漏斗：规则先筛，前 width 名再交给模型看。
 * assess=false 只跑规则筛，一分不花——想先看看规则挑出什么再决定时用。
 */
export function runValueCandidates(strategy: string, width: number, assess: boolean): Promise<ValueCandidates> {
  return apiFetch<ValueCandidates>(
    `/api/v1/value-candidates?strategy=${encodeURIComponent(strategy)}&width=${width}&assess=${assess}`,
    { method: "POST" });
}

/** 找票页的模型复核是后台任务；返回任务后由页面轮询。 */
export function startCandidateReview(strategy: string, width: number): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>(
    `/api/v1/value-candidates/review?strategy=${encodeURIComponent(strategy)}&width=${width}`,
    { method: "POST" });
}

export function getCandidateReviewJob(strategy: string, width: number): Promise<BackgroundJob | null> {
  return apiFetch<BackgroundJob | null>(
    `/api/v1/value-candidates/review/status?strategy=${encodeURIComponent(strategy)}&width=${width}`);
}

export function saveCandidateReview(payload: {
  strategy_key: string;
  strategy_name: string;
  width: number;
  rows: CandidateRow[];
  note: string;
  boundary?: string;
  estimated_credits: number;
}): Promise<SavedCandidateReview> {
  return apiFetch<SavedCandidateReview>("/api/v1/value-candidates/saved", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getSavedCandidateReview(strategy: string, width?: number): Promise<SavedCandidateReview | null> {
  const suffix = width ? `&width=${width}` : "";
  return apiFetch<SavedCandidateReview | null>(`/api/v1/value-candidates/saved?strategy=${encodeURIComponent(strategy)}${suffix}`);
}

export type AgentPoolScore = {
  key: string; label: string; weight: number; score: number | null;
  detail: string; reverse: boolean;
};
export type AgentPoolRow = {
  symbol: string; name: string; board: string | null; industry: string | null;
  price: number | null; total_market_cap: number | null; in_research_pool: boolean;
  matched: string[]; scores: AgentPoolScore[];
  /** total 已经去掉：一个需要免责声明的加权总分，就是不该给的分数。
   *  排序改用 matched.length（命中了几套规则），那是数出来的。 */
  missing: string[]; coverage: string; weight_covered: number;
  context: { key: string; label: string; value: number | null; note: string }[];
  attention_rank: number | null; sentiment_as_of: string | null;
  unranked: boolean;
};
export type AgentPool = {
  rows: AgentPoolRow[]; pool_total: number; returned: number; dropped: number;
  strategies: string[]; universe_total: number; with_sentiment: number;
  industries: { name: string; count: number }[]; concentration: string;
  capacity_note: string;
  stance: string; stance_label: string;
  ranked: boolean; unranked_reason: string;
  stances: { key: string; label: string; blurb: string }[];
  dimensions: { key: string; label: string; weight: number; reading: string; reverse: boolean }[];
  note: string; boundary: string;
};

/**
 * 智能体荐股池 · 打底层：五套规则取并集，代码打分排序。
 * **不调模型、不花积分**，也不自动跑——点了才跑。
 */
export function runAgentPool(limit: number, stance: string): Promise<AgentPool> {
  return apiFetch<AgentPool>(
    `/api/v1/agent-pool?limit=${limit}&stance=${encodeURIComponent(stance)}`, { method: "POST" });
}

export type ValuationScenarioRow = {
  key: string; label: string; revenue_growth: number; net_margin: number;
  exit_pe: number; future_revenue?: number; future_profit?: number; per_share: number | null;
};
export type ValuationView = {
  company_id: number; company_name: string; symbol: string;
  ready: boolean; missing: string[]; note: string;
  years?: number; discount_rate?: number; price?: number | null;
  base_revenue?: number; base_report_date?: string | null; shares?: number;
  scenarios?: ValuationScenarioRow[];
  implied_growth?: number | null; implied_verdict?: string;
  sensitivity?: { label: string; exit_pe: number; per_share: number | null }[];
  history?: {
    years: { report_date: string; revenue: number; net_profit: number; net_margin: number | null }[];
    cagr_3y: number | null; cagr_5y: number | null;
    growth_worst: number | null; growth_best: number | null;
    margin_median: number | null; margin_low: number | null; margin_high: number | null;
    covered: number; stat_note: string;
  };
  pe_band?: { p25: number | null; p50: number | null; p75: number | null; covered: number };
  current_pe?: number | null;
  saved?: boolean; saved_at?: string | null; price_at_write?: number | null;
  seeded_from?: string; boundary?: string;
  /** 每个初值是从哪个数来的。**摆在输入框旁边，不然它就是个黑箱。** */
  seed_sources?: { bear?: string; base?: string; bull?: string; note?: string };
};

/** 钱从哪来、去了哪：两张桑基图的原料。
 *
 * **不套响应模型是刻意的**（后端同）：返回的是图的节点与连线，形状随科目多少而变，
 * 套一个模型只会在加一根流量时把它悄悄吃掉。 */
export type MoneyFlowView = {
  company_id: number; symbol: string; company_name?: string;
  report_date?: string; available: boolean; note?: string; boundary?: string;
  /** 「2025 三季报」。**后端拼好的** —— 这四个字是这一页最要紧的一句话，只该有一处拼它。 */
  period_label?: string;
  /** 全年 / 前三季度累计 / 上半年累计 / 第一季度。 */
  span?: string;
  /** 这家公司还有哪些期可选，从新到旧。 */
  periods?: MoneyFlowPeriod[];
  income: { total: number; note: string; links: MoneyFlowLink[];
    /** 左边那层缺了、而且点一下就能补上时是 "syncable"；补不了是空串。 */
    left_fix?: string } | null;
};
export type MoneyFlowPeriod = { report_date: string; label: string; annual: boolean };
export type MoneyFlowLink = {
  source: string; target: string; value: number;
  /** 这根流量对应的报表科目原名。**倒算出来的这一栏是空的** —— 见 derived。 */
  item: string;
  /** 倒算出来的（用别的科目减出来），不是报表上的任何一行。 */
  derived: boolean;
  /** 倒算流量的白话说明。**跟 item 分开**：一句能拿去核年报，一句不能。 */
  explain?: string;
};

export type DocRow = {
  id: number; company_id: number | null; title: string; kind: string;
  /** 标题底下那几个标签：类型 · 是谁 · 哪一期。**抽不到的不给** ——
   *  猜错一个标签会让人打开错的那份文件。 */
  tags?: string[];
  source: string; url: string; page_count: number; read_pages: number;
  char_count: number; table_count: number; created_at: string;
  /** 每种读法各有几页：表格 / 版面 / 双栏 / 扫描件 / 读不到。 */
  modes: Record<string, number>;
  /** 读不到的页，**逐条带页码** —— 给总数的话他没法自己去翻。 */
  unreadable: Array<{ page: number; why: string }>;
  /** 读完自动出的结果。**存在文件上，重开不重付。** */
  digest: string; digest_kind: string; digest_pages: number[]; digest_missed: string[];
};
export type DocPage = { page: number; mode: string; text: string; tables: number; note: string };
/**
 * 一条清单项的结果。**结论一句话，数字单独放** —— 数字塞进句子就又是一堵墙。
 *
 * 数字分两种去处：孤立的一个数进 `figures`，**成组的（同一科目多个年份、
 * 多个分部、多家可比公司）进 `tables`** —— 那种数写成句子对不齐，排成表一眼看得清。
 */
export type DigestItem = {
  title: string; verdict: string; pages: number[]; found?: boolean;
  figures?: Array<{ label: string; value: string; note?: string }>;
  tables?: DigestTable[];
};
export type DigestBody = { watch?: Array<{ point: string; pages: number[] }>; items?: DigestItem[] };
export type DocDigest = {
  digest: string; kind: string; pages: number[]; missed: string[];
  /** 数字回它自己标注的那几页去核，核不到的那些。
   *  `where: "没有"` = 整份文件里都找不到这个数（多半是编的）；
   *  `where: "别的页"` = 数字对，页码标错了。两者都破坏「翻回原文核」。 */
  unverified?: { value: string; where: string }[];
  credits: number; cached?: boolean; note?: string; boundary?: string; chars?: number;
  /** 这一次的输出解析成 JSON 了吗。**只有新读的那次有这个字段** ——
   *  库里取出来的老结果没有，于是"这次截断了"和"这是旧版式存的"分得开。 */
  structured?: boolean;
};
export type DocDetail = DocRow & {
  pages: DocPage[];
  /** 数字回所引页核不到的那些。**详情里也要带** —— 界面初次渲染是从这里拼结果的。 */
  digest_unverified?: { value: string; where: string }[];
};
export type DocAnswer = {
  answer: string; pages: number[]; note: string; credits: number;
  chars?: number; boundary?: string;
};

export function getDocuments(companyId?: number): Promise<{ rows: DocRow[]; boundary: string }> {
  const suffix = companyId ? `?company_id=${companyId}` : "";
  return apiFetch(`/api/v1/documents${suffix}`);
}

export function getDocument(id: number): Promise<DocDetail> {
  return apiFetch<DocDetail>(`/api/v1/documents/${id}`);
}

export function deleteDocument(id: number): Promise<void> {
  return apiFetch(`/api/v1/documents/${id}`, { method: "DELETE" });
}

/** 上传一份 PDF。**解析在本地做，不花积分** —— 所以这一步没有报价。 */
export async function uploadDocument(file: File, companyId?: number): Promise<DocRow> {
  const form = new FormData();
  form.append("file", file);
  if (companyId) form.append("company_id", String(companyId));
  // **不要带 Content-Type**：浏览器要自己填 multipart 的 boundary，手写一个会让后端
  // 收到一个解不开的表单，而报出来的错跟"文件坏了"长得一模一样。
  // 所以这条不能走 apiFetch（它一律加 application/json）。
  const response = await fetch(apiUrl("/api/v1/documents"), { method: "POST", body: form });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    throw new ApiError(describeError(payload?.detail, response.status));
  }
  return response.json() as Promise<DocRow>;
}

export function readDocumentUrl(url: string, companyId?: number): Promise<DocRow> {
  return apiFetch<DocRow>("/api/v1/documents/from-url",
    { method: "POST", body: JSON.stringify({ url, company_id: companyId }) });
}

/**
 * 从一份募集资金专项报告里抽募投进度并落库。
 * **抽完直接排进公司档案那张甘特图的第三条泳道** —— 第一条「读文档的结果
 * 喂给另一个功能」的链子。
 */
export function extractFundraising(id: number, companyId?: number, dryRun?: boolean) {
  return apiFetch<{ saved: number; pages: number[]; credits: number; note?: string; boundary?: string }>(
    `/api/v1/documents/${id}/fundraising`,
    { method: "POST", body: JSON.stringify({ company_id: companyId, dry_run: dryRun }) });
}

/** 读完自动出的那份结果。已经有就直接返回（不重付），`redo` 强制重出。 */
/** 按第一页重认标题、类型和标签。**不调模型，不花积分** —— 给老文件用。 */
export function retitleDocument(id: number) {
  return apiFetch<{ id: number; title: string; kind: string; tags: string[]; changed: boolean }>(
    `/api/v1/documents/${id}/retitle`, { method: "POST", body: "{}" });
}

export function digestDocument(id: number, opts: { dryRun?: boolean; redo?: boolean } = {}) {
  return apiFetch<DocDigest>(`/api/v1/documents/${id}/digest`, {
    method: "POST", body: JSON.stringify({ dry_run: opts.dryRun, redo: opts.redo }),
  });
}

/** `dryRun` 只报价不调模型 —— 检索在本地做，报价不该花钱。 */
export function askDocument(id: number, question: string,
                            opts: { dryRun?: boolean; followup?: boolean } = {}): Promise<DocAnswer> {
  return apiFetch<DocAnswer>(`/api/v1/documents/${id}/ask`, {
    method: "POST",
    body: JSON.stringify({ question, dry_run: opts.dryRun, followup: opts.followup }),
  });
}

export type ScheduleItem = {
  title: string; start: string; end: string | null; point: boolean;
  state: string; detail: string; url?: string | null; kind: string; weight?: number | null;
};
export type ScheduleLane = { key: string; label: string; note: string; items: ScheduleItem[] };
export type ScheduleView = {
  company_id: number; symbol: string; company_name?: string;
  available: boolean; today: string; start: string; end: string;
  lanes: ScheduleLane[];
  /** 画不出来的泳道，逐条写明为什么。**不省掉** —— 少一条会被读成"这家公司没有"。 */
  missing: Array<{ key: string; why: string }>;
  note?: string; boundary?: string;
};

/**
 * 未来有哪些日子在等着：承诺台账 + 限售股解禁的**区间**。
 *
 * **不是 `getTimeline`** —— 那个是估值走势 + 事件时点，另一条路径、另一个问题。
 */
export function getSchedule(companyId: number): Promise<ScheduleView> {
  return apiFetch<ScheduleView>(`/api/v1/companies/${companyId}/schedule`);
}

/** `reportDate` 不传就是最近一期年报。传了对不上的期，后端退回默认而不是报错。 */
export function getMoneyFlow(companyId: number, reportDate?: string): Promise<MoneyFlowView> {
  const suffix = reportDate ? `?report_date=${encodeURIComponent(reportDate)}` : "";
  return apiFetch<MoneyFlowView>(`/api/v1/companies/${companyId}/money-flow${suffix}`);
}

export function getValuation(companyId: number): Promise<ValuationView> {
  return apiFetch<ValuationView>(`/api/v1/companies/${companyId}/valuation`);
}

/** 存下你的假设。**每次存插一行**，旧的留着——那是你判断变迁的记录。 */
export function saveValuation(companyId: number, payload: {
  years: number; discount_rate: number; note?: string;
  scenarios: { key: string; revenue_growth: number; net_margin: number; exit_pe: number }[];
}): Promise<ValuationView> {
  return apiFetch<ValuationView>(`/api/v1/companies/${companyId}/valuation`,
    { method: "PUT", body: JSON.stringify(payload) });
}

export type AttributionRow = {
  thesis_id: number; company_id: number; company_name: string; symbol: string;
  claim: string; counter_condition: string; status: ThesisStatus; written_at: string;
  price_at_write: number | null; price_now: number | null; price_move: number | null;
  counter_fired: number; first_fired_at: string | null; acted: boolean; state: string;
};
export type AttributionView = {
  rows: AttributionRow[]; total: number; fired: number; silent: number;
  no_falsifier: number; enough: boolean; median_move: number | null;
  headline: string; note: string; question: string; boundary: string;
  /** 还差几条才谈得上规律。**进度可以往前推，"不够"读完就到头了。** */
  progress?: { have: number; need: number };
};

export function getAttribution(): Promise<AttributionView> {
  return apiFetch<AttributionView>("/api/v1/attribution");
}

/** 对话式反方：钉在一家公司上，专门找你这条判断可能错在哪。**只读、只提议。** */
export type AdvocatePoint = {
  claim: string;
  evidence: { tool: string; shows: string }[];
  counter_condition: string;
  task: string;
  /** 这几个数在工具返回的数据里找不到——**不是删掉，是标出来**，请自己核。 */
  untraceable: string[];
  /** 超出复核上限、这一轮没被独立再查过。**不标的话它会假装自己也核过了。** */
  unchecked?: boolean;
};
export type AdvocateView = {
  company_id: number; company_name: string; symbol: string; question: string;
  points: AdvocatePoint[]; not_challenged: string; gaps: string[];
  tool_calls: { tool: string; rows: number }[]; rounds: number;
  messages: unknown[]; boundary: string;
};

export function askAdvocate(companyId: number, question: string,
                            history: unknown[] = []): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>(`/api/v1/companies/${companyId}/advocate`,
    { method: "POST", body: JSON.stringify({ question, history }) });
}

/** 反方每一轮都落在后台任务存档里，页面用它恢复上方的结果胶囊。 */
export function getAdvocateHistory(companyId: number, limit = 20): Promise<BackgroundJob[]> {
  return apiFetch<BackgroundJob[]>(
    `/api/v1/companies/${companyId}/advocate/history?limit=${limit}`);
}

/** 管理层承诺兑现台账：公司说过的话，到期之后有没有人回头看。 */
export type PromiseCheck = { verdict: string; actual: number | null; period?: string; note: string };
export type PromiseRow = {
  id: number; company_id: number; subject: string; statement: string; category: string;
  promised_on: string; due_date: string | null; status: string; outcome_note: string;
  source_title: string; source_url: string | null;
  check_metric: string; check_op: string; check_value: number | null; check_period: string;
  check: PromiseCheck; overdue: boolean;
};
export type PromiseView = {
  company_id: number; company_name: string; symbol: string; as_of: string;
  rows: PromiseRow[]; total: number; due: number; kept: number; broken: number;
  undated: number; pending: number; headline: string; note: string; boundary: string;
};
export type PromiseFound = {
  statement: string; promised_on: string; subject: string; category: string;
  due_date: string; check_metric: string; check_op: string; check_value: number | null;
  check_period: string; event_id: number | null; source_title: string; source_url: string | null;
  /** 回公告原文核对的结果：原文 / 拼接 / 没有正文可对。对不上的在服务端就丢了。 */
  verbatim?: string;
  verbatim_note?: string;
};

export function getPromises(companyId: number): Promise<PromiseView> {
  return apiFetch<PromiseView>(`/api/v1/companies/${companyId}/promises`);
}
/** 抽承诺这一次大概几分 —— 按真实入参算，不是典型值表。 */
export function estimatePromises(companyId: number) {
  return apiFetch<{ credits: number; events: number; with_text: number; note: string }>(
    `/api/v1/companies/${companyId}/promises/estimate`);
}

export function extractPromises(companyId: number): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>(`/api/v1/companies/${companyId}/promises/extract`, { method: "POST" });
}
export function savePromises(companyId: number, items: PromiseFound[]): Promise<{ saved: number; note: string }> {
  return apiFetch(`/api/v1/companies/${companyId}/promises`,
    { method: "POST", body: JSON.stringify({ items }) });
}
/** 给一条承诺下结论。**结论由人下**——自动核对只说对上没对上。 */
export function settlePromise(promiseId: number, status: string, note = ""): Promise<{ id: number; status: string }> {
  return apiFetch(`/api/v1/promises/${promiseId}`,
    { method: "PATCH", body: JSON.stringify({ status, note }) });
}

/** 行业特有指标：白酒的合同负债、银行的拨贷比、地产的已售未结转。 */
export type IndustryMetricRow = {
  key: string; label: string; unit: string; scope: string;
  formula: string; why: string; good: string; annual_only: boolean;
  series: { report_date: string; value: number }[];
  latest: { report_date: string; value: number } | null;
  change: number | null; compare_note: string; trendable: boolean;
  inputs: string[]; missing: string[]; applicable: boolean;
};
export type IndustryMetricsView = {
  company_id: number; company_name: string; symbol: string;
  industry: string; resolved: string; rows: IndustryMetricRow[];
  annual_periods: number; note: string; boundary: string;
  industry_sources: Record<string, string>;
};

export function getIndustryMetrics(companyId: number): Promise<IndustryMetricsView> {
  return apiFetch<IndustryMetricsView>(`/api/v1/companies/${companyId}/industry-metrics`);
}

/** 组合共同风险：我以为的分散，是不是同一个赌注下了五次。 */
export type CommonRiskMember = { symbol: string; name: string; weight: number | null; detail: string };
export type CommonRiskGroup = {
  kind: string; label: string; members: CommonRiskMember[]; member_count: number;
  weight: number | null; evidence: string; confidence: string; question: string;
};
export type CommonRiskView = {
  portfolio_id: number; portfolio_name: string; amount_mode: string;
  position_count: number; weighted: boolean; groups: CommonRiskGroup[]; hidden: number;
  headline: string; note: string; boundary: string;
  /** 只有一只持仓时给出那一家——这种仓位下唯一要紧的事是它的认错条件。 */
  single?: { symbol: string; name: string; company_id: number | null } | null;
};

export function getPortfolioCommonRisk(portfolioId: number): Promise<CommonRiskView> {
  return apiFetch<CommonRiskView>(`/api/v1/portfolios/${portfolioId}/common-risk`);
}

export type QuickThesisContext = {
  symbol: string; name: string | null; company_id: number | null; known: boolean;
  suggestions: { text: string; why: string }[]; note: string;
};
export type QuickThesisResult = {
  company_id: number; company_name: string; symbol: string;
  thesis_id: number; created_company: boolean; note: string;
};

export function getQuickThesisContext(symbol: string): Promise<QuickThesisContext> {
  return apiFetch<QuickThesisContext>(
    `/api/v1/quick-thesis/context?symbol=${encodeURIComponent(symbol)}`);
}

/** 三十秒写下一个判断：哪家 · 为什么 · 什么情况下我认错。没建档会顺手建。 */
export function writeQuickThesis(payload: {
  symbol: string; claim: string; counter_condition: string;
}): Promise<QuickThesisResult> {
  return apiFetch<QuickThesisResult>("/api/v1/quick-thesis",
    { method: "POST", body: JSON.stringify(payload) });
}

export type DriftChange = {
  change: {
    from_at: string; to_at: string;
    price_before: number | null; price_after: number | null;
    assumption_shift: number | null; price_shift: number | null;
    fields: { key: string; label: string; unit: string; before: number; after: number; change: number }[];
    followed_price: boolean; against_price: boolean;
  };
  context: { evidences: number; material_events: number; reports: number };
  reading: { level: string; headline: string; question: string };
};
export type ValuationDrift = {
  company_id: number; company_name: string; symbol: string;
  saves: number; changes: DriftChange[]; summary: string;
  open_questions: number; boundary: string;
};

export function getValuationDrift(companyId: number): Promise<ValuationDrift> {
  return apiFetch<ValuationDrift>(`/api/v1/companies/${companyId}/valuation/drift`);
}

export type SentimentSummary = {
  total: number; ranked: number; followed: number;
  trade_date: string | null; updated_at: string | null; source: string; reading: string;
};

export function getSentimentSummary(): Promise<SentimentSummary> {
  return apiFetch<SentimentSummary>("/api/v1/sentiment/summary");
}

/** 按某个方法写一条投资逻辑：后台跑，跑完直接落库。切走页面不影响。 */
export function writeThesis(companyId: number, method: string): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>(
    `/api/v1/companies/${companyId}/thesis-write?method=${encodeURIComponent(method)}`,
    { method: "POST" });
}

export function deleteThesis(thesisId: number): Promise<{ deleted: boolean }> {
  return apiFetch<{ deleted: boolean }>(`/api/v1/theses/${thesisId}`, { method: "DELETE" });
}

export type SyncStripJob = {
  job_id: string; name: string; category: string;
  runs: { status: string; at: string; note: string }[];
  failed: number; total: number;
};

export function getSyncStrip(perJob = 24): Promise<SyncStripJob[]> {
  return apiFetch<SyncStripJob[]>(`/api/v1/sync/strip?per_job=${perJob}`);
}

export function getAssessmentMatrix() {
  return apiFetch<{ rows: import("./components/AssessmentMatrix").MatrixRow[];
                    assessed: number; boundary: string }>("/api/v1/assessment-matrix");
}

export function getTimeline(companyId: number, years = 2) {
  return apiFetch<import("./components/CompanyTimeline").TimelinePayload>(
    `/api/v1/companies/${companyId}/timeline?years=${years}`);
}

export interface PeerPositionView {
  industry: string;
  peers: number;
  note: string;
  metrics: Array<{
    key: string; label: string; unit: string; higher_is_better: boolean;
    value: number | null; percentile: number | null;
    p10: number; p25: number; p50: number; p75: number; p90: number; sample: number;
  }>;
}

export interface EvidenceDirectionView {
  events: Array<{ id: number; date: string; title: string; polarity: string;
                  reason: string; source: string; url: string }>;
  theses: Array<{ id: number; claim: string; date: string }>;
  total_documents: number;
  boundary: string;
}

export interface EvidenceDirectionPlan {
  ready: boolean; documents: number; events: number; credits: number;
  thesis?: { id: number; claim: string }; note: string;
}

export function getEvidenceDirection(companyId: number): Promise<EvidenceDirectionView> {
  return apiFetch<EvidenceDirectionView>(`/api/v1/companies/${companyId}/evidence-direction`);
}

export function getEvidenceDirectionPlan(companyId: number): Promise<EvidenceDirectionPlan> {
  return apiFetch<EvidenceDirectionPlan>(`/api/v1/companies/${companyId}/evidence-direction/plan`);
}

export function judgeEvidenceDirection(companyId: number): Promise<{ judged: number; counts: Record<string, number>; note: string }> {
  return apiFetch(`/api/v1/companies/${companyId}/evidence-direction`, { method: "POST" });
}

export interface SegmentView {
  symbol: string;
  company_name: string;
  report_date: string | null;
  boundary: string;
  dimensions: Array<{
    key: string;
    items: Array<{
      segment: string; revenue: number | null; revenue_share: number | null;
      profit_share: number | null; gross_margin: number | null; filler: boolean;
    }>;
  }>;
}

export function getSegments(companyId: number): Promise<SegmentView> {
  return apiFetch<SegmentView>(`/api/v1/companies/${companyId}/segments`);
}

export function refreshSegments(companyId: number): Promise<SegmentView> {
  return apiFetch<SegmentView>(`/api/v1/companies/${companyId}/segments`, { method: "POST" });
}

export interface PeerTableView {
  industry: string;
  total: number;
  note: string;
  median: Record<string, number | null>;
  rows: Array<{
    symbol: string; name: string; is_self: boolean;
    total_market_cap: number | null; pe_ttm: number | null; pb: number | null;
    roe: number | null; gross_margin: number | null;
    revenue_growth: number | null; net_profit_growth: number | null;
    dividend_yield: number | null;
  }>;
}

/** 给一个候选跑方法体检。不要求先建档——体检就是用来帮你决定要不要建档的。 */
export interface DeepReportPlan {
  company_id: number; company_name: string; queries: string[];
  searches: number; credits: number; search_ready: boolean; note: string;
}

/** 手动加一条产业链关系。手写的直接算已证实——是你自己填的。 */
export function addChainLink(companyId: number, payload: Record<string, string>) {
  return apiFetch<import("./types").SupplyChainView>(
    `/api/v1/companies/${companyId}/supply-chain`, { method: "POST", body: JSON.stringify(payload) });
}

export function deleteReport(reportId: number): Promise<{ deleted: boolean }> {
  return apiFetch<{ deleted: boolean }>(`/api/v1/reports/${reportId}`, { method: "DELETE" });
}

export function getDeepReportPlan(companyId: number): Promise<DeepReportPlan> {
  return apiFetch<DeepReportPlan>(`/api/v1/companies/${companyId}/deep-report/plan`);
}

/** 联网找资料 + 库里的真实数字写一份报告。后台任务，一两分钟。 */
export function makeDeepReport(companyId: number): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>(`/api/v1/companies/${companyId}/deep-report`, { method: "POST" });
}

export function assessTaskItem(itemId: number): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>(`/api/v1/tasks/items/${itemId}/assessment`, { method: "POST" });
}

export function getPeerTable(companyId: number): Promise<PeerTableView> {
  return apiFetch<PeerTableView>(`/api/v1/companies/${companyId}/peer-table`);
}

export function getPeerPosition(companyId: number): Promise<PeerPositionView> {
  return apiFetch<PeerPositionView>(`/api/v1/companies/${companyId}/peer-position`);
}

export function getAssessment(companyId: number): Promise<AssessmentView> {
  return apiFetch<AssessmentView>(`/api/v1/companies/${companyId}/assessment`);
}

export function runAssessment(companyId: number): Promise<AssessmentView> {
  return apiFetch<AssessmentView>(`/api/v1/companies/${companyId}/assessment`, { method: "POST" });
}

/** 起草一条投资逻辑。**后台跑**——它现在要自己查库，实测 57 秒。
 *  返回的是任务，结果从 getJob("thesis_draft", companyId) 里拿。 */
export function draftThesis(companyId: number, method?: string): Promise<BackgroundJob> {
  const suffix = method ? `?method=${encodeURIComponent(method)}` : "";
  return apiFetch<BackgroundJob>(`/api/v1/companies/${companyId}/thesis-draft${suffix}`, { method: "POST" });
}

/** 起一个后台任务。一轮要 20 秒以上（十几个 RSS 源逐个抓 + 模型分批匹配）。 */
export function refreshNews(): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>("/api/v1/news/refresh", { method: "POST" });
}

export function getNews(status = "待确认", limit = 60, read = "全部"): Promise<NewsPage> {
  return apiFetch<NewsPage>(`/api/v1/news?status=${encodeURIComponent(status)}&read=${encodeURIComponent(read)}&limit=${limit}`);
}

export function confirmNews(newsId: number, companyId?: number): Promise<{ evidence_id: number }> {
  const suffix = companyId ? `?company_id=${companyId}` : "";
  return apiFetch(`/api/v1/news/${newsId}/confirm${suffix}`, { method: "POST" });
}

export function ignoreNews(newsId: number): Promise<{ ignored: boolean }> {
  return apiFetch(`/api/v1/news/${newsId}/ignore`, { method: "POST" });
}

export function markNewsRead(newsId: number): Promise<{ read: boolean; read_at: string }> {
  return apiFetch(`/api/v1/news/${newsId}/read`, { method: "POST" });
}

export function getSupplyChain(companyId: number): Promise<SupplyChainView> {
  return apiFetch<SupplyChainView>(`/api/v1/companies/${companyId}/supply-chain`);
}

export function getIndustryChains(): Promise<IndustryChainThemeSummary[]> {
  return apiFetch<IndustryChainThemeSummary[]>("/api/v1/industry-chains");
}

export function getIndustryChain(themeId: number): Promise<IndustryChainView> {
  return apiFetch<IndustryChainView>(`/api/v1/industry-chains/${themeId}`);
}

/** 按环节横排的对照数据;行情取自全市场底座,跟着 universe 同步任务走。 */
export function getIndustryChainCompare(themeId: number): Promise<ChainCompareView> {
  return apiFetch<ChainCompareView>(`/api/v1/industry-chains/${themeId}/compare`);
}

export function createIndustryChain(payload: {
  name: string; chain_type: string; description?: string;
}): Promise<IndustryChainView> {
  return apiFetch<IndustryChainView>("/api/v1/industry-chains", {
    method: "POST", body: JSON.stringify(payload),
  });
}

/** 主题 → 公开资料 → 可编辑的待确认产业链初稿。任务在服务端跑，切页不会丢。 */
export function startIndustryChainDraft(topic: string): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>("/api/v1/industry-chains/draft", {
    method: "POST", body: JSON.stringify({ topic }),
  });
}

export function getIndustryChainDraftJob(): Promise<BackgroundJob | null> {
  return apiFetch<BackgroundJob | null>("/api/v1/industry-chains/draft/status");
}

export function forkIndustryChain(themeId: number): Promise<IndustryChainView> {
  return apiFetch<IndustryChainView>(`/api/v1/industry-chains/${themeId}/fork`, {
    method: "POST",
  });
}

export function addIndustryChainStage(themeId: number, payload: {
  name: string; stage_kind?: string; description?: string;
}): Promise<IndustryChainView> {
  return apiFetch<IndustryChainView>(`/api/v1/industry-chains/${themeId}/stages`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function addIndustryChainNode(themeId: number, payload: {
  stage_id: number; name: string; node_type: string; description?: string;
  source_name?: string; source_url?: string; verification?: string;
  upstream_node_id?: number | null; relation_type?: string;
}): Promise<IndustryChainView> {
  return apiFetch<IndustryChainView>(`/api/v1/industry-chains/${themeId}/nodes`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function addIndustryChainEdge(themeId: number, payload: {
  from_node_id: number; to_node_id: number; relation_type: string;
  detail?: string; source_name?: string; source_url?: string; verification?: string;
}): Promise<IndustryChainView> {
  return apiFetch<IndustryChainView>(`/api/v1/industry-chains/${themeId}/edges`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function addIndustryChainPosition(themeId: number, payload: {
  node_id: number; company_id: number; role: string; detail?: string;
  source_name?: string; source_url?: string; verification?: string;
}): Promise<IndustryChainView> {
  return apiFetch<IndustryChainView>(`/api/v1/industry-chains/${themeId}/positions`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function deleteIndustryChainRecord(
  kind: "theme" | "stage" | "node" | "edge" | "position", recordId: number,
): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/v1/industry-chains/records/${kind}/${recordId}`, { method: "DELETE" });
}

export function getCompanyIndustryChainPositions(companyId: number): Promise<CompanyIndustryChainPositions> {
  return apiFetch<CompanyIndustryChainPositions>(`/api/v1/companies/${companyId}/industry-chain-positions`);
}

export function refreshSupplyChain(companyId: number): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>(`/api/v1/companies/${companyId}/supply-chain/refresh`, { method: "POST" });
}

export function confirmChainLink(linkId: number): Promise<{ confirmed: boolean }> {
  return apiFetch(`/api/v1/supply-chain/${linkId}/confirm`, { method: "POST" });
}

export function deleteChainLink(linkId: number): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/v1/supply-chain/${linkId}`, { method: "DELETE" });
}

export function getReports(companyId?: number): Promise<ResearchReport[]> {
  const suffix = companyId ? `?company_id=${companyId}` : "";
  return apiFetch<ResearchReport[]>(`/api/v1/reports${suffix}`);
}

export function generateReport(companyId: number): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>(`/api/v1/companies/${companyId}/reports`, { method: "POST" });
}

export function rederiveUniverse(): Promise<UniverseRederiveResult> {
  return apiFetch<UniverseRederiveResult>("/api/v1/universe/rederive", { method: "POST" });
}

export function autoReviewTask(taskId: number, limit = 30): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>(`/api/v1/research-tasks/${taskId}/auto-review?limit=${limit}`, { method: "POST" });
}

export function getJob(kind: string, targetId: number): Promise<BackgroundJob | null> {
  return apiFetch<BackgroundJob | null>(`/api/v1/jobs/${encodeURIComponent(kind)}/${targetId}`);
}

export function getNewsFeeds(): Promise<NewsFeed[]> {
  return apiFetch<NewsFeed[]>("/api/v1/news/feeds");
}

export function saveNewsFeed(payload: { name: string; url: string; key?: string; enabled?: boolean }): Promise<NewsFeed> {
  return apiFetch<NewsFeed>("/api/v1/news/feeds", { method: "POST", body: JSON.stringify(payload) });
}

export function toggleNewsFeed(feedId: number, enabled: boolean): Promise<{ updated: boolean }> {
  return apiFetch(`/api/v1/news/feeds/${feedId}?enabled=${enabled}`, { method: "PATCH" });
}

export function deleteNewsFeed(feedId: number): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/v1/news/feeds/${feedId}`, { method: "DELETE" });
}

export function getBriefing(): Promise<DailyBriefing | null> {
  return apiFetch<DailyBriefing | null>("/api/v1/briefing");
}

export function generateBriefing(): Promise<BackgroundJob> {
  return apiFetch<BackgroundJob>("/api/v1/briefing", { method: "POST" });
}

/** 本模块的计费状态：接没接入虾米伙伴积分、单价怎么算、还剩多少。 */
export function getCreditState(): Promise<CreditState> {
  return apiFetch<CreditState>("/api/v1/credits/state");
}

/** 删掉一笔交易。手记会记错、也会记重，删不掉就只能记一笔反向交易去抵消，
 *  那等于往账本里写一笔从未发生过的事。 */
export function deleteTrade(tradeId: number): Promise<void> {
  return apiFetch<void>(`/api/v1/trades/${tradeId}`, { method: "DELETE" });
}

/** 登记一次真实成交。**在你按下单的那一刻填，不是事后补账。**
 *
 * 这是「计划内 / 计划外」现在唯一的数据来源：持仓改成只记两个数之后，
 * 账本里不会再有 buy 流水，那个指标必须换源，否则永久归零且不报错。 */
export function recordFill(companyId: number, payload: {
  price: number; filled_on?: string; shares?: number | null; note?: string;
}): Promise<DecisionCardView> {
  return apiFetch<DecisionCardView>(`/api/v1/companies/${companyId}/fills`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

/** 删掉一条成交登记。**填错价格是常事**，而错的成交价会让纪律指标一直错。 */
export function deleteFill(fillId: number): Promise<void> {
  return apiFetch<void>(`/api/v1/fills/${fillId}`, { method: "DELETE" });
}

/** 删掉一个组合，连里面的持仓一起。**删了就回不来。** */
export function deletePortfolio(portfolioId: number): Promise<{
  deleted: boolean; name: string; holdings: number;
}> {
  return apiFetch(`/api/v1/portfolios/${portfolioId}`, { method: "DELETE" });
}

/** 设定一只票的持仓：N 股、成本价 P。**新增和更新是同一个动作。**
 *
 * 用 PUT 不用 POST：这是"把它设成这样"，不是"再加一笔"。
 * 同一组数调两次结果一样——不会变成买了两次。 */
export function setHolding(portfolioId: number, companyId: number,
                           shares: number, costPrice: number): Promise<TradeRecord> {
  return apiFetch<TradeRecord>(`/api/v1/portfolios/${portfolioId}/holdings`, {
    method: "PUT",
    body: JSON.stringify({ company_id: companyId, shares, cost_price: costPrice }),
  });
}

/** 把一只票从持仓里去掉，连同它的历史。**删掉就回不来了。** */
export function deleteHolding(portfolioId: number, companyId: number): Promise<{
  deleted: number;
  companies: { company_id: number; name: string; symbol: string; trades: number }[];
}> {
  return apiFetch(`/api/v1/portfolios/${portfolioId}/holdings/${companyId}`,
                  { method: "DELETE" });
}

/** 把某几家公司的流水整段删掉。**删不回来。**
 *
 * 逐条修修不回一本烂账：停记了半年、中间又买卖过，缺的那几笔你自己也想不起来。
 * 唯一能回到「账对得上」的路是整段翻篇 + 一条期初持仓声明现在有多少。
 *
 * **返回的条数一定要显示出来**：选错组合时删 0 条和删 34 条在界面上长得一样。 */
export function purgeCompanyTrades(portfolioId: number, companyIds: number[]): Promise<{
  deleted: number;
  companies: { company_id: number; name: string; symbol: string; trades: number }[];
}> {
  return apiFetch(`/api/v1/portfolios/${portfolioId}/trades/purge`, {
    method: "POST",
    body: JSON.stringify({ company_ids: companyIds }),
  });
}

/** 每个花钱的动作大概几分。典型值，不是承诺——结算按真实用量。 */
export function getCreditEstimates(): Promise<Record<string, number | null>> {
  return apiFetch<Record<string, number | null>>("/api/v1/credits/estimates");
}

export function updatePortfolio(portfolioId: number, payload: PortfolioUpdateInput): Promise<PortfolioSummary> {
  return apiFetch<PortfolioSummary>(`/api/v1/portfolios/${portfolioId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/** 分级引擎从纠错里学到了什么。只读，页面负责让你逐条确认。 */
export function getInboxLearning(): Promise<InboxLearning> {
  return apiFetch<InboxLearning>("/api/v1/inbox/learning");
}

export function saveRuleTerm(term: string, relevance: string, topic = "自定义"): Promise<unknown> {
  const query = new URLSearchParams({ term, relevance, topic });
  return apiFetch(`/api/v1/inbox/rule-terms?${query}`, { method: "POST" });
}

export function deleteRuleTerm(term: string): Promise<{ deleted: boolean }> {
  return apiFetch<{ deleted: boolean }>(`/api/v1/inbox/rule-terms/${encodeURIComponent(term)}`, { method: "DELETE" });
}

/** 每只票一行的决策状态表。与今日简报读同一批事实，但摊开成可逐只处理的形式。 */
export function getDecisionBoard(): Promise<DecisionBoard> {
  return apiFetch<DecisionBoard>("/api/v1/decision-board");
}

/** 你写过的全部投资逻辑。**首页那张「投资逻辑 N 条」的卡片要指向它** —— 
 *  原来指的是复核工作台，而那一页按定义只放"该重看的"，不到期时是空的。 */
export type ThesisListItem = {
  id: number; company_id: number; company_name: string; symbol: string; industry: string | null;
  claim: string; counter_condition: string; status: ThesisStatus;
  next_review_trigger: string; next_review_date: string | null; last_reviewed_at: string | null;
  created_at: string; updated_at: string; method_name: string | null;
  counter_evidence: number; support_evidence: number; review_count: number;
  no_counter_condition: boolean; never_reviewed: boolean;
};
export function getAllTheses(): Promise<ThesisListItem[]> {
  return apiFetch<ThesisListItem[]>("/api/v1/theses");
}

/** 产业链位置：年报强制披露的客户与供应商集中度。**纯正则抽取，不花积分。** */
export type ChainPosition = {
  company_id: number; symbol: string; available: boolean;
  report_title: string; report_date: string; source_url: string | null;
  customer_ratio: number | null; supplier_ratio: number | null;
  customer_amount: number | null; supplier_amount: number | null;
  top: { name: string; amount: number | null; ratio: number | null }[];
  excerpt: string; reading: string; note: string; boundary: string;
};
export function getChainPosition(companyId: number, refresh = false): Promise<ChainPosition> {
  return apiFetch<ChainPosition>(
    `/api/v1/companies/${companyId}/chain-position${refresh ? "?refresh=true" : ""}`);
}

/** 三份示例档案。**由使用者在空态点一下，不自动种**——自动种是替他做决定。 */
export type SampleResult = {
  created: string[]; skipped: string[]; synced?: string[];
  failures?: string[]; note: string; boundary?: string;
};
export function loadSamples(): Promise<SampleResult> {
  return apiFetch<SampleResult>("/api/v1/samples", { method: "POST" });
}
export function removeSamples(): Promise<{ removed: string[]; note: string }> {
  return apiFetch<{ removed: string[]; note: string }>("/api/v1/samples", { method: "DELETE" });
}


/** 当前的访问姿态。**页面靠 is_guest 决定给登录引导还是给建档入口**——
 *  不然游客看到的是一个点了就 401 的按钮。 */
export type AccessView = {
  mode: string; owner_configured: boolean; note: string;
  follows_console: boolean; is_guest: boolean;
  /** 站主才看得见备份与恢复：那几个接口是 require_owner，
   *  没有这个信号的时候菜单对所有人亮着，点进去只会撞 403。 */
  is_owner: boolean;
};
export function getAccess(): Promise<AccessView> {
  return apiFetch<AccessView>("/api/v1/access");
}

/* ══════════════════════════════════════════════════════════════════════════
 * 我的判断 · 做 T 回测 / 决策闭环 / 涨跌类型
 * ════════════════════════════════════════════════════════════════════════ */

/** 做 T 回测：规律检验 + 四条策略的机器模拟。**纯算术，不花积分。** */
export type SwingConditional = {
  label: string; hits: number; total: number; rate: number | null;
  base: number; lift: number | null; p_value: number | null;
};
export type SwingRhythm = {
  enough: boolean; days: number; note?: string;
  start?: string; end?: string; verdict?: string; headline?: string;
  up_days?: number; down_days?: number; flat_days?: number;
  base_up?: number; base_down?: number;
  reversal?: SwingConditional; rebound?: SwingConditional; alpha?: number;
  autocorrelation_1?: number | null; autocorrelation_2?: number | null;
  mean_abs_return?: number; mean_amplitude?: number | null; amplitude_days?: number;
  daily_sigma?: number | null;
  volatility_5d?: number | null; volatility_20d?: number | null; volatility_window?: number | null;
  runs?: {
    max_up: number; max_down: number;
    up_histogram: { length: number; times: number }[];
    down_histogram: { length: number; times: number }[];
  };
};
export type SwingRun = {
  ok: boolean; strategy: string; label: string; blurb?: string; days: number;
  start?: string; end?: string; trades: number; note?: string;
  wins?: number; win_rate?: number; gross?: number; fees?: number; net?: number;
  net_percent?: number | null; net_per_trade?: number; fee_share?: number | null;
  breakeven_spread?: number | null; max_drawdown?: number;
  /** 这个结果跟运气分得开吗。**正收益必须当场配上它**。 */
  win_rate_p_value?: number | null; t_stat?: number | null; small_sample?: boolean;
  curve?: { date: string; cumulative: number }[];
  skipped_locked: number; skipped_no_open: number; not_triggered: number;
  base_shares?: number; tactical_shares?: number; base_value?: number;
};
export type SwingView = {
  company_id: number; symbol: string; name: string;
  rhythm: SwingRhythm; runs: SwingRun[];
  ceiling_line: string; cost_line: string; best_line: string;
  strategies: Record<string, { label: string; blurb: string; why: string }>;
  cost_labels: Record<string, string>;
  caveats: string[];
  bars_available: number; window: number; windows: number[];
  trigger_percent: number; base_shares: number; tactical_percent: number;
  shares_held: number | null; missing_open_days: number;
};
export type SwingOptions = {
  window?: number; trigger_percent?: number; base_shares?: number;
  tactical_percent?: number;
  commission_rate?: number; commission_min?: number; stamp_tax_rate?: number;
  transfer_fee_rate?: number; slippage_rate?: number;
};

export function getSwingStudy(companyId: number, options: SwingOptions = {}): Promise<SwingView> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(options)) {
    if (value !== undefined && value !== null) query.set(key, String(value));
  }
  const suffix = query.toString() ? `?${query}` : "";
  return apiFetch<SwingView>(`/api/v1/companies/${companyId}/swing${suffix}`);
}

/** 决策闭环：每只票只能停在一格上，走到下一格需要的东西是机器能判的。 */
export type DecisionBand = { key: string; label: string; means: string };
export type DecisionPlanField = {
  key: string; label: string; kind: string; required: boolean; hint: string;
};
export type DecisionGuard = {
  key: string; label: string; ok: boolean; fix: string;
  /** 这一条补在哪儿。**没有它，"去公司档案的逻辑与证据写下核心主张"
   *  就只是一句话——人得自己找页面、找页签、再往下滚。** */
  goto: { where: "card" | "company" | "portfolio"; tab?: string;
          anchor?: string; label: string } | null;
};
export type DecisionTarget = {
  state: string; label: string; ok: boolean; reason: string;
  missing: { key: string; label: string; fix: string }[];
  /** 这一步要不要你亲手写一句。往前走的那一步不用——机器按"哪几格齐了"自己写。
   *  退回 / 搁置 / 决定买 仍然必须自己写，为什么见 reason_why。 */
  reason_required: boolean;
  reason_why: string;
  /** 留空时机器会写的那一句，提前给页面当占位符——**让人看见它要替你写什么**。 */
  auto_reason: string;
};
export type DecisionMove = {
  from_state: string; to_state: string; actor: string; reason: string;
  price_at_move: number | null; created_at: string;
};
export type DecisionCardView = {
  company_id: number; symbol: string; name: string; industry: string;
  state: string; state_label: string; state_means: string; state_next: string;
  entered_at: string; entered_reason: string; watch_reason: string;
  bands: Record<string, number>; band_specs: DecisionBand[];
  plan_fields: DecisionPlanField[]; position_plan: Record<string, number | string>;
  /** 这一笔打算买什么价、买多少。跟 position_plan 不是一回事（那是整只票的总规划）。 */
  order_fields: DecisionPlanField[]; order_plan: Record<string, number | string>;
  price: number | null; price_date: string | null;
  current_band: string | null; current_band_label?: string;
  last_trigger: { band: string | null; label?: string; price: number | null; date: string | null } | null;
  guards: DecisionGuard[]; targets: DecisionTarget[];
  blocked: { state: string; label: string; reason: string }[];
  checklist: string[]; history: DecisionMove[]; states: Record<string, string>;
  /** 按「我的估值」的基准每股价值推的一组价格带建议。取不到估值时是 null。
   *  **是建议不是推荐买点**：三个系数是人定的规矩，算式跟着一起给。 */
  suggested_bands: SuggestedBands | null;
  /** 每一块各自是什么时候定的、依据哪一期财报。
   *  用的不是整张卡的 updated_at —— 那个会被"今天改了仓位计划"刷掉。 */
  block_stamps: Record<string, { set_at?: string; valuation_saved_at?: string | null;
                                 base_report_date?: string | null; per_share_base?: number | null }>;
  /** 你自己写下的几个数对不对得上（计划价 vs 基准每股价值 vs 合理区）。 */
  reconcile: string[];
  /** 定价格带之后财报换过期了没有。空字符串 = 没过期。 */
  bands_stale: string;
  valuation_per_share_base: number | null;
  valuation_base_report_date: string | null;
  /** 这张卡上登记过的成交。**纪律指标的原料就是它**，所以要看得见、改得掉。 */
  fills: DecisionFill[];
};
export type DecisionFill = {
  id: number; filled_on: string; price: number; shares: number | null;
  /** 登记当时卡上写的计划价，**快照**——卡片之后被改也不影响这条记录。 */
  planned_price: number | null; planned_fraction: string;
  state_then: string; note: string; created_at: string;
};
export type SuggestedBands = {
  bands: Record<string, number>;
  rows: { key: string; value: number; formula: string; means: string }[];
  per_share_base: number;
  safety_margin: number; watch_premium: number; extreme_multiple: number;
  as_of: string | null; base_report_date: string | null;
  is_convention: boolean; note: string;
};
export type DecisionLoopItem = {
  company_id: number; symbol: string; name: string; industry: string;
  state: string; state_label: string; entered_at: string; entered_reason: string;
  watch_reason: string; price: number | null; price_date: string | null;
  bands: Record<string, number>; band: string | null; band_label?: string;
  ideal_low: number | null; ideal_high: number | null;
  total_percent: number | null;
  last_trigger_band: string | null; last_trigger_label?: string;
  last_trigger_price: number | null; last_trigger_date: string | null;
  ready: boolean;
};
export type DisciplineTrade = {
  id: number; company_id: number; company_name: string; symbol: string;
  side: string; trade_date: string; price: number | null; rationale: string;
  band?: string | null; band_label?: string; state_then?: string; why?: string;
  /** 写过计划价就顺带对账：成交价离它多远。 */
  planned_price?: number | null; price_drift?: number | null; fraction?: string | null;
};
export type DecisionLoopView = {
  research: {
    company_id: number; symbol: string; name: string; industry: string; is_sample: number;
    thesis_count: number; latest_claim: string | null; thesis_status: string | null;
    valuation_count: number; report_count: number; report_title: string | null;
    price: number | null; price_date: string | null;
  }[];
  groups: {
    state: string; label: string; means: string; next: string;
    actionable: boolean; items: DecisionLoopItem[]; count: number;
  }[];
  total: number; not_in_loop: number;
  discipline: {
    inside: DisciplineTrade[]; outside: DisciplineTrade[]; undecidable: DisciplineTrade[];
    inside_count: number; outside_count: number; undecidable_count: number;
    sell_count: number; discipline_rate: number | null; sell_note: string;
  };
  states: Record<string, { label: string; means: string; next: string }>;
  state_order: string[];
};

export function getDecisionLoop(): Promise<DecisionLoopView> {
  return apiFetch<DecisionLoopView>("/api/v1/decision-loop");
}
export function evaluateDecisionTriggers(): Promise<{
  count: number;
  moved: { company_id: number; symbol: string; name: string; band_label: string;
           price: number; date: string; note: string }[];
}> {
  return apiFetch("/api/v1/decision-loop/evaluate", { method: "POST" });
}
export function getDecisionCard(companyId: number): Promise<DecisionCardView> {
  return apiFetch<DecisionCardView>(`/api/v1/companies/${companyId}/decision-card`);
}
export function enrollDecisionCard(companyId: number): Promise<DecisionCardView> {
  return apiFetch<DecisionCardView>(`/api/v1/companies/${companyId}/decision-card/enroll`,
    { method: "POST" });
}
export function saveDecisionCard(companyId: number, payload: {
  watch_reason?: string; bands?: Record<string, number | null>;
  position_plan?: Record<string, number | string | null>;
  order_plan?: Record<string, number | string | null>;
}): Promise<DecisionCardView> {
  return apiFetch<DecisionCardView>(`/api/v1/companies/${companyId}/decision-card`,
    { method: "POST", body: JSON.stringify(payload) });
}
export function moveDecisionState(companyId: number, state: string, reason: string):
    Promise<DecisionCardView> {
  return apiFetch<DecisionCardView>(`/api/v1/companies/${companyId}/decision-card/move`,
    { method: "POST", body: JSON.stringify({ state, reason }) });
}

/** 这段涨跌属于什么类型。规则层不花积分；那段解释要花。 */
export type RallyCheck = { text: string; ok: boolean; detail: string };
export type RallyType = {
  key: string; label: string; means: string; for_you: string;
  checks: RallyCheck[]; hit: boolean; hit_count: number; total: number;
};
export type RallyFacts = {
  ok: boolean; note?: string;
  company_id: number; symbol: string; name: string; board?: string;
  limit_percent?: number; window_days?: number; windows?: number[];
  start_date?: string; end_date?: string; start_close?: number; end_close?: number;
  change?: number | null;
  industry?: { name: string | null; peer_count: number; median_change: number | null;
               rank_percentile?: number | null; note?: string };
  /** 同产业链环节的同行（来自 earth-atlas）。**逐家点名，不算中位数** ——
   *  155 个环节里公司数中位只有 2，两家的中位数只是其中一家。 */
  chain_peers?: {
    groups: {
      key: string; chain_label: string; stage: string; segment_label: string; what: string;
      peer_count: number; median_change: number | null; enough: boolean;
      members: { symbol: string; name: string; change: number | null; self: boolean;
                 source_url: string; source_title: string; accessed: string }[];
    }[];
    best: string | null; note: string;
  };
  volume?: { window_avg: number | null; prior_avg: number | null; ratio: number | null };
  limit_up_days?: number; max_limit_streak?: number;
  turnover_rate?: number | null; float_market_cap?: number | null;
  valuation?: {
    pe_start: number | null; pe_end: number | null; pe_change: number | null;
    pe_start_date: string | null; pe_end_date: string | null; pe_end_derived: boolean;
    earnings_share: number | null; report_in_window: boolean; report_dates: string[];
    report_date_caveat: string; pe_percentile_start: number | null; pe_sample: number;
  };
  events?: { event_date: string; title: string; category: string;
             relevance: string; relevance_from?: string; relevance_reason?: string }[];
  event_count?: number; high_relevance_count?: number;
  post_event?: { share: number; day_share: number; covered_days: number;
                 tradable_days: number; lift: number | null; events_used: number } | null;
  /** 池子外的票走全市场底座，少了成交量/公告/估值分位三样——**明写出来，别让人从空值里猜**。 */
  events_available?: boolean;
  source?: string;
  unavailable?: string[];
  enrich_hint?: string;
  requested_window?: number;
};
export type RallyVerdict = {
  ok: boolean; note?: string;
  primary?: string; hit_types?: string[]; floor?: number;
  /** 门槛是按这只票自己的波动算的，还是缺数据退回了通用式子。 */
  floor_basis?: string; prior_daily_sigma?: number | null;
  /** 「行业性」那条判据实际用的是哪个对照组：产业链环节还是申万一级。 */
  peer_source?: string; peer_median?: number | null;
  suppressed_by_floor?: boolean; magnitude?: number;
  types?: RallyType[]; headline?: string; accounting_note?: string;
};
export type RallyNarration = {
  ok: boolean; skipped?: boolean; note?: string;
  story?: string; meaning?: string; what_to_check?: string[];
  untraceable?: string[]; model?: string; credits?: number | null;
};
export type RallyView = {
  facts: RallyFacts; verdict: RallyVerdict;
  types?: { key: string; label: string; means: string; for_you: string }[];
  narration?: RallyNarration;
};

export function getRally(companyId: number, window = 20): Promise<RallyView> {
  return apiFetch<RallyView>(`/api/v1/companies/${companyId}/rally?window=${window}`);
}

/** 按代码查任意一只 A 股。**不要求它在研究池里**——最想问的那几只本来就不在。 */
export function lookupRally(symbol: string, window = 20): Promise<RallyView> {
  return apiFetch<RallyView>(
    `/api/v1/rally?symbol=${encodeURIComponent(symbol)}&window=${window}`);
}
export function narrateRally(companyId: number, window = 20): Promise<RallyView> {
  return apiFetch<RallyView>(
    `/api/v1/companies/${companyId}/rally/narrate?window=${window}`, { method: "POST" });
}


export interface AssistantWebStatus {
  mode: "local" | "guide";
  ready: boolean; configured: boolean; feishu_bound: boolean;
  settings_url: string | null; message: string;
  guide: { title: string; done: boolean; text: string }[];
}
export interface AssistantChatMessage {
  id: string; content: string; company_id: number | null; company_name: string;
  state: "running" | "done" | "interrupted"; answer: string; error: string;
  created_at: string; updated_at: string;
  actions: { operation: string; company_id: number | null; record_id?: string; url?: string }[];
}
export const getAssistantWebStatus = () => apiFetch<AssistantWebStatus>("/api/v1/assistant/web/status");
export const getAssistantMessages = () => apiFetch<AssistantChatMessage[]>("/api/v1/assistant/web/messages");
export const sendAssistantMessage = (payload: { id: string; text: string; company_id: number | null }) =>
  apiFetch<{ id: string }>("/api/v1/assistant/web/messages", {
    method: "POST", headers: { "X-Stock-Chat": "1" }, body: JSON.stringify(payload),
  });

export const connectAssistantFeishu = () => apiFetch<AssistantWebStatus>("/api/v1/assistant/web/connect-feishu", {
  method: "POST", headers: { "X-Stock-Chat": "1" },
});
