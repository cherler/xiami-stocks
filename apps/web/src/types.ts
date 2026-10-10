export type ThesisStatus = "intact" | "watching" | "challenged" | "broken";
export type EvidencePolarity = "support" | "counter" | "neutral";
export type EventImportance = "high" | "medium" | "low";

export interface MarketTile {
  name: string;
  value: number;
  change: number;
  group: string;
}

export interface WatchlistItem {
  id: number;
  symbol: string;
  name: string;
  industry: string;
  thesis_status: ThesisStatus;
  valuation_percentile: number | null;
  roe_trend: string;
  last_reviewed_at: string | null;
  latest_price: number | null;
  change_percent: number | null;
  pe: number | null;
  pb: number | null;
  market_timestamp: string | null;
  market_source: string | null;
}

export interface ThesisItem {
  id: number;
  /** 决策总览要一键跳到公司页——只有 symbol 跳不过去。 */
  company_id: number;
  symbol: string;
  company_name: string;
  claim: string;
  status: ThesisStatus;
  evidence_count: number;
  counter_evidence_count: number;
  next_review_trigger: string;
}

export interface DashboardEvent {
  id: number;
  company_id: number;
  symbol: string;
  company_name: string;
  category: string;
  title: string;
  occurred_at: string;
  importance: EventImportance;
  verification: string;
}

export interface PortfolioExposure {
  name: string;
  weight: number;
}

export interface DashboardSummary {
  as_of: string;
  demo: boolean;
  intact_theses: number;
  theses_to_review: number;
  total_theses: number;
  theses_watching: number;
  next_review_due: string | null;
  unread_events: number;
  data_health: string;
  data_alerts: Array<{ level: string; job_id: string; title: string; detail: string; impact: string }>;
  market_tiles: MarketTile[];
  watchlist: WatchlistItem[];
  theses: ThesisItem[];
  events: DashboardEvent[];
  portfolio_exposure: PortfolioExposure[];
  exposure_basis: string;
  holding_market_value: number | null;
  holding_unrealized_percent: number | null;
  holdings_reviews_due: number;
  inbox_pending: number;
  /** 还没回答的假设漂移问题。藏在公司页里这个机制就废了，所以顶到首页。 */
  /** 未处理的反证命中数。侧栏徽章用它——公告未读数永远清不完，做成红点等于背景色。 */
  counter_hits: number;
  /** 还有多少条待核验公告没被比对过。跟 counter_hits 分开看：
   *  「命中 0」有两种意思——比过了没事、和压根没比过。 */
  counter_uncompared: number;
  /** 有几条判断压根没写认错条件——它们不在网里，反证比对只查写了条件的。 */
  theses_without_counter: number;
  /** 「中」级待核验的积压。**不进首页待办**——它们踩不到你任何一条认错条件。 */
  inbox_backlog: number;
  /** 这一份是不是以游客身份查出来的。游客域一行都匹配不到，返回的是处处为 0
   *  的空档案——**不许长得像"你还没有公司"**，那两件事的下一步完全不同。 */
  viewer_is_guest: boolean;
  drift_questions: {
    company_id: number; company_name: string; symbol: string;
    at: string; level: string; headline: string; question: string;
  }[];
  /** 已经到期、还没人核对的管理层承诺。台账那句「到期顶到你面前」以前没有兑现处：
   *  只有你自己走进那家公司的档案页才看得到。 */
  promises_due: {
    id: number; company_id: number; company_name: string; symbol: string;
    subject: string; statement: string; category: string;
    due_date: string; source_url: string | null;
  }[];
}


/** 全市场底座里的一家公司。搜索栏和建档共用。
 *
 * industry 和 total_market_cap 是给**重名消歧**用的，不是装饰：
 * 「中国电建」和「中国电研」光看名字分不清，看到行业和市值就分得清。 */
export interface UniverseMatch {
  symbol: string;
  name: string;
  industry: string | null;
  board: string;
  exchange: string;
  price: number | null;
  change_percent: number | null;
  total_market_cap: number | null;
  /** 已经在你档案里的话是档案 id，否则 null。 */
  company_id: number | null;
  in_archive: boolean;
}

export interface CompanyRecord {
  id: number;
  symbol: string;
  name: string;
  exchange: string;
  industry: string;
  industry_source: string;
  description: string;
  watch_group: string;
  is_watched: boolean;
  /** 预置的示例档案。看不出是示例的示例，会被当成使用者自己的研究。 */
  is_sample?: boolean;
  valuation_percentile: number | null;
  roe_trend: string;
  latest_price: number | null;
  change_percent: number | null;
  pe: number | null;
  pb: number | null;
  high_52w: number | null;
  low_52w: number | null;
  market_timestamp: string | null;
  market_source: string | null;
  created_at: string;
  updated_at: string;
}

export interface ThesisRecord {
  id: number;
  company_id: number;
  claim: string;
  counter_condition: string;
  status: ThesisStatus;
  next_review_trigger: string;
  created_at: string;
  updated_at: string;
  evidence_count: number;
  counter_evidence_count: number;
  revision_count: number;
}

export interface EvidenceRecord {
  id: number;
  company_id: number;
  thesis_id: number | null;
  source_name: string;
  source_url: string | null;
  excerpt: string;
  polarity: EvidencePolarity;
  occurred_at: string;
  verification: string;
  created_at: string;
}

export interface ResearchEventRecord {
  id: number;
  company_id: number;
  thesis_id: number | null;
  category: string;
  title: string;
  occurred_at: string;
  importance: EventImportance;
  verification: string;
  created_at: string;
}

export interface CompanyDetail extends CompanyRecord {
  theses: ThesisRecord[];
  evidences: EvidenceRecord[];
  events: ResearchEventRecord[];
  profile: CompanyProfileSummary | null;
  valuation: ValuationSummary | null;
  market_history: MarketHistorySummary | null;
  financials: FinancialSummary | null;
  ledger: CompanyLedger | null;
}

export interface CompanyCalendarEvent {
  id: number | null;
  category: string;
  event_date: string;
  title: string;
  detail: string;
  url: string | null;
  source: string;
  upcoming: boolean;
  inbox_status: string;
  archived_as: string | null;
  relevance?: string | null;
}

export interface CompanyProfileSummary {
  full_name: string | null;
  english_name: string | null;
  industry: string | null;
  market: string | null;
  legal_representative: string | null;
  registered_capital: number | null;
  founded_date: string | null;
  listed_date: string | null;
  website: string | null;
  registered_address: string | null;
  office_address: string | null;
  main_business: string | null;
  product_type: string | null;
  business_scope: string | null;
  introduction: string | null;
  total_shares: number | null;
  circulating_shares: number | null;
  share_structure_date: string | null;
  share_change_reason: string | null;
  issue_price: number | null;
  raised_net: number | null;
  underwriter: string | null;
  latest_dividend_period: string | null;
  latest_dividend_plan: string | null;
  latest_dividend_progress: string | null;
  latest_dividend_payout_ratio: string | null;
  latest_dividend_record_date: string | null;
  latest_dividend_ex_date: string | null;
  missing_sections: string[];
  source: string;
  refreshed_at: string;
  upcoming_events: CompanyCalendarEvent[];
  recent_events: CompanyCalendarEvent[];
  event_count: number;
}

export interface CompanyProfileRefreshResult {
  company_id: number;
  refreshed_events: number;
  source: string;
  as_of: string;
}

/** 账本上会发生的六种事。
 *
 * 中间三种不是「你的决定」，而是「发生在你身上的事」。
 * 最后一种连"事"都不是：期初持仓是一句**关于现状的断言**——
 * 「到这天为止我手上有 N 股、均价 P」——它覆盖之前那段流水，不加在上面。
 * 详见后端 schemas.TradeSide.opening。 */
export type TradeSide = "buy" | "sell" | "dividend" | "bonus" | "rights" | "opening";

export const TRADE_SIDE_LABEL: Record<TradeSide, string> = {
  buy: "买入",
  sell: "卖出",
  dividend: "现金分红",
  bonus: "送股转增",
  rights: "配股",
  opening: "持仓对账",
};

/** full = 记股数与价格；ratio = 只记仓位占比，不落任何金额。 */
export type AmountMode = "full" | "ratio";

export interface TradeRecord {
  id: number;
  portfolio_id: number;
  portfolio_name: string;
  company_id: number;
  symbol: string;
  company_name: string;
  thesis_id: number | null;
  side: TradeSide;
  trade_date: string;
  shares: number | null;
  price: number | null;
  fee: number;
  /** ratio 口径下没有金额可谈，是 null 而不是 0——0 会被读成「这笔没花钱」 */
  amount: number | null;
  weight_percent: number | null;
  cash_amount: number | null;
  rationale: string;
  expectation: string;
  review_due: string | null;
  thesis_claim_snapshot: string;
  thesis_status_snapshot: string;
  created_at: string;
  revision_count: number;
}

export interface PositionRecord {
  company_id: number;
  symbol: string;
  company_name: string;
  industry: string;
  shares: number;
  average_cost: number | null;
  cost_value: number;
  latest_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_percent: number | null;
  realized_pnl: number;
  realized_cost: number;
  dividend_income: number;
  cost_after_dividends: number | null;
  weight_percent: number | null;
  weight: number | null;
  first_trade_date: string;
  last_trade_date: string;
  trade_count: number;
  thesis_status: ThesisStatus | null;
  next_review_due: string | null;
  market_timestamp: string | null;
}

export interface PortfolioSummary {
  id: number;
  name: string;
  objective: string;
  amount_mode: AmountMode;
  dividend_income: number;
  created_at: string;
  updated_at: string;
  position_count: number;
  trade_count: number;
  cost_value: number;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_percent: number | null;
  realized_pnl: number;
  largest_weight: number | null;
  top3_weight: number | null;
  priced_positions: number;
  reviews_due: number;
  quote_as_of: string | null;
}

export interface PortfolioDetail extends PortfolioSummary {
  positions: PositionRecord[];
  closed_positions: PositionRecord[];
  trades: TradeRecord[];
}

export interface CompanyLedger {
  shares: number;
  average_cost: number | null;
  cost_value: number;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_percent: number | null;
  realized_pnl: number;
  dividend_income: number;
  cost_after_dividends: number | null;
  total_return: number | null;
  total_return_percent: number | null;
  next_review_due: string | null;
  portfolio_names: string[];
  /** 仓位口径下 shares 永远是 0，要靠这两个字段才知道是"记了 50%"还是"真清仓了"。 */
  weight_percent: number | null;
  amount_mode: string;
  trades: TradeRecord[];
}

export interface PortfolioInput {
  name: string;
  objective: string;
  amount_mode?: AmountMode;
}

export interface PortfolioUpdateInput {
  name?: string;
  objective?: string;
  amount_mode?: AmountMode;
}




export interface TradeInput {
  company_id: number;
  thesis_id?: number | null;
  side: TradeSide;
  trade_date: string;
  shares?: number | null;
  price?: number | null;
  fee?: number;
  weight_percent?: number | null;
  cash_amount?: number | null;
  rationale?: string;
  expectation?: string;
  review_due?: string | null;
}

export interface PriceBar {
  trade_date: string;
  close: number;
  high: number | null;
  low: number | null;
  change_percent: number | null;
}

export interface MarketHistorySummary {
  source: string;
  adjusted: string;
  refreshed_at: string;
  latest_trade_date: string;
  price_5d_change: number | null;
  price_20d_change: number | null;
  ytd_change: number | null;
  one_year_change: number | null;
  bars: PriceBar[];
}

export interface MarketHistoryRefreshResult {
  company_id: number;
  refreshed_bars: number;
  source: string;
  as_of: string;
}

export interface FinancialPeriod {
  report_date: string;
  revenue: number | null;
  net_profit: number | null;
  operating_cash_flow: number | null;
  operating_cost: number | null;
  rnd_expense: number | null;
  capex: number | null;
  receivables: number | null;
  inventory: number | null;
  interest_bearing_debt: number | null;
  total_assets: number | null;
  total_liabilities: number | null;
  equity: number | null;
  debt_ratio: number | null;
  roe_estimate: number | null;
  currency: string | null;
  audit_status: string | null;
  announcement_date: string | null;
  gross_margin: number | null;
  net_margin: number | null;
  free_cash_flow: number | null;
  cash_conversion: number | null;
  interest_debt_ratio: number | null;
  rnd_ratio: number | null;
  receivable_days: number | null;
  inventory_days: number | null;
  revenue_ttm: number | null;
  net_profit_ttm: number | null;
  ttm_basis: string | null;
}

export interface FinancialMetricCard {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  basis: string;
  previous_annual: number | null;
  previous_annual_date: string | null;
  unavailable_reason: string | null;
}

export interface FinancialWarning {
  level: string;
  title: string;
  detail: string;
}

export interface FinancialSummary {
  source: string;
  refreshed_at: string;
  latest_report_date: string;
  latest_audit_status: string;
  latest_annual_roe_report_date: string | null;
  roe_reference_value: number | null;
  roe_reference_report_date: string | null;
  roe_reference_source: string | null;
  periods: FinancialPeriod[];
  metrics: FinancialMetricCard[];
  warnings: FinancialWarning[];
}

export interface FinancialRefreshResult {
  company_id: number;
  refreshed_periods: number;
  source: string;
  as_of: string;
}

export interface CompanyInput {
  symbol: string;
  name: string;
  industry: string;
  description: string;
  watch_group: string;
  valuation_percentile?: number | null;
  roe_trend: string;
}

export interface CompanyFromQuoteInput {
  symbol: string;
  watch_group: string;
  description?: string;
}

export interface QuotePreview {
  symbol: string;
  name: string;
  exchange: string;
  price: number | null;
  change_percent: number | null;
  pe: number | null;
  pb: number | null;
  market_timestamp: string | null;
  source: string;
}

export interface DataProviderStatus {
  provider_id: string;
  display_name: string;
  category: string;
  last_status: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  refreshed_items: number;
}

export interface ThesisInput {
  claim: string;
  counter_condition: string;
  status: ThesisStatus;
  next_review_trigger: string;
}

export interface EvidenceInput {
  thesis_id?: number | null;
  source_name: string;
  source_url?: string;
  excerpt: string;
  polarity: EvidencePolarity;
  verification: string;
}

export interface ResearchEventInput {
  thesis_id?: number | null;
  category: string;
  title: string;
  importance: EventImportance;
  verification: string;
}

export interface RecordRevision {
  id: number;
  entity_type: string;
  entity_id: number;
  version: number;
  snapshot: Record<string, unknown>;
  changed_fields: string;
  change_note: string;
  created_at: string;
}

export interface ThesisUpdateInput {
  claim?: string;
  counter_condition?: string;
  status?: ThesisStatus;
  next_review_trigger?: string;
  change_note?: string;
}

export interface TradeUpdateInput {
  rationale?: string;
  expectation?: string;
  review_due?: string | null;
  change_note?: string;
}

export interface BackupManifest {
  name: string;
  created_at: string;
  schema_version: number;
  size: number;
  note: string;
  reason: string;
  counts: Record<string, number>;
}

export interface BackupRestoreResult {
  restored_from: string;
  safety_backup: string;
  schema_version: number;
  before_counts: Record<string, number>;
  restored_counts: Record<string, number>;
  mismatched: Record<string, { backup: number; restored: number }>;
  verified: boolean;
}

/** 代码在写、库里却基本没有的列。缺列不会报错，只会让下游判断悄悄失去依据。 */
export interface Freshness {
  stale: boolean;
  findings: { table: string; column: string; filled: number; total: number; ratio: number }[];
  actions: { table: string; columns: string[]; how: string }[];
  note: string;
}

export interface LocalDataSummary {
  freshness: Freshness;
  database_path: string;
  database_size: number;
  schema_version: number;
  expected_schema_version: number;
  authored_counts: Record<string, number>;
  source_counts: Record<string, number>;
  backup_count: number;
  latest_backup_at: string | null;
  backup_directory: string;
}

export interface ValuationPoint {
  point_date: string;
  value: number;
}

export interface ValuationWindow {
  window_years: number;
  sample_size: number;
  sample_start: string | null;
  sample_end: string | null;
  percentile: number | null;
  minimum: number | null;
  median: number | null;
  maximum: number | null;
  unavailable_reason: string | null;
  /** 样本实际横跨几年。跟 window_years 不是一回事——序列可能根本没那么长。 */
  covered_years: number | null;
  /** 没铺满窗口时的那句话。有它就说明这个分位不能当成 N 年历史位置读。 */
  coverage_note: string | null;
}

export interface ValuationMetric {
  metric: string;
  label: string;
  current: number | null;
  current_date: string | null;
  windows: ValuationWindow[];
  history: ValuationPoint[];
}

export interface ValuationSummary {
  source: string;
  refreshed_at: string;
  metrics: ValuationMetric[];
  local_snapshot_days: number;
  local_snapshot_start: string | null;
}

export interface ValuationRefreshResult {
  company_id: number;
  refreshed_points: number;
  source: string;
  as_of: string;
}

export interface InboxItem {
  id: number;
  company_id: number;
  symbol: string;
  company_name: string;
  category: string;
  event_date: string;
  title: string;
  detail: string;
  url: string | null;
  source: string;
  inbox_status: string;
  archived_as: string | null;
  archived_ref_id: number | null;
  handled_at: string | null;
  relevance: string | null;
  relevance_reason: string | null;
  relevance_source: string | null;
  relevance_topic: string | null;
  summary: string | null;
}

export interface Billing {
  /** false = 这次根本没计费（本地单机、未登录、闸口不可达），不要显示成「0 分」 */
  metered: boolean;
  credits: number;
  tokens: number;
  calls: number;
}

export interface CreditState {
  connected: boolean;
  module: string;
  balance: number | null;
  available: number | null;
  note: string;
  pricing: { token_bucket: number; multiplier: number; formula: string } | null;
}

export interface InboxClassifyResult {
  scanned: number;
  by_rules: number;
  by_model: number;
  uncertain: number;
  counts: Record<string, number>;
  note: string;
  billing: Billing;
}

export interface InboxPage {
  items: InboxItem[];
  total: number;
  in_window: number;
  ungraded: number;
  high: number;
  medium: number;
  low: number;
  window_days: number | null;
  since: string | null;
}

export interface InboxArchiveInput {
  target: "evidence" | "event";
  thesis_id?: number | null;
  polarity?: EvidencePolarity;
  importance?: EventImportance;
  verification?: string;
  note?: string;
}

export interface InboxActionResult {
  item: InboxItem;
  created_type: string;
  created_id: number;
}

export interface SyncJobStatus {
  job_id: string;
  display_name: string;
  category: string;
  description: string;
  interval_minutes: number;
  weekdays_only: boolean;
  enabled: boolean;
  freshness_hours: number;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_success_at: string | null;
  last_status: string;
  last_error: string | null;
  last_items: number;
  next_run_at: string | null;
  consecutive_failures: number;
  health: string;
  health_message: string;
  age_hours: number | null;
  /** 这个任务算不算「需要关注」。**判定在后端做**——前端原来自己列了一份
   *  「哪几种算有问题」的名单，少了「降级」，于是首页说有事、点进去说全正常。 */
  needs_attention: boolean;
}

export interface SyncJobUpdateInput {
  enabled?: boolean;
  interval_minutes?: number;
}

export interface SyncRunRecord {
  id: number;
  job_id: string;
  display_name: string | null;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  items: number;
  failures: number;
  error: string | null;
  detail: string;
}

export interface SyncRunResult {
  job_id: string;
  status: string;
  items: number;
  failures: number;
  detail: string;
  error: string | null;
  started_at: string;
  finished_at: string;
  next_run_at: string;
}

export type ReviewVerdict = "supported" | "challenged" | "broken" | "watching";

export interface ReviewQueueItem {
  thesis_id: number;
  company_id: number;
  symbol: string;
  company_name: string;
  claim: string;
  counter_condition: string;
  status: ThesisStatus;
  next_review_trigger: string;
  next_review_date: string | null;
  last_reviewed_at: string | null;
  created_at: string;
  new_counter_evidence: number;
  new_support_evidence: number;
  new_high_events: number;
  trade_review_due: string | null;
  review_count: number;
  has_position: boolean;
  reasons: string[];
  due_since: string;
}

export interface ThesisReviewRecord {
  id: number;
  thesis_id: number;
  company_id: number;
  verdict: ReviewVerdict | string;
  verdict_label: string | null;
  note: string;
  previous_status: string;
  new_status: string;
  next_review_date: string | null;
  thesis_version: number | null;
  support_evidence: number;
  counter_evidence: number;
  event_count: number;
  price_at_review: number | null;
  pe_percentile_at_review: number | null;
  unrealized_at_review: number | null;
  realized_at_review: number | null;
  created_at: string;
  claim: string | null;
  symbol: string | null;
  company_name: string | null;
}

export interface ThesisReviewContext {
  thesis: Record<string, unknown>;
  since: string;
  revisions: Array<{ version: number; snapshot: Record<string, unknown>; changed_fields: string; change_note: string; created_at: string }>;
  evidences: Array<EvidenceRecord & { since_last_review: boolean }>;
  events: Array<ResearchEventRecord & { since_last_review: boolean }>;
  trades: TradeRecord[];
  position: PositionRecord | null;
  price: {
    latest: number | null;
    change_percent: number | null;
    market_timestamp: string | null;
    price_20d_change: number | null;
    ytd_change: number | null;
    one_year_change: number | null;
    latest_trade_date: string | null;
  };
  valuation: Array<{ label: string; current: number | null; percentile: number | null; sample_note: string | null }>;
  reviews: ThesisReviewRecord[];
}

export interface ThesisReviewInput {
  verdict: ReviewVerdict;
  note: string;
  new_status?: ThesisStatus | null;
  next_review_date?: string | null;
  next_review_trigger?: string | null;
}

export interface ReviewQuarter {
  period: string;
  supported: number;
  challenged: number;
  broken: number;
  watching: number;
  total: number;
  realized: number;
  unrealized: number;
  reviews: ThesisReviewRecord[];
}

export interface ReviewAttribution {
  quarters: ReviewQuarter[];
  total_reviews: number;
  by_method: MethodAttribution[];
}

export interface WatchGroupSummary {
  name: string;
  watched: number;
  archived: number;
}

export interface WatchlistImportRow {
  symbol: string;
  watch_group?: string | null;
  description?: string | null;
  industry?: string | null;
  is_watched?: boolean | null;
}

export interface WatchlistImportInput {
  symbols?: string[];
  rows?: WatchlistImportRow[];
  watch_group?: string;
  description?: string;
  restore_existing?: boolean;
}

export interface WatchlistImportResult {
  created: number;
  skipped: number;
  updated: number;
  failed: number;
  results: Array<{ symbol: string; status: string; detail: string }>;
}

export interface CompanyPatch {
  watch_group?: string;
  is_watched?: boolean;
  industry?: string;
  description?: string;
}

export interface IndustrySummary {
  name: string;
  company_count: number;
  watched_count: number;
  companies: string | null;
}

export interface PeerValuation {
  current: number | null;
  percentile: number | null;
  note: string | null;
}

export interface PeerFinancials {
  report_date: string | null;
  gross_margin: number | null;
  net_margin: number | null;
  cash_conversion: number | null;
  debt_ratio: number | null;
  interest_debt_ratio: number | null;
  roe_estimate: number | null;
  roe_report_date: string | null;
  revenue_growth: number | null;
  revenue_growth_basis: string | null;
  note: string | null;
}

export interface PeerCompany {
  id: number;
  symbol: string;
  name: string;
  industry: string;
  industry_source: string;
  is_watched: boolean;
  latest_price: number | null;
  change_percent: number | null;
  market_timestamp: string | null;
  valuation: Record<string, PeerValuation>;
  financials: PeerFinancials;
}

export interface IndustryAggregate {
  sample_count: number;
  latest_price: number | null;
  pe_ttm: number | null;
  pe_ttm_percentile: number | null;
  pb: number | null;
  pb_percentile: number | null;
  roe_estimate: number | null;
  gross_margin: number | null;
  net_margin: number | null;
  cash_conversion: number | null;
  debt_ratio: number | null;
  revenue_growth: number | null;
  coverage: Record<string, number>;
}

export interface IndustryComparison {
  industry: string | null;
  benchmark_company_count: number;
  benchmark_source: string;
  benchmark_as_of: string | null;
  company_count: number;
  coverage: string;
  industry_basis: string;
  companies: PeerCompany[];
  average: IndustryAggregate;
  lower_quartile: IndustryAggregate;
  median: IndustryAggregate;
  upper_quartile: IndustryAggregate;
}

export interface UniverseSnapshotRecord {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  price_rows: number;
  fundamental_rows: number;
  index_rows: number;
  price_source: string | null;
  fundamental_source: string | null;
  report_date: string | null;
  degraded: boolean;
  note: string;
}

export interface UniverseSummary {
  total: number;
  boards: Array<{ name: string; count: number }>;
  indexes: Array<{ index_code: string; index_name: string; count: number }>;
  completeness: Array<{ field: string; label: string; filled: number; ratio: number }>;
  last_snapshot: UniverseSnapshotRecord | null;
  report_date: string | null;
  valuation_history_days: number;
  valuation_history_start: string | null;
  valuation_history_note: string;
  coverage: string;
}

export interface ScreenRule {
  field: string;
  op: string;
  value: number;
  unit: string;
  text: string | null;
}

export interface ScreenStrategy {
  key: string;
  name: string;
  summary: string;
  provenance: string;
  biases: string[];
  rules: ScreenRule[];
  sort_field: string;
  sort_desc: boolean;
  sort_label: string;
  preset: boolean;
  /** 价值口味还是趋势口味。**后端从规则用的字段推出来**（Strategy.kind），
   *  接口一直在返回，前端类型里一直漏了这一个键。荐股池按它分池，
   *  候选清单按它分组——两处都不该在前端另编一份名单。 */
  kind: "value" | "trend";
  forked_from: string | null;
  required_fields: string[];
  available: boolean;
  unavailable_reason: string | null;
}

export interface ScreenCheck {
  rule: string;
  field: string;
  label: string;
  actual: number | null;
  passed: boolean;
  missing: boolean;
}

export interface ScreenCandidate {
  symbol: string;
  name: string;
  board: string;
  industry: string | null;
  price: number | null;
  change_percent: number | null;
  total_market_cap: number | null;
  report_date: string | null;
  price_as_of: string | null;
  in_indexes: string[];
  in_research_pool: boolean;
  also_matched: string[];
  sort_value: number | null;
  checks: ScreenCheck[];
}

export interface ScreenResult {
  strategy: ScreenStrategy;
  universe_total: number;
  matched: number;
  returned: number;
  /** 两级排序都写出来：第一关键字是「被几套策略同时选中」，第二才是策略声明的字段 */
  sort_explain: string;
  report_date: string | null;
  price_as_of: string | null;
  candidates: ScreenCandidate[];
  boundary: string;
  billing: Billing;
}

/* ── AI 选股 ─────────────────────────────────────────────────────────
 * 一句话 → 模型翻成条件 → 代码在全 A 上筛 → 模型从命中里挑。
 * **筛选是代码做的**：模型两头只碰文字，中间那 5541 行数据它一行都看不到。 */

export interface AiPickAsk {
  /** 按钮上印的四五个字。整句在 text 里——按钮上直接印整句时，
   *  五条并排是一堵墙，使用者的原话是「我看的都没兴趣去用了」。 */
  short: string;
  text: string;
  /** 这条问法要联网才成立（概念、题材这类库里没有字段的东西） */
  web: boolean;
  usable: boolean;
  unavailable_reason: string;
}

export interface AiPickOptions {
  asks: AiPickAsk[];
  web_available: boolean;
  web_reason: string;
}

export interface AiPickPlan {
  name: string;
  summary: string;
  rules: ScreenRule[];
  sort_field: string;
  sort_desc: boolean;
  sort_label: string;
  industries: string[];
  theme: string;
  theme_queries: string[];
  /** 模型自己说它把这句话理解成了什么。**要显示**——用户靠它判断有没有理解错 */
  reading: string;
  /** 校验时丢掉了什么。**丢了不说，用户会以为那条生效了** */
  dropped: string[];
}

export interface AiPickChoice {
  symbol: string;
  name: string | null;
  industry: string | null;
  price: number | null;
  change_percent: number | null;
  total_market_cap: number | null;
  in_research_pool: boolean;
  why: string;
  reasons: string[];
  concerns: string[];
  checks: ScreenCheck[];
  /** 概念名单里它是被哪篇文章提到的。点得进去 */
  /** 概念名单命中时，那篇文章里的**原文那一句**。
   *  只给链接不给原文，等于要求人点进去才能判断——而这一层的匹配是会错的
   *  （「eVTOL、机器人等细分场景」匹配出了公司「机器人」），
   *  原文摆在这里，一眼就能看出是不是误伤。 */
  theme_sources: { title: string; url: string; quote?: string }[];
}

export interface AiPickResult {
  question: string;
  plan: AiPickPlan;
  web: {
    used: boolean;
    queries: string[];
    hits: number;
    matched: number;
    note: string;
    sources: { title: string; url: string; kind: string }[];
  };
  screened: {
    universe_total: number;
    /** 这次实际在多大范围里筛的：限定了概念或行业时会小于全 A */
    searched_in: number;
    matched: number;
    returned: number;
    sort_explain: string;
    report_date: string | null;
  };
  savable: { name: string; rules: ScreenRule[]; sort_field: string; sort_desc: boolean; sort_label: string };
  rows: ScreenCandidate[];
  picks: AiPickChoice[];
  passed: { symbol: string; name: string; why: string }[];
  note: string;
  boundary: string;
  model?: string;
}

export interface ScreenField {
  field: string;
  label: string;
  unit: string;
  hint: string;
  derived: boolean;
  coverage: number;
  usable: boolean;
}

export interface ScreenStrategySaveInput {
  key: string;
  name: string;
  summary?: string;
  rules: Array<{ field: string; op: string; value: number; unit: string }>;
  sort_field: string;
  sort_desc: boolean;
  sort_label?: string;
  forked_from?: string | null;
}

export interface ScreenAdHocInput {
  name?: string;
  rules: Array<{ field: string; op: string; value: number; unit: string }>;
  sort_field: string;
  sort_desc: boolean;
  forked_from?: string | null;
}

export interface HeatmapTile {
  name: string;
  symbol: string | null;
  industry: string | null;
  size: number;
  metric_value: number | null;
  count: number;
  watched: Array<{ company_id: number; symbol: string; name: string }>;
}

export interface HeatmapView {
  /** 这份底座数据自己的时间（到秒）。**不是今天** —— 它由计划任务刷。 */
  as_of?: string;
  /** 行情来源。降级时是「新浪全市场快照（降级）」。 */
  source?: string;
  /** 主源连不上、退到了只有价格的备用源。**面积与估值那几个镜头会失真。** */
  degraded?: boolean;
  missing_fields?: string[];
  scope: string;
  scope_label: string;
  level: string;
  metric: string;
  metric_label: string;
  metric_unit: string;
  metric_kind: string;
  metric_note: string;
  aggregation: string;
  universe_total: number;
  with_metric: number;
  size_basis: string;
  tiles: HeatmapTile[];
  indexes: Array<{ index_code: string; index_name: string; count: number }>;
  coverage: string;
  boundary: string;
  breadth: { advancing: number; declining: number; unchanged: number; median_change: number | null; covered: number; note: string } | null;
  scopes: Array<{ key: string; label: string; group: string; count: number | null }>;
}

export interface MarketLensStatus {
  metric: string;
  available: boolean;
  filled: number;
  trading_days: number;
  required_days: number | null;
  message: string;
}

export interface MarketFundFlowPoint {
  date: string;
  main_net_inflow: number | null;
  main_net_inflow_percent: number | null;
  super_large_net_inflow: number | null;
  large_net_inflow: number | null;
  medium_net_inflow: number | null;
  small_net_inflow: number | null;
  sh_close: number | null;
  sh_change_percent: number | null;
  sz_close: number | null;
  sz_change_percent: number | null;
}

export interface MarketFundFlowView {
  source: string;
  as_of: string;
  unit: string;
  points: MarketFundFlowPoint[];
  boundary: string;
}

export interface ResearchTaskItem {
  id: number;
  task_id: number;
  symbol: string;
  name: string;
  industry: string | null;
  evidence: Array<{ label: string; actual: number | null; rule: string }>;
  status: string;
  note: string;
  /** 模型初筛的结论：值得深入 / 先放着 / 直接排除。没跑过初筛就是空串。 */
  verdict: string;
  /** 模型初筛写的结论。跟 note 分开——note 是你自己写的一句话。 */
  conclusion: string;
  reasons: string[];
  concerns: string[];
  /** 方法体检结果。没跑过就是空数组。 */
  assessment: Array<{
    method_key: string; method_name?: string; category?: string;
    verdict: string; summary?: string; gaps?: string[];
    evidence?: Array<{ fact?: string; value?: string; as_of?: string }>;
  }>;
  assessed_at: string;
  company_id: number | null;
  brief: string;
  brief_source: string;
  links: Array<{ label: string; url: string }>;
  reports: Array<{ title: string; org: string; rating: string | null; date: string; url: string | null }>;
  updated_at: string;
}

export interface ResearchTaskRecord {
  id: number;
  title: string;
  source: string;
  strategy_key: string | null;
  strategy_name: string | null;
  rules: Array<Record<string, unknown>>;
  data_note: string;
  status: string;
  conclusion: string;
  due_date: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  total: number;
  pending: number;
  adopted: number;
  dropped: number;
  items: ResearchTaskItem[];
}

export interface ThesisMethodSummary {
  key: string;
  name: string;
  category: string;
  category_label: string;
  one_liner: string;
  core_question: string;
  beginner: boolean;
  effort: string;
  related_strategy: string | null;
}

export interface ThesisMethod extends ThesisMethodSummary {
  origin: string;
  steps: string[];
  claim_template: string;
  counter_template: string;
  trigger_template: string;
  fits: string[];
  not_fits: string[];
  caution: string;
}

export interface ThesisMethodCategory {
  key: string;
  label: string;
  intro: string;
  methods: ThesisMethodSummary[];
}

export interface ThesisMethodLibrary {
  categories: ThesisMethodCategory[];
  boundary: string;
}

/** 可分块渲染的那一份。平文本的 claim / counter_condition 仍然保留，取不到结构就回落。 */
export interface ThesisStructure {
  headline: string;
  basis: { point: string; evidence: string; as_of: string }[];
  counters: { metric: string; threshold: string; means: string }[];
  review: { when: string; what: string[] };
}

export interface ThesisDraft {
  claim: string;
  counter_condition: string;
  next_review_trigger: string;
  structure: ThesisStructure;
  used_facts: string[];
  unknowns: string[];
  trackable_fields: string[];
  model: string;
  method: string | null;
  boundary: string;
  billing: Billing;
  /** 它自己查了哪几张表。模型不支持工具、回落到固定资料时，这里说明为什么。 */
  read: string;
}

export interface InboxTidyResult {
  classified: number;
  by_model: number;
  archived: number;
  ignored: number;
  remaining: number;
  note: string;
}

export interface NewsItem {
  id: number; feed_key: string; feed_name: string; title: string; url: string; summary: string;
  published_at: string; company_id: number | null; company_name: string | null; symbol: string | null;
  match_confidence: string; match_reason: string; match_source: string; status: string; read_at: string | null;
}
export interface NewsPage {
  items: NewsItem[];
  total: number;
  linked: number;
  boundary: string;
  /** 全量状态计数，和当前选中的列表状态无关。 */
  all: number;
  pending: number;
  archived: number;
  ignored: number;
  read: number;
  unread: number;
}
export interface NewsRefreshResult { fetched: number; matched: number; failures: string[]; note: string; billing: Billing; }
export interface SupplyChainLink {
  id: number; company_id: number; relation: string; counterpart: string; segment: string;
  /** 图上的短名，后端从 counterpart 派生（库里那一栏常常是整段描述）。 */
  label: string;
  detail: string; confidence: string; source: string; evidence_id: number | null; created_at: string;
}
export interface SupplyChainView { links: SupplyChainLink[]; confirmed: number; boundary: string; billing: Billing; }

/** 按环节横排:同一条链上,每个环节里的公司并排比估值与盈利。 */
export interface ChainCompareCompany {
  company_id: number;
  symbol: string;
  company: string;
  price: number | null;
  pe_ttm: number | null;
  pb: number | null;
  total_market_cap: number | null;
  revenue: number | null;
  net_profit: number | null;
  roe: number | null;
  gross_margin: number | null;
  revenue_growth: number | null;
  net_profit_growth: number | null;
  dividend_yield: number | null;
  change_20d: number | null;
  change_60d: number | null;
  ytd_change: number | null;
  sw_level1: string | null;
  sw_level2: string | null;
  fundamental_as_of: string | null;
  detail: string;
  source_url: string;
  verification: string;
}

export interface ChainCompareNode {
  node_id: number;
  node: string;
  stage: string;
  what: string;
  count: number;
  market_cap_sum: number | null;
  revenue_sum: number | null;
  net_profit_sum: number | null;
  revenue_count: number;
  profit_count: number;
  /** 环节市销率 = 合计市值 ÷ 合计营收,只算两边都有数的公司 */
  ps: number | null;
  ps_count: number;
  pe_median: number | null;
  pb_median: number | null;
  roe_median: number | null;
  gross_margin_median: number | null;
  /** 这一环有几家取不到行情——不露出来的话,中位数会被悄悄算在少数几家身上 */
  missing_quote: number;
  /** 这一环的市场盘子(亿元人民币)+ 口径 + 出处;没有就是 null,别当成「不拥挤」 */
  market_size_cny_yi: number | null;
  market_size_basis: string;
  market_size_source_url: string;
  /** 环节拥挤度 = 这一环 A 股合计市值 ÷ 市场盘子 */
  crowding: number | null;
  companies: ChainCompareCompany[];
}

export interface ChainCompareView {
  theme_id: number;
  theme: string;
  description: string;
  node_count: number;
  company_count: number;
  /** 每一列非空的个数;整列为 0 的指标会被收起并注明原因 */
  coverage: Record<string, number>;
  nodes: ChainCompareNode[];
}

export interface IndustryChainThemeSummary {
  id: number; name: string; chain_type: string; description: string;
  is_default: boolean;
  category: string; recommended: boolean; recommendation_score: number; recommendation_reason: string;
  stage_count: number; node_count: number; company_count: number; updated_at: string;
}

export interface IndustryChainCompanyPosition {
  id: number; company_id: number; company_name: string; symbol: string; node_id: number;
  role: string; detail: string; source_name: string; source_url: string;
  verification: string; valid_from: string | null; valid_to: string | null;
}

export interface IndustryChainNode {
  id: number; theme_id: number; stage_id: number; parent_id: number | null;
  name: string; node_type: string; description: string; source_name: string;
  source_url: string; verification: string; node_order: number;
  positions: IndustryChainCompanyPosition[];
}

export interface IndustryChainStage {
  id: number; theme_id: number; name: string; stage_kind: string;
  description: string; stage_order: number; nodes: IndustryChainNode[];
}

export interface IndustryChainEdge {
  id: number; theme_id: number; from_node_id: number; to_node_id: number;
  relation_type: string; detail: string; source_name: string; source_url: string;
  verification: string;
}

export interface IndustryChainView {
  id: number; name: string; chain_type: string; description: string;
  is_default: boolean;
  stages: IndustryChainStage[]; edges: IndustryChainEdge[];
  node_count: number; company_count: number; boundary: string;
  created_at: string; updated_at: string;
}

export interface CompanyIndustryChainPositions {
  company_id: number;
  themes: Array<{
    theme_id: number; theme_name: string; chain_type: string;
    positions: Array<{
      id: number; node_id: number; node_name: string; node_type: string; stage_name: string;
      role: string; detail: string; source_name: string; source_url: string;
      verification: string; valid_from: string | null; valid_to: string | null;
    }>;
  }>;
}
export interface ResearchReport {
  id: number; company_id: number; company_name: string; symbol: string; version: number;
  title: string; body: string;
  /** 三节各是一句一条。老简报这三个是空数组，页面回退到 body。 */
  business: string[]; changes: string[]; implications: string[];
  /** 深度报告（联网那一版）。老报告 kind='local'，这几项是空的，页面回落旧版式。 */
  kind: string;
  cards: Array<{ title: string; point: string; refs: number[] }>;
  sections: Array<{ title: string; lines: string[] }>;
  themes: Array<{ name: string; direction: string; refs: number[] }>;
  sources: Array<{ ref: number; kind: string; title: string; url: string;
                   published: string; snippet: string; tier?: string }>;
  queries: string[];
  facts: Record<string, unknown>;
  citations: Array<{ ref?: number; label?: string }>; unknowns: string[];
  source_count: number; model: string; created_at: string; billing: Billing;
}
export interface BackgroundJob {
  id: number; kind: string; target_id: number; label: string; status: string;
  progress: number; total: number; note: string; error: string;
  created_at: string; updated_at: string; started_at: string | null; finished_at: string | null;
  credits: number; tokens: number; metered: boolean;
  /** 任务的结构化产出（读图结果这类）。没有就是 null。 */
  result: Record<string, unknown> | null;
}

export interface IndustryChainDraftResult {
  theme_id: number; theme_name: string; stages: number; nodes: number; edges: number;
  sources: number; primary_sources: number; queries: string[]; search_failures: string[];
  unknowns: string[]; model: string; boundary: string;
}
export interface TaskAutoReviewResult { reviewed: number; counts: Record<string, number>; note: string; }

export interface UniverseRederiveResult {
  derived: number; total: number; pe_coverage: number; pb_coverage: number;
  market_cap_coverage: number; note: string;
}

export interface NewsFeed {
  id: number; key: string; name: string; url: string; enabled: boolean; builtin: boolean;
  last_ok_at: string | null; last_error: string; item_count: number;
}

export interface DailyBriefing {
  as_of: string; headline: string; market: string; holdings: string; pending: string;
  watchlist: string; actions: string[]; gaps: string[]; boundary: string; model: string; created_at: string;
  billing: Billing;  /** 生成这份简报时代码算好的那批数。页面靠它画图，不靠模型复述。 */
  context?: import("./components/BriefingCharts").BriefingContext | null;
}

/** 分级引擎从你的纠错里学到的候选词。**只提议，不自动生效。** */
export interface LearnedTerm {
  term: string;
  relevance: string;
  corrections: number;
  also_in_agreed: number;
  examples: string[];
}

export interface RuleTerm {
  term: string;
  relevance: string;
  topic: string;
  note: string;
  hits: number;
  created_at: string;
}

export interface InboxLearning {
  total: number;
  by_direction: Array<{ was_relevance: string; now_relevance: string; c: number }>;
  suggestions: LearnedTerm[];
  terms: RuleTerm[];
}

export interface MethodAttribution {
  method: string;
  total: number;
  intact: number;
  watching: number;
  challenged: number;
  broken: number;
  settled: number;
  hit_rate: number | null;
  note: string;
}

/** 决策看板的一行。每一格都是已发生的事实或已到期的约定，**没有一格是预测**。 */
export interface DecisionRow {
  company_id: number;
  symbol: string;
  name: string;
  industry: string | null;
  watch_group: string;
  latest_price: number | null;
  change_percent: number | null;
  pe: number | null;
  pb: number | null;
  quote_as_of: string | null;
  thesis_count: number;
  thesis_status: ThesisStatus | null;
  claim: string;
  counter_condition: string;
  method_name: string | null;
  counter_evidence: number;
  pending_events: number;
  reviews_due: number;
  next_review_date: string | null;
  held: boolean;
  weight: number | null;
  unrealized_percent: number | null;
  action: string;
  /** 反证 / 复核 / 公告 / 补全 / 无 —— 只用于分组与配色 */
  action_kind: string;  assessed: boolean;
  adverse_methods: number;
}

export interface DecisionBoard {
  as_of: string;
  rows: DecisionRow[];
  todo_count: number;
  held_count: number;
  boundary: string;
}
