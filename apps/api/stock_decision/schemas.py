from datetime import date, datetime
from enum import Enum

try:                                    # Python 3.11+
    from enum import StrEnum
except ImportError:                     # 3.10：服务器上就是 3.10，后端也跑在这个版本
    # StrEnum 是 3.11 才有的。它等价于「同时继承 str 和 Enum」——
    # 值就是字符串本身，能直接参与比较、拼接与 JSON 序列化。
    # 为一个能两行补上的类去给服务器装新 Python，代价与风险都不划算。
    class StrEnum(str, Enum):           # type: ignore[no-redef]
        def __str__(self) -> str:
            return str(self.value)
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ThesisStatus(StrEnum):
    intact = "intact"
    watching = "watching"
    challenged = "challenged"
    broken = "broken"


class EvidencePolarity(StrEnum):
    support = "support"
    counter = "counter"
    neutral = "neutral"


class EventImportance(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class CompanyInput(BaseModel):
    # **A 股代码就是六位数字。** 2026-08-19 巡检实测：`ABCDEF`、`60051🍤`
    # 都能建成档案，而且被 exchange_for_symbol 推断出了交易所 ——
    # 那个函数的注释写着「exchange is a deterministic property of the six-digit code」，
    # 前提却从来没人保证。垃圾代码进来之后，交易所字段是错的，行情永远同步不到。
    #
    # 这里只管"格式对不对"；"这个代码真的存在吗"由建档时的行情校验管，那是两件事。
    symbol: str = Field(pattern=r"^\d{6}$", description="六位数字的 A 股代码")
    name: str = Field(min_length=1, max_length=60)
    industry: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=600)
    watch_group: str = Field(default="观察池", min_length=1, max_length=30)
    valuation_percentile: int | None = Field(default=None, ge=0, le=100)
    roe_trend: str = Field(default="待补充", max_length=80)


class CompanyFromQuoteInput(BaseModel):
    """Create a research archive from a real-time quote, never user-supplied company facts."""

    # 六位数字，理由见 CompanyInput.symbol
    symbol: str = Field(pattern=r"^\d{6}$")
    watch_group: str = Field(default="观察池", min_length=1, max_length=30)
    description: str = Field(default="", max_length=600)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    industry: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=600)
    watch_group: str | None = Field(default=None, min_length=1, max_length=30)
    is_watched: bool | None = None
    valuation_percentile: int | None = Field(default=None, ge=0, le=100)
    roe_trend: str | None = Field(default=None, max_length=80)


class CompanyRecord(BaseModel):
    id: int
    symbol: str
    name: str
    exchange: str
    industry: str
    industry_source: str = "待补充"
    description: str
    watch_group: str
    is_watched: bool
    # 预置的示例档案。**页面上要带记号**——看不出是示例的示例会被当成
    # 使用者自己的研究，而他会以为自己已经写过三条判断了。
    is_sample: bool = False
    valuation_percentile: int | None
    roe_trend: str
    latest_price: float | None = None
    change_percent: float | None = None
    pe: float | None = None
    pb: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    market_timestamp: datetime | None = None
    market_source: str | None = None
    created_at: datetime
    updated_at: datetime


class ThesisCreate(BaseModel):
    claim: str = Field(min_length=3, max_length=500)
    counter_condition: str = Field(default="", max_length=500)
    status: ThesisStatus = ThesisStatus.watching
    next_review_trigger: str = Field(default="手动复核", max_length=200)
    # 用了方法库里的哪一个。留空表示自由发挥——那也是一种答案，归因时单列一组。
    method_key: str | None = Field(default=None, max_length=40)


class ThesisUpdate(BaseModel):
    claim: str | None = Field(default=None, min_length=3, max_length=500)
    counter_condition: str | None = Field(default=None, max_length=500)
    status: ThesisStatus | None = None
    next_review_trigger: str | None = Field(default=None, max_length=200)
    change_note: str = Field(default="", max_length=300)


class ThesisRecord(BaseModel):
    id: int
    company_id: int
    claim: str
    counter_condition: str
    status: ThesisStatus
    next_review_trigger: str
    method_key: str | None = None
    method_name: str | None = None
    created_at: datetime
    updated_at: datetime
    evidence_count: int = 0
    counter_evidence_count: int = 0
    revision_count: int = 0


class EvidenceCreate(BaseModel):
    thesis_id: int | None = None
    source_name: str = Field(min_length=1, max_length=100)
    source_url: HttpUrl | None = None
    excerpt: str = Field(min_length=3, max_length=1500)
    polarity: EvidencePolarity = EvidencePolarity.neutral
    occurred_at: datetime = Field(default_factory=datetime.now)
    verification: str = Field(default="待核验", max_length=50)


class EvidenceRecord(BaseModel):
    id: int
    company_id: int
    thesis_id: int | None
    source_name: str
    source_url: str | None
    excerpt: str
    polarity: EvidencePolarity
    occurred_at: datetime
    verification: str
    created_at: datetime


class ResearchEventCreate(BaseModel):
    thesis_id: int | None = None
    category: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=3, max_length=300)
    occurred_at: datetime = Field(default_factory=datetime.now)
    importance: EventImportance = EventImportance.medium
    verification: str = Field(default="待核验", max_length=50)


class ResearchEventUpdate(BaseModel):
    verification: str | None = Field(default=None, max_length=50)
    thesis_id: int | None = None


class ResearchEventRecord(BaseModel):
    id: int
    company_id: int
    thesis_id: int | None
    category: str
    title: str
    occurred_at: datetime
    importance: EventImportance
    verification: str
    created_at: datetime


class CompanyDetail(CompanyRecord):
    theses: list[ThesisRecord]
    evidences: list[EvidenceRecord]
    events: list[ResearchEventRecord]
    profile: "CompanyProfileSummary | None" = None
    valuation: "ValuationSummary | None" = None
    market_history: "MarketHistorySummary | None" = None
    financials: "FinancialSummary | None" = None
    ledger: "CompanyLedger | None" = None


class PriceBar(BaseModel):
    trade_date: date
    close: float
    high: float | None = None
    low: float | None = None
    change_percent: float | None = None


class MarketHistorySummary(BaseModel):
    source: str
    adjusted: str
    refreshed_at: datetime
    latest_trade_date: date
    price_5d_change: float | None = None
    price_20d_change: float | None = None
    ytd_change: float | None = None
    one_year_change: float | None = None
    bars: list[PriceBar]


class MarketHistoryRefreshResult(BaseModel):
    company_id: int
    refreshed_bars: int
    source: str = "StockSDK"
    as_of: datetime


class FinancialPeriod(BaseModel):
    report_date: date
    revenue: float | None = None
    net_profit: float | None = None
    operating_cash_flow: float | None = None
    operating_cost: float | None = None
    rnd_expense: float | None = None
    capex: float | None = None
    receivables: float | None = None
    inventory: float | None = None
    interest_bearing_debt: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    equity: float | None = None
    debt_ratio: float | None = None
    roe_estimate: float | None = None
    currency: str | None = None
    audit_status: str = "待确认"
    announcement_date: date | None = None
    # 以下为本地计算的派生指标，口径写在 FinancialMetricCard.basis 里
    gross_margin: float | None = None
    net_margin: float | None = None
    free_cash_flow: float | None = None
    cash_conversion: float | None = None
    interest_debt_ratio: float | None = None
    rnd_ratio: float | None = None
    receivable_days: float | None = None
    inventory_days: float | None = None
    revenue_ttm: float | None = None
    net_profit_ttm: float | None = None
    ttm_basis: str | None = None


class FinancialMetricCard(BaseModel):
    key: str
    label: str
    value: float | None = None
    unit: str
    basis: str
    previous_annual: float | None = None
    previous_annual_date: date | None = None
    unavailable_reason: str | None = None


class FinancialWarning(BaseModel):
    level: str
    title: str
    detail: str


class DupontComponent(BaseModel):
    key: str
    label: str
    value: float | None
    unit: str
    formula: str
    caveat: str
    group: str
    unavailable_reason: str | None = None


class DupontBreakdown(BaseModel):
    components: list[DupontComponent]
    roe_reconstructed: float | None
    unit: str
    formula: str
    caveat: str
    unavailable_reason: str | None = None


class FinancialSummary(BaseModel):
    source: str
    refreshed_at: datetime
    latest_report_date: date
    latest_audit_status: str
    latest_annual_roe_report_date: date | None = None
    roe_reference_value: float | None = None
    roe_reference_report_date: date | None = None
    roe_reference_source: str | None = None
    periods: list[FinancialPeriod]
    metrics: list[FinancialMetricCard] = []
    warnings: list[FinancialWarning] = []
    dupont: DupontBreakdown | None = None


class FinancialRefreshResult(BaseModel):
    company_id: int
    refreshed_periods: int
    source: str = "AKShare / 新浪财经"
    as_of: datetime


class QuotePreview(BaseModel):
    symbol: str
    name: str
    exchange: str
    price: float | None = None
    change_percent: float | None = None
    pe: float | None = None
    pb: float | None = None
    market_timestamp: datetime | None = None
    source: str


class UniverseMatch(BaseModel):
    """全市场里的一家公司，附带"你建过档没有"。

    行业和总市值是给**重名消歧**用的，不是装饰：搜「中国电建」「中国电研」
    只看名字分不清，一眼看到行业和市值就分得清。
    """

    symbol: str
    name: str
    industry: str | None = None
    board: str = ""
    exchange: str = ""
    price: float | None = None
    change_percent: float | None = None
    total_market_cap: float | None = None
    company_id: int | None = None
    in_archive: bool = False


class DataProviderStatus(BaseModel):
    provider_id: str
    display_name: str
    category: str
    last_status: str
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    refreshed_items: int


class MarketTile(BaseModel):
    name: str
    value: float = Field(gt=0)
    change: float
    group: str


class WatchlistItem(BaseModel):
    id: int
    symbol: str
    name: str
    industry: str
    thesis_status: ThesisStatus
    valuation_percentile: int | None
    roe_trend: str
    last_reviewed_at: date | None
    latest_price: float | None = None
    change_percent: float | None = None
    pe: float | None = None
    pb: float | None = None
    market_timestamp: datetime | None = None
    market_source: str | None = None


class ThesisItem(BaseModel):
    id: int
    # 决策总览要能一键跳到这家公司去（比如"让反方驳一驳这条"）。
    # 只有 symbol 跳不过去——路由按 company_id 走。
    company_id: int = 0
    symbol: str
    company_name: str
    claim: str
    status: ThesisStatus
    evidence_count: int = Field(ge=0)
    counter_evidence_count: int = Field(ge=0)
    next_review_trigger: str


class DashboardEvent(BaseModel):
    id: int
    company_id: int
    symbol: str
    company_name: str
    category: str
    title: str
    occurred_at: datetime
    importance: EventImportance
    verification: str


class IndustrySummary(BaseModel):
    name: str
    company_count: int
    watched_count: int
    companies: str | None = None


class PeerValuation(BaseModel):
    current: float | None = None
    percentile: float | None = None
    note: str | None = None


class PeerFinancials(BaseModel):
    report_date: date | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    cash_conversion: float | None = None
    debt_ratio: float | None = None
    interest_debt_ratio: float | None = None
    roe_estimate: float | None = None
    roe_report_date: date | None = None
    revenue_growth: float | None = None
    revenue_growth_basis: str | None = None
    note: str | None = None


class PeerCompany(BaseModel):
    id: int
    symbol: str
    name: str
    industry: str
    industry_source: str
    is_watched: bool
    latest_price: float | None = None
    change_percent: float | None = None
    market_timestamp: datetime | None = None
    valuation: dict[str, PeerValuation]
    financials: PeerFinancials


class IndustryAggregate(BaseModel):
    """行业表的聚合行；各指标只按有值的公司计算，不把缺失当成 0。"""

    sample_count: int = 0
    latest_price: float | None = None
    pe_ttm: float | None = None
    pe_ttm_percentile: float | None = None
    pb: float | None = None
    pb_percentile: float | None = None
    roe_estimate: float | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    cash_conversion: float | None = None
    debt_ratio: float | None = None
    revenue_growth: float | None = None
    coverage: dict[str, int] = {}


class IndustryComparison(BaseModel):
    industry: str | None = None
    benchmark_company_count: int = 0
    benchmark_source: str = ""
    benchmark_as_of: date | None = None
    company_count: int
    coverage: str
    industry_basis: str
    companies: list[PeerCompany]
    average: IndustryAggregate
    lower_quartile: IndustryAggregate
    median: IndustryAggregate
    upper_quartile: IndustryAggregate


class ScreenRule(BaseModel):
    field: str = Field(min_length=1, max_length=40)
    op: str = Field(pattern="^(gte|lte|gt|lt)$")
    value: float
    unit: str = Field(default="", max_length=8)
    text: str | None = None


class ScreenStrategy(BaseModel):
    key: str
    name: str
    summary: str = ""
    provenance: str = ""
    biases: list[str] = []
    rules: list[ScreenRule] = []
    sort_field: str
    sort_desc: bool = True
    sort_label: str = ""
    preset: bool = True
    # 价值口味还是趋势口味。荐股池按它决定这套规则进哪个池子——
    # 漏声明的话接口出去就没有这个键，而池子会把所有策略都当成价值型。
    kind: str = "value"
    forked_from: str | None = None
    required_fields: list[str] = []
    available: bool = True
    unavailable_reason: str | None = None


class ScreenStrategySave(BaseModel):
    """把预置策略复制成自己的，或直接写一套新的。"""

    key: str = Field(min_length=1, max_length=40, pattern="^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=40)
    summary: str = Field(default="", max_length=300)
    rules: list[ScreenRule] = Field(min_length=1, max_length=12)
    sort_field: str = Field(min_length=1, max_length=40)
    sort_desc: bool = True
    sort_label: str = Field(default="", max_length=60)
    forked_from: str | None = Field(default=None, max_length=40)


class ScreenAdHoc(BaseModel):
    """未保存的临时条件，用于在界面上改完直接试跑。"""

    name: str = Field(default="临时条件", max_length=40)
    rules: list[ScreenRule] = Field(min_length=1, max_length=12)
    sort_field: str = Field(min_length=1, max_length=40)
    sort_desc: bool = True
    sort_label: str = Field(default="", max_length=60)
    forked_from: str | None = Field(default=None, max_length=40)


class ScreenField(BaseModel):
    field: str
    label: str
    unit: str = ""
    hint: str = ""
    derived: bool = False
    coverage: float = 0
    usable: bool = False


class ScreenCheck(BaseModel):
    rule: str
    field: str
    label: str
    actual: float | None = None
    passed: bool
    missing: bool = False


class ScreenCandidate(BaseModel):
    symbol: str
    name: str
    board: str
    industry: str | None = None
    price: float | None = None
    change_percent: float | None = None
    total_market_cap: float | None = None
    report_date: str | None = None
    price_as_of: datetime | None = None
    in_indexes: list[str] = []
    in_research_pool: bool = False
    also_matched: list[str] = []
    sort_value: float | None = None
    checks: list[ScreenCheck] = []


class Billing(BaseModel):
    """一次 AI 操作实际花掉的积分。

    页面必须把这个数字显示出来——用户按下按钮之前不知道会花多少（token 数事先算不准），
    那至少事后要如实告诉他花了多少。`metered=False` 表示这次根本没计费
    （本地单机、未登录、闸口不可达），不要显示成「0 分」当成免费。
    """

    metered: bool = False
    credits: int = 0
    tokens: int = 0
    calls: int = 0


class ScreenResult(BaseModel):
    strategy: ScreenStrategy
    universe_total: int
    matched: int
    returned: int
    # 两级排序都写出来：第一关键字是「被几套策略同时选中」，第二才是策略声明的字段
    sort_explain: str = ""
    report_date: str | None = None
    price_as_of: datetime | None = None
    candidates: list[ScreenCandidate]
    boundary: str
    billing: Billing = Billing()


class ScreenRunRecord(BaseModel):
    id: int
    strategy_key: str
    strategy_name: str
    rules: list[ScreenRule]
    universe_total: int
    matched: int
    report_date: str | None = None
    price_as_of: datetime | None = None
    executed_at: datetime
    note: str = ""


class CandidateReviewSave(BaseModel):
    """保存一次模型复核的原始结果，供之后继续查看。"""

    strategy_key: str = Field(min_length=1, max_length=80)
    strategy_name: str = Field(min_length=1, max_length=120)
    width: int = Field(ge=1, le=60)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=60)
    note: str = Field(default="", max_length=2000)
    boundary: str = Field(default="", max_length=4000)
    estimated_credits: int = Field(default=0, ge=0, le=100)


class CandidateReviewRecord(BaseModel):
    id: int
    strategy_key: str
    strategy_name: str
    width: int
    rows: list[dict[str, Any]] = []
    note: str = ""
    boundary: str = ""
    estimated_credits: int = 0
    created_at: datetime


class UniverseBoard(BaseModel):
    name: str
    count: int


class UniverseIndex(BaseModel):
    index_code: str
    index_name: str
    count: int


class ResearchTaskCreate(BaseModel):
    """把一份候选清单固化成一次研究任务；入选依据一并留档。"""

    title: str = Field(min_length=1, max_length=80)
    strategy_key: str = Field(min_length=1, max_length=40)
    symbols: list[str] = Field(default_factory=list, max_length=100)
    due_date: date | None = None
    limit: int = Field(default=30, ge=1, le=100)


class ResearchTaskItemUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=1000)


class ResearchTaskUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=20)
    conclusion: str | None = Field(default=None, max_length=2000)
    due_date: date | None = None


class ResearchTaskItem(BaseModel):
    id: int
    task_id: int
    symbol: str
    name: str
    industry: str | None = None
    evidence: list[dict[str, Any]] = []
    status: str
    note: str = ""
    # **这三个必须写在这里**，不是可有可无的补充。响应模型会把模型里没有的键
    # 直接丢掉——库里存了、repository 也返回了，接口出去就是没有，
    # 而前端拿 undefined 去 .length 就是一屏白。默认值给空是为了老条目。
    verdict: str = ""
    # 模型初筛写的结论。跟 note 分开：note 是用户自己写的一句话。
    conclusion: str = ""
    reasons: list[str] = []
    concerns: list[str] = []
    # 候选的方法体检结果。**必须在这里声明**——响应模型会把没声明的键静默丢掉。
    assessment: list[dict[str, Any]] = []
    assessed_at: str = ""
    company_id: int | None = None
    brief: str = ""
    brief_source: str = ""
    links: list[dict[str, str]] = []
    reports: list[dict[str, Any]] = []
    updated_at: datetime


class ResearchTaskRecord(BaseModel):
    id: int
    title: str
    source: str
    strategy_key: str | None = None
    strategy_name: str | None = None
    rules: list[dict[str, Any]] = []
    data_note: str = ""
    status: str
    conclusion: str = ""
    due_date: date | None = None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    total: int = 0
    pending: int = 0
    adopted: int = 0
    dropped: int = 0
    items: list[ResearchTaskItem] = []


class HeatmapTile(BaseModel):
    name: str
    symbol: str | None = None
    industry: str | None = None
    size: float
    metric_value: float | None = None
    count: int = 1
    watched: list[dict[str, Any]] = Field(default_factory=list)


class HeatmapBreadth(BaseModel):
    advancing: int
    declining: int
    unchanged: int
    median_change: float | None
    covered: int
    note: str


class HeatmapScope(BaseModel):
    key: str
    label: str
    group: str
    count: int | None = None


class HeatmapView(BaseModel):
    scope: str
    scope_label: str
    level: str
    metric: str
    metric_label: str
    metric_unit: str
    metric_kind: str
    metric_note: str
    aggregation: str
    universe_total: int
    with_metric: int
    size_basis: str = "总市值"
    tiles: list[HeatmapTile]
    indexes: list[UniverseIndex] = []
    coverage: str
    boundary: str
    breadth: HeatmapBreadth | None = None
    scopes: list[HeatmapScope] = []


class MarketFundFlowPoint(BaseModel):
    date: str
    main_net_inflow: float | None = None
    main_net_inflow_percent: float | None = None
    super_large_net_inflow: float | None = None
    large_net_inflow: float | None = None
    medium_net_inflow: float | None = None
    small_net_inflow: float | None = None
    sh_close: float | None = None
    sh_change_percent: float | None = None
    sz_close: float | None = None
    sz_change_percent: float | None = None


class MarketFundFlowView(BaseModel):
    source: str
    as_of: str
    unit: str = "元"
    points: list[MarketFundFlowPoint]
    # 本地快照什么时候同步的、这一份是不是降级返回的。
    # **降级要说出来**：一屏"截至昨天"的图有用，但让人以为是今天的就有害。
    synced_at: str = ""
    degraded: bool = False
    note: str = ""
    boundary: str


class UniverseFieldCoverage(BaseModel):
    field: str
    label: str
    filled: int
    ratio: float


class UniverseSnapshotRecord(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    price_rows: int
    fundamental_rows: int
    index_rows: int
    price_source: str | None = None
    fundamental_source: str | None = None
    report_date: str | None = None
    degraded: bool = False
    note: str = ""


class UniverseSummary(BaseModel):
    total: int
    boards: list[UniverseBoard] = []
    indexes: list[UniverseIndex] = []
    completeness: list[UniverseFieldCoverage] = []
    last_snapshot: UniverseSnapshotRecord | None = None
    report_date: str | None = None
    valuation_history_days: int = 0
    valuation_history_start: date | None = None
    valuation_history_note: str = ""
    coverage: str


class UniversePercentile(BaseModel):
    symbol: str
    metric: str
    current: float | None = None
    percentile: float | None = None
    sample_size: int = 0
    sample_start: date | None = None
    sample_end: date | None = None
    unavailable_reason: str | None = None


class UniverseRow(BaseModel):
    symbol: str
    name: str
    exchange: str
    board: str
    industry: str | None = None
    price: float | None = None
    change_percent: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    total_market_cap: float | None = None
    float_market_cap: float | None = None
    turnover_rate: float | None = None
    ytd_change: float | None = None
    change_60d: float | None = None
    report_date: str | None = None
    revenue: float | None = None
    revenue_growth: float | None = None
    net_profit: float | None = None
    net_profit_growth: float | None = None
    roe: float | None = None
    gross_margin: float | None = None
    eps: float | None = None
    bps: float | None = None
    ocf_per_share: float | None = None
    price_source: str | None = None
    price_as_of: datetime | None = None
    fundamental_source: str | None = None
    fundamental_as_of: datetime | None = None
    updated_at: datetime


class WatchlistImportRow(BaseModel):
    """导出文件里的一行；名称与行业仍以行情源为准，这里只回灌用户自己写的字段。"""

    # **这里不加六位数字的约束。** 批量导入是逐条处理、逐条报告的：
    # 坏代码会在行情校验那一步被拒，并且原样列在结果里告诉用户哪条不行。
    # 在模型上拦的话，整批会在构造时就崩掉 —— 用户反倒不知道坏在哪条。
    # 直接建档（CompanyInput / CompanyFromQuoteInput）没有这一层，所以那两处要拦。
    symbol: str = Field(min_length=1, max_length=16)
    watch_group: str | None = Field(default=None, max_length=30)
    description: str | None = Field(default=None, max_length=600)
    industry: str | None = Field(default=None, max_length=60)
    is_watched: bool | None = None


class WatchlistImport(BaseModel):
    """批量加入研究池；仍然逐个用行情校验，不接受手填的公司名称。

    两种用法：粘贴一串代码（symbols），或直接回灌导出的文件（rows）。
    """

    symbols: list[str] = Field(default_factory=list, max_length=200)
    rows: list[WatchlistImportRow] = Field(default_factory=list, max_length=200)
    watch_group: str = Field(default="观察池", min_length=1, max_length=30)
    description: str = Field(default="", max_length=600)
    # 回灌导出文件时，已存在的公司是否也恢复分组、研究缘起与是否关注
    restore_existing: bool = False


class WatchlistImportItem(BaseModel):
    symbol: str
    status: str
    detail: str = ""


class WatchlistImportResult(BaseModel):
    created: int
    skipped: int
    updated: int = 0
    failed: int
    results: list[WatchlistImportItem]


class WatchGroupSummary(BaseModel):
    name: str
    watched: int
    archived: int


class WatchlistExportRow(BaseModel):
    symbol: str
    name: str
    exchange: str
    industry: str
    watch_group: str
    is_watched: bool
    description: str
    valuation_percentile: int | None = None
    roe_trend: str
    created_at: datetime


class SyncJobStatus(BaseModel):
    job_id: str
    display_name: str
    category: str
    description: str = ""
    interval_minutes: int
    weekdays_only: bool
    enabled: bool
    freshness_hours: int
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_status: str
    last_error: str | None = None
    last_items: int = 0
    next_run_at: datetime | None = None
    consecutive_failures: int = 0
    health: str
    health_message: str
    age_hours: float | None = None
    # 这个任务算不算「需要关注」。**判定在后端做，前端不再自己列名单**——
    # 上一版前端那份少了「降级」，于是首页说有事、点进去说全正常。
    # （声明在这里是必须的：响应模型不写，后端算了也带不出去，
    #   页面上只表现为"这一栏永远是 undefined"，不报错。本仓踩过四次。）
    needs_attention: bool = False


class SyncJobUpdate(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=20160)


class SyncRunRecord(BaseModel):
    id: int
    job_id: str
    display_name: str | None = None
    trigger: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    items: int = 0
    failures: int = 0
    error: str | None = None
    detail: str = ""


class SyncRunResult(BaseModel):
    job_id: str
    status: str
    items: int
    failures: int
    detail: str
    error: str | None = None
    started_at: datetime
    finished_at: datetime
    next_run_at: datetime


class InboxTarget(StrEnum):
    evidence = "evidence"
    event = "event"


class InboxArchive(BaseModel):
    """把一条已同步的公告归档为证据或事件；判断由用户做出，系统不代劳。

    ## 默认值原来跟上面这句话正好相反

    `verification` 的默认值是「已核验」，而手工建证据的默认是「待核验」
    （见本文件 132 / 154 行）—— 也就是说**只有批量归档这一条路会替人盖上"核过了"**。

    实测：`archive_inbox_batch` 一次归档最多 500 条公告，每一条都写「已核验」。
    公司档案的证据档案里四条并排，四个「已核验」——**没有一条被人看过**。
    而同一个函数返回的说明里还特意写着「极性一律是中性 —— 这条公告对你的判断是
    支持还是反证，仍然由你在证据档案里改」。

    极性交给人判断、核验却替人判了，这两件事是同一类。而「已核验」比极性更重：
    它是在说"这条我看过了、是真的"。**一个没人看过的判断被标成看过了，
    比没有这个标记糟得多** —— 复盘时你不会再去核它。

    所以默认改成「待核验」。真要标已核验的调用方自己显式传。
    """

    target: InboxTarget
    thesis_id: int | None = None
    polarity: EvidencePolarity = EvidencePolarity.neutral
    importance: EventImportance = EventImportance.medium
    verification: str = Field(default="待核验", max_length=50)
    note: str = Field(default="", max_length=1000)


class InboxItem(BaseModel):
    id: int
    company_id: int
    symbol: str
    company_name: str
    category: str
    event_date: date
    title: str
    detail: str = ""
    url: str | None = None
    source: str
    inbox_status: str
    archived_as: str | None = None
    archived_ref_id: int | None = None
    handled_at: datetime | None = None
    relevance: str | None = None
    relevance_reason: str | None = None
    relevance_source: str | None = None
    relevance_topic: str | None = None
    summary: str | None = None


class InboxClassifyResult(BaseModel):
    scanned: int
    by_rules: int
    by_model: int
    uncertain: int
    counts: dict[str, int] = {}
    note: str = ""
    billing: Billing = Billing()


class InboxPage(BaseModel):
    items: list[InboxItem]
    total: int
    in_window: int
    ungraded: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    window_days: int | None = None
    since: date | None = None


class InboxActionResult(BaseModel):
    item: InboxItem
    created_type: str
    created_id: int


class ValuationPoint(BaseModel):
    point_date: date
    value: float


class ValuationWindow(BaseModel):
    """某个回看窗口内的分位。分位只描述当前值在历史样本中的位置，不代表贵或便宜。"""

    window_years: int
    sample_size: int
    sample_start: date | None = None
    sample_end: date | None = None
    percentile: float | None = None
    minimum: float | None = None
    median: float | None = None
    maximum: float | None = None
    unavailable_reason: str | None = None
    # **样本实际横跨几年，以及没铺满时的那句话。**
    #
    # 跟 window_years 不是一回事：序列可能根本没那么长。寒武纪 2025-04 才转正、
    # 之前没有 PE，于是「近 3 年分位」和「近 5 年分位」是同一个 1.7% ——
    # 背后是同一批 16 个月的样本，而读的人会当成五年历史位置。
    #
    # **这两行漏在这儿的话，repository 算得再对也白算**：响应模型会把
    # 多出来的键悄悄吃掉，页面表现为"这块从来不出现"，不报错。
    # 这个坑本仓已经踩过四次，第五次就是我加这两个字段的时候。
    covered_years: float | None = None
    coverage_note: str | None = None


class ValuationMetric(BaseModel):
    metric: str
    label: str
    current: float | None = None
    current_date: date | None = None
    windows: list[ValuationWindow] = []
    history: list[ValuationPoint] = []


class ValuationSummary(BaseModel):
    source: str
    refreshed_at: datetime
    metrics: list[ValuationMetric]
    local_snapshot_days: int = 0
    local_snapshot_start: date | None = None


class ValuationRefreshResult(BaseModel):
    company_id: int
    refreshed_points: int
    source: str = "AKShare / 百度股市通"
    as_of: datetime


class CompanyCalendarEvent(BaseModel):
    id: int | None = None
    category: str
    event_date: date
    title: str
    detail: str = ""
    url: str | None = None
    source: str
    upcoming: bool = False
    inbox_status: str = "待核验"
    archived_as: str | None = None


class CompanyProfileSummary(BaseModel):
    """公开披露的公司资料；全部字段来自数据源，缺失时为空而不是占位文字。"""

    full_name: str | None = None
    english_name: str | None = None
    industry: str | None = None
    market: str | None = None
    legal_representative: str | None = None
    registered_capital: float | None = None
    founded_date: date | None = None
    listed_date: date | None = None
    website: str | None = None
    registered_address: str | None = None
    office_address: str | None = None
    main_business: str | None = None
    product_type: str | None = None
    business_scope: str | None = None
    introduction: str | None = None
    total_shares: float | None = None
    circulating_shares: float | None = None
    share_structure_date: date | None = None
    share_change_reason: str | None = None
    issue_price: float | None = None
    raised_net: float | None = None
    underwriter: str | None = None
    latest_dividend_period: str | None = None
    latest_dividend_plan: str | None = None
    latest_dividend_progress: str | None = None
    latest_dividend_payout_ratio: str | None = None
    latest_dividend_record_date: date | None = None
    latest_dividend_ex_date: date | None = None
    missing_sections: list[str] = []
    source: str
    refreshed_at: datetime
    upcoming_events: list[CompanyCalendarEvent] = []
    recent_events: list[CompanyCalendarEvent] = []
    event_count: int = 0


class CompanyProfileRefreshResult(BaseModel):
    company_id: int
    refreshed_events: int
    source: str = "AKShare / 巨潮资讯"
    as_of: datetime


class TradeSide(StrEnum):
    """账本上会发生的五种事。

    后三种不是「你的决定」，而是「发生在你身上的事」——但它们同样改变持仓与收益。
    只记买卖的账本会长期偏离事实，而且偏得很有方向性：**分红被完全忽略，
    长期持有的真实回报被系统性低估**，恰好低估的是长期投资最看重的那一块。
    """

    buy = "buy"
    sell = "sell"
    dividend = "dividend"     # 现金分红（税后到账）
    bonus = "bonus"           # 送股 / 转增：股数增加，成本不变
    rights = "rights"         # 配股：按配股价掏钱增持


# 会改变股数的类型；分红不在其中
SHARE_CHANGING = {TradeSide.buy, TradeSide.sell, TradeSide.bonus, TradeSide.rights}


class AmountMode(StrEnum):
    """账本记到什么程度。

    full  —— 股数与价格都记。能算出真实盈亏，代价是**这台机器上落着你的真实财务状况**。
    ratio —— 只记仓位占比（这只占我 15%），成本价可选。研究判断需要的其实只是「重不重」，
             而不是「多少钱」：逻辑被破坏时该减仓，与持有 3 万还是 300 万无关。
             建议默认用它；确实需要真实盈亏时再开 full。

    这个取舍在组合上单独设，而不是全局一刀切——可以只给自己那个组合开 full。
    """

    full = "full"
    ratio = "ratio"


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    objective: str = Field(default="", max_length=300)
    # 默认只记比例。真实财务状况落在磁盘上这件事该是明确选择，不该是默认。
    amount_mode: AmountMode = AmountMode.ratio


class PortfolioUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    objective: str | None = Field(default=None, max_length=300)
    amount_mode: AmountMode | None = None


class TradeCreate(BaseModel):
    """一笔记录必须带上当时的理由；系统不会替用户补写动机。

    字段哪些必填取决于 side 与组合的 amount_mode，校验在 repository 里做——
    那里才知道这个组合是 full 还是 ratio。
    """

    company_id: int
    thesis_id: int | None = None
    side: TradeSide
    trade_date: date = Field(default_factory=date.today)
    # **上限不是形式主义。** 2026-08-19 巡检实测：一笔 1e15 股就把整个账本变成废纸 ——
    # 持仓成本 100,000,000,000,020,000 元、浮盈 +1,207,880%。
    # 下限拦住了负数和零，上限一直是空的。
    #
    # 100 亿股：A 股股本最大的公司也就三千多亿股，个人持仓到不了这个量级；
    # 十万元一股：茅台一千三，留两个数量级的余量。
    # 挡的是"手滑多打几个零"和"把总金额填进单价"，不是挡真实交易。
    shares: float | None = Field(default=None, gt=0, le=1e10)
    price: float | None = Field(default=None, ge=0, le=1e5)   # 送股价格为 0，所以是 ge 不是 gt
    fee: float = Field(default=0, ge=0, le=1e8)
    weight_percent: float | None = Field(default=None, ge=0, le=100)
    cash_amount: float | None = Field(default=None, ge=0)
    # "补仓""清仓"这类两个字的理由是合理记录，不该被挡在门外；空白仍然不允许。
    # 分红/送股这类不是你的决定，理由可以省——系统会替你写上「除权除息，非主动操作」。
    rationale: str = Field(default="", max_length=1000)
    expectation: str = Field(default="", max_length=1000)
    review_due: date | None = None

    @field_validator("trade_date")
    @classmethod
    def _not_in_the_future(cls, value: date) -> date:
        """交易日期不能在未来。

        实测 `2999-01-01` 能存进去。一笔未来的交易会排在流水最前面，
        让"最近一笔"和移动加权成本都跟着错 —— 而 review_due（下次复核）
        本来就该在未来，所以只管这一个字段。
        """
        if value > date.today():
            raise ValueError("交易日期不能填未来的日期。")
        return value


class TradeUpdate(BaseModel):
    rationale: str | None = Field(default=None, min_length=2, max_length=1000)
    expectation: str | None = Field(default=None, max_length=1000)
    review_due: date | None = None
    change_note: str = Field(default="", max_length=300)


class TradeRecord(BaseModel):
    id: int
    portfolio_id: int
    portfolio_name: str
    company_id: int
    symbol: str
    company_name: str
    thesis_id: int | None
    side: TradeSide
    trade_date: date
    shares: float | None = None
    price: float | None = None
    fee: float
    amount: float | None = None
    weight_percent: float | None = None
    cash_amount: float | None = None
    rationale: str
    expectation: str
    review_due: date | None
    thesis_claim_snapshot: str
    thesis_status_snapshot: str
    created_at: datetime
    revision_count: int = 0


class PositionRecord(BaseModel):
    company_id: int
    symbol: str
    company_name: str
    industry: str
    shares: float
    average_cost: float | None = None
    cost_value: float
    latest_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_percent: float | None = None
    realized_pnl: float
    realized_cost: float = 0.0
    dividend_income: float = 0.0
    cost_after_dividends: float | None = None
    weight_percent: float | None = None
    weight: float | None = None
    first_trade_date: date
    last_trade_date: date
    trade_count: int
    thesis_status: ThesisStatus | None = None
    next_review_due: date | None = None
    market_timestamp: datetime | None = None


class PortfolioSummary(BaseModel):
    id: int
    name: str
    objective: str
    amount_mode: AmountMode = AmountMode.full
    dividend_income: float = 0.0
    created_at: datetime
    updated_at: datetime
    position_count: int
    trade_count: int
    cost_value: float
    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_percent: float | None = None
    realized_pnl: float
    largest_weight: float | None = None
    top3_weight: float | None = None
    priced_positions: int = 0
    reviews_due: int = 0
    quote_as_of: datetime | None = None


class PortfolioDetail(PortfolioSummary):
    positions: list[PositionRecord]
    closed_positions: list[PositionRecord]
    trades: list[TradeRecord]


class CompanyLedger(BaseModel):
    """公司档案里的持仓与交易视图，跨组合合并。"""

    shares: float
    average_cost: float | None = None
    cost_value: float
    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_percent: float | None = None
    realized_pnl: float
    # 分红单独列出来，不混进 realized_pnl：
    # 「卖出赚的」与「拿着收的」是两种性质完全不同的钱，合并之后就看不出
    # 这笔投资到底是靠差价还是靠现金流回报的——而这正是长期投资要回答的问题。
    dividend_income: float = 0.0
    # 摊薄视角：把已收分红从成本里扣掉之后的成本价。券商不这么显示，
    # 所以不改 average_cost，另给一个字段，两种看法都在。
    cost_after_dividends: float | None = None
    total_return: float | None = None
    total_return_percent: float | None = None
    next_review_due: date | None = None
    portfolio_names: list[str]
    # **仓位口径下 shares 永远是 0。** 只看 shares 的话，一笔 50% 的持仓
    # 会被页面写成「已清仓」——使用者真的这么撞上了：他刚记完 50% 仓位和成本价，
    # 页面顶上写着"已清仓"。所以把口径本身带出来，让前端知道该显示哪一种。
    weight_percent: float | None = None
    amount_mode: str = "full"
    trades: list[TradeRecord]


class ScannedTrade(BaseModel):
    """从截图里读出来的一条流水。**读出来不等于记进账本**——每条都要你确认。

    模型认错一个数字，账本就永久错一笔；而账本错了之后所有复盘都建立在错的基础上。
    所以这里只负责读，写进去是另一步。
    """

    side: TradeSide
    trade_date: date | None = None
    symbol: str = ""
    company_name: str = ""
    shares: float | None = None
    price: float | None = None
    fee: float | None = None
    cash_amount: float | None = None
    # 本地档案里匹配到的公司；匹配不上就是 None，由用户在确认时指定
    company_id: int | None = None
    matched_by: str = ""
    confidence: str = "待确认"
    note: str = ""
    # 长截图切成多段读，每行本该被相邻两段各读一次。只被读到一次的，
    # 说明有一段漏读了它——那一行没有被印证过，值得重点核。
    seen_in: int = 1
    cross_checked: bool = False


class TradeScanResult(BaseModel):
    trades: list[ScannedTrade]
    unmatched: list[str] = []
    warnings: list[str] = []
    # 这张图是怎么切的（长截图必切，见 ledger_scan 的说明）
    geometry: dict[str, Any] = {}
    # 逐行费用 vs 页头「交易税费」合计。**这是这张图上唯一的校验和。**
    reconcile: dict[str, Any] | None = None
    model: str = ""
    boundary: str = ""
    billing: Billing = Billing()


class AdvocateAsk(BaseModel):
    """问反方一句话。history 是上一轮返回的 messages，接着聊时原样传回来。"""

    question: str = Field(min_length=2, max_length=500)
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=40)


class PromiseItem(BaseModel):
    """一条待确认的管理层承诺。**抽取出来不等于记进台账**——每条都要人过一眼。"""

    statement: str = Field(min_length=1, max_length=500)
    promised_on: str
    subject: str = "公司"
    category: str = "其他"
    due_date: str | None = None
    check_metric: str = ""
    check_op: str = ""
    check_value: float | None = None
    check_period: str = ""
    event_id: int | None = None
    source_title: str = ""
    source_url: str | None = None


class PromiseBatch(BaseModel):
    items: list[PromiseItem] = Field(min_length=1, max_length=100)


class PromiseSettle(BaseModel):
    """给一条承诺下结论。**结论由人下**——自动核对只说对上没对上。"""

    status: str
    note: str = ""


class ScanKeep(BaseModel):
    """记完之后还留着没记的那几条。空列表表示这次读图的结果可以整个清掉。"""

    trades: list[ScannedTrade] = Field(default_factory=list, max_length=400)


class ScanKnown(BaseModel):
    """问一句：这批读出来的流水里，哪几条账本里已经有了。"""

    portfolio_id: int
    trades: list[ScannedTrade] = Field(default_factory=list, max_length=400)


class TradeBatchCreate(BaseModel):
    """确认读图结果。**这里刻意不逐条校验。**

    声明成 `list[TradeCreate]` 的话，Pydantic 会在进函数之前就把整批 422 掉——
    而 create_trades_batch 写着的承诺是「逐条独立成败」。那个承诺此前是假的：
    截图里十条有一条读错，另外九条也一起被退回来，而那正是读图想省掉的事。

    所以这一层只管形状（是个非空列表），每一条的校验挪进循环里，坏的那条单独报。
    """

    trades: list[dict[str, Any]] = Field(min_length=1, max_length=200)


class TradeBatchResult(BaseModel):
    created: list[TradeRecord]
    failed: list[dict[str, Any]]
    note: str


class RecordRevision(BaseModel):
    """研究记录的历史版本；修改只追加，不覆盖。"""

    id: int
    entity_type: str
    entity_id: int
    version: int
    snapshot: dict[str, Any]
    changed_fields: str
    change_note: str
    created_at: datetime


class BackupManifest(BaseModel):
    name: str
    created_at: datetime
    schema_version: int
    size: int
    note: str = ""
    reason: str = ""
    counts: dict[str, int] = {}


class BackupRestoreResult(BaseModel):
    restored_from: str
    safety_backup: str
    schema_version: int
    before_counts: dict[str, int]
    restored_counts: dict[str, int]
    mismatched: dict[str, dict[str, int]] = {}
    verified: bool


class StaleColumn(BaseModel):
    table: str
    column: str
    filled: int
    total: int
    ratio: float


class StaleAction(BaseModel):
    table: str
    columns: list[str]
    how: str


class Freshness(BaseModel):
    """代码在写、库里却基本没有的列。

    缺列不会报错，只会让下游判断悄悄失去依据——然后表现成「模型说数据不足」
    或「策略筛不出东西」，把人引向完全错误的方向。
    """

    stale: bool = False
    findings: list[StaleColumn] = []
    actions: list[StaleAction] = []
    note: str = ""


class LocalDataSummary(BaseModel):
    freshness: Freshness = Freshness()
    database_path: str
    database_size: int
    schema_version: int
    expected_schema_version: int
    authored_counts: dict[str, int]
    source_counts: dict[str, int]
    backup_count: int
    latest_backup_at: datetime | None = None
    backup_directory: str


class PortfolioExposure(BaseModel):
    name: str
    weight: float = Field(ge=0, le=100)


class DecisionRow(BaseModel):
    """决策看板的一行。每一格都是已发生的事实或已到期的约定，没有预测。"""

    company_id: int
    symbol: str
    name: str
    industry: str | None = None
    watch_group: str
    latest_price: float | None = None
    change_percent: float | None = None
    pe: float | None = None
    pb: float | None = None
    quote_as_of: datetime | None = None
    thesis_count: int = 0
    thesis_status: ThesisStatus | None = None
    claim: str = ""
    counter_condition: str = ""
    # 方法体检的读数。做过没有、其中几个方法说不利——放在这一行上，
    # 省得为了看一眼要点进档案。
    assessed: bool = False
    adverse_methods: int = 0
    method_name: str | None = None
    counter_evidence: int = 0
    pending_events: int = 0
    reviews_due: int = 0
    next_review_date: date | None = None
    held: bool = False
    weight: float | None = None
    unrealized_percent: float | None = None
    action: str
    action_kind: str


class DecisionBoard(BaseModel):
    as_of: str
    rows: list[DecisionRow]
    todo_count: int
    held_count: int
    boundary: str


class DashboardSummary(BaseModel):
    as_of: datetime
    demo: bool = False
    intact_theses: int
    theses_to_review: int
    # 逻辑总数与还没到复核期的那些。**不能只报「成立」与「待复核」**：
    # 一条刚写下、状态是 watching、又不到复核期的逻辑两边都不算，
    # 于是页面上两个 0，而库里明明有两条——用户只会以为数据丢了。
    total_theses: int = 0
    theses_watching: int = 0
    next_review_due: date | None = None
    unread_events: int
    data_health: str
    # 同步坏掉是静默的：页面照常渲染，数字停在三天前。所以要主动摆到第一页。
    data_alerts: list[dict[str, Any]] = []
    market_tiles: list[MarketTile]
    watchlist: list[WatchlistItem]
    theses: list[ThesisItem]
    events: list[DashboardEvent]
    portfolio_exposure: list[PortfolioExposure]
    exposure_basis: str = "研究池分布"
    holding_market_value: float | None = None
    holding_unrealized_percent: float | None = None
    holdings_reviews_due: int = 0
    inbox_pending: int = 0
    # 还没回答的假设漂移问题。**忘了声明的话接口出去就是没有**，
    # 而页面上只表现为"这块从来不出现"，不报错——这个坑本仓踩过四次。
    # 未处理的反证命中数。**侧栏徽章用它，不用未读公告数。**
    # 未读公告长期停在 646——一个永远清不完的红点第三天就成了背景色，
    # 之后真正要紧的事再也没法用徽章提醒。而反证命中是
    # 「你自己写下的那件事真的发生了」，天然是个位数，也天然值得中断你。
    counter_hits: int = 0
    # 还有多少条待核验公告没被比对过。**跟 counter_hits 分开**：
    # 「命中 0」有两种意思——比过了没事、和压根没比过。
    # 只给前一个数的话，第二种会被读成第一种，而第二种才是常态
    # （比对要手动点，按钮还在一个默认折叠的分区里）。
    counter_uncompared: int = 0
    # 有几条判断压根没写认错条件。**它们不在网里** ——
    # 反证比对只查写了条件的，所以这些记录永远不会被事实撞上，而且不报错。
    theses_without_counter: int = 0
    # 「中」级待核验的积压量。**跟 inbox_pending 分开**：
    # inbox_pending 是"点进去真的要做事的数量"（只数「高」），
    # 而这些是"还没定性、但踩不到你任何一条认错条件"的——
    # 它们该在收件箱页面里被交代一句，不该顶在首页当待办。
    inbox_backlog: int = 0
    # **这一份是以什么身份查出来的。**
    #
    # 游客域一行都匹配不到（RLS），所以返回的是一份处处为 0 的档案 ——
    # 而它跟「新用户，确实什么都还没有」在页面上**长得一模一样**，
    # 还配着一个「建立第一家公司 →」的引导按钮。2026-08-15 线上就是这样：
    # 主站 /v1/me 在首屏那一瞬返回 401，首页于是长期显示「已建档 0 家」，
    # 而这个账号下有 6 家公司。
    #
    # 「没查到」和「查了，是 0」必须能分辨 —— 这是本仓反复出现的同一条。
    viewer_is_guest: bool = False
    drift_questions: list[dict[str, Any]] = []
    # 已经到期、还没人核对的管理层承诺。**这一条以前只存在于代码里**：
    # repository.due_promises() 写着"给今日概览用——到期了要顶到面前"，
    # main.py 也把它 import 进来了，而**从头到尾没有任何地方调用过它**。
    # 于是承诺台账那句「到期顶到你面前」的兑现方式是：你自己走进那家公司的
    # 档案页、翻到简报页签、往下拉。——跟认错条件那次是同一种失败
    # （算法对的，没有出口）。
    promises_due: list[dict[str, Any]] = []


class RecordRevision2(BaseModel):
    """复核视图里的逻辑版本快照。"""

    version: int
    snapshot: dict[str, Any]
    changed_fields: str
    change_note: str
    created_at: datetime


class ReviewVerdict(StrEnum):
    supported = "supported"
    challenged = "challenged"
    broken = "broken"
    watching = "watching"


class ThesisReviewCreate(BaseModel):
    """复核结论由用户写；系统只保存结论、依据和当时的市场状态。"""

    verdict: ReviewVerdict
    note: str = Field(min_length=3, max_length=1500)
    new_status: ThesisStatus | None = None
    next_review_date: date | None = None
    next_review_trigger: str | None = Field(default=None, max_length=200)


class ThesisReviewRecord(BaseModel):
    id: int
    thesis_id: int
    company_id: int
    verdict: str
    verdict_label: str | None = None
    note: str
    previous_status: str
    new_status: str
    next_review_date: date | None = None
    thesis_version: int | None = None
    support_evidence: int = 0
    counter_evidence: int = 0
    event_count: int = 0
    price_at_review: float | None = None
    pe_percentile_at_review: float | None = None
    unrealized_at_review: float | None = None
    realized_at_review: float | None = None
    created_at: datetime
    claim: str | None = None
    symbol: str | None = None
    company_name: str | None = None


class ReviewQueueItem(BaseModel):
    thesis_id: int
    company_id: int
    symbol: str
    company_name: str
    claim: str
    counter_condition: str
    status: ThesisStatus
    next_review_trigger: str
    next_review_date: date | None = None
    last_reviewed_at: datetime | None = None
    created_at: datetime
    new_counter_evidence: int = 0
    new_support_evidence: int = 0
    new_high_events: int = 0
    trade_review_due: date | None = None
    review_count: int = 0
    has_position: bool = False
    reasons: list[str] = []
    due_since: date


class ReviewContextPrice(BaseModel):
    latest: float | None = None
    change_percent: float | None = None
    market_timestamp: datetime | None = None
    price_20d_change: float | None = None
    ytd_change: float | None = None
    one_year_change: float | None = None
    latest_trade_date: date | None = None


class ReviewContextValuation(BaseModel):
    label: str
    current: float | None = None
    percentile: float | None = None
    sample_note: str | None = None


class ReviewEvidenceItem(EvidenceRecord):
    since_last_review: bool = False


class ReviewEventItem(ResearchEventRecord):
    since_last_review: bool = False


class ThesisReviewContext(BaseModel):
    thesis: dict[str, Any]
    since: datetime
    revisions: list[RecordRevision2]
    evidences: list[ReviewEvidenceItem]
    events: list[ReviewEventItem]
    trades: list[TradeRecord]
    position: PositionRecord | None = None
    price: ReviewContextPrice
    valuation: list[ReviewContextValuation]
    reviews: list[ThesisReviewRecord]


class ReviewQuarter(BaseModel):
    period: str
    supported: int = 0
    challenged: int = 0
    broken: int = 0
    watching: int = 0
    total: int = 0
    realized: float = 0
    unrealized: float = 0
    reviews: list[ThesisReviewRecord]


class MethodAttribution(BaseModel):
    """某个方法写下的逻辑，后来站住了几条。

    hit_rate 只在「已经有结论」的逻辑里算——还在观察的既不算对也不算错，
    算进分母会让所有方法看起来都很差。样本少时 note 会明说不要下结论。
    """

    method: str
    total: int
    intact: int = 0
    watching: int = 0
    challenged: int = 0
    broken: int = 0
    settled: int = 0
    hit_rate: float | None = None
    note: str = ""


class ReviewAttribution(BaseModel):
    quarters: list[ReviewQuarter]
    total_reviews: int
    by_method: list[MethodAttribution] = []


class ThesisMethodSummary(BaseModel):
    key: str
    name: str
    category: str
    category_label: str
    one_liner: str
    core_question: str
    beginner: bool
    effort: str
    related_strategy: str | None


class ThesisMethod(ThesisMethodSummary):
    origin: str
    steps: list[str]
    claim_template: str
    counter_template: str
    trigger_template: str
    fits: list[str]
    not_fits: list[str]
    caution: str


class ThesisMethodCategory(BaseModel):
    key: str
    label: str
    intro: str
    methods: list[ThesisMethodSummary]


class ThesisMethodLibrary(BaseModel):
    categories: list[ThesisMethodCategory]
    boundary: str


class InboxBatchResult(BaseModel):
    archived: int
    failed: int
    note: str


class InboxTidyResult(BaseModel):
    classified: int
    by_model: int
    archived: int
    ignored: int
    remaining: int
    note: str


class ThesisBasis(BaseModel):
    point: str
    evidence: str = ""
    as_of: str = ""


class ThesisCounter(BaseModel):
    """一条反证条件。指标、门槛、含义分开——写成一段话就没法逐条核对。"""

    metric: str = ""
    threshold: str = ""
    means: str = ""


class ThesisReview(BaseModel):
    when: str = ""
    what: list[str] = []


class ThesisStructure(BaseModel):
    """可分块渲染的那一份。

    平文本的 claim / counter_condition 仍然保留（数据库那两列不动），
    页面优先按块渲染，取不到结构就回落到平文本。
    """

    headline: str = ""
    basis: list[ThesisBasis] = []
    counters: list[ThesisCounter] = []
    review: ThesisReview = ThesisReview()


class ThesisDraft(BaseModel):
    claim: str
    counter_condition: str
    next_review_trigger: str
    structure: ThesisStructure = ThesisStructure()
    used_facts: list[str]
    unknowns: list[str]
    trackable_fields: list[str]
    model: str
    method: str | None
    boundary: str
    billing: Billing = Billing()
    # 它自己查了哪几张表。**摆出来是"它没瞎说"最直接的证明**，
    # 也是使用者判断这条草稿值不值得逐句读的第一个信号。
    # 塞资料那条路（模型不支持工具时的回落）留空。
    read: str = ""


class TaskAutoReviewResult(BaseModel):
    reviewed: int
    counts: dict[str, int]
    note: str


class NewsItem(BaseModel):
    id: int
    feed_key: str
    feed_name: str
    title: str
    url: str
    summary: str
    published_at: datetime
    company_id: int | None
    company_name: str | None = None
    symbol: str | None = None
    match_confidence: str
    match_reason: str
    match_source: str
    status: str
    # 阅读是独立于“待确认 / 已归档 / 已忽略”的个人动作：看过不代表已经归档。
    read_at: datetime | None = None


class NewsPage(BaseModel):
    items: list[NewsItem]
    total: int
    linked: int
    boundary: str
    # 页面要把「待处理 / 已读 / 未读 / 已忽略」分开显示。
    # 这些是全量计数，不随当前筛选项变化，避免筛选后出现「已对应 4」但列表为空的错觉。
    all: int = 0
    pending: int = 0
    archived: int = 0
    ignored: int = 0
    read: int = 0
    unread: int = 0


class NewsRefreshResult(BaseModel):
    fetched: int
    matched: int
    failures: list[str]
    note: str
    billing: Billing = Billing()


class SupplyChainLink(BaseModel):
    id: int
    company_id: int
    relation: str
    counterpart: str
    # 图上放得下的短名，由后端在读取时从 counterpart 派生。
    # **必须在这里声明**——响应模型会把没声明的键静默丢掉，页面拿不到就画不成图。
    label: str = ""
    segment: str
    detail: str
    confidence: str
    source: str
    evidence_id: int | None = None
    created_at: datetime


class SupplyChainView(BaseModel):
    links: list[SupplyChainLink]
    confirmed: int
    boundary: str
    billing: Billing = Billing()


class IndustryChainThemeCreate(BaseModel):
    """新建一张空白底图；只创建通用阶段骨架，不编造任何行业事实。"""

    name: str = Field(min_length=2, max_length=80)
    chain_type: str = Field(default="制造链", min_length=2, max_length=20)
    description: str = Field(default="", max_length=500)


class IndustryChainDraftRequest(BaseModel):
    """从公开资料起草一张可编辑的产业链图。"""

    topic: str = Field(min_length=2, max_length=80)


class IndustryChainStageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    stage_kind: str = Field(default="core", max_length=20)
    description: str = Field(default="", max_length=300)
    stage_order: int | None = Field(default=None, ge=0, le=10000)


class IndustryChainNodeCreate(BaseModel):
    stage_id: int
    parent_id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    node_type: str = Field(default="产品", max_length=20)
    description: str = Field(default="", max_length=500)
    source_name: str = Field(default="", max_length=120)
    source_url: str = Field(default="", max_length=1000)
    verification: str = Field(default="待补证", max_length=20)
    node_order: int | None = Field(default=None, ge=0, le=10000)
    upstream_node_id: int | None = None
    relation_type: str = Field(default="流向", max_length=30)


class IndustryChainEdgeCreate(BaseModel):
    from_node_id: int
    to_node_id: int
    relation_type: str = Field(default="流向", max_length=30)
    detail: str = Field(default="", max_length=500)
    source_name: str = Field(default="", max_length=120)
    source_url: str = Field(default="", max_length=1000)
    verification: str = Field(default="待补证", max_length=20)


class IndustryChainPositionCreate(BaseModel):
    node_id: int
    company_id: int
    role: str = Field(default="参与者", max_length=30)
    detail: str = Field(default="", max_length=500)
    source_name: str = Field(default="", max_length=120)
    source_url: str = Field(default="", max_length=1000)
    verification: str = Field(default="待补证", max_length=20)
    valid_from: date | None = None
    valid_to: date | None = None


class IndustryChainThemeSummary(BaseModel):
    id: int
    name: str
    chain_type: str
    description: str
    is_default: bool = False
    category: str = "我的主题"
    recommended: bool = False
    recommendation_score: int = 0
    recommendation_reason: str = ""
    stage_count: int = 0
    node_count: int = 0
    company_count: int = 0
    updated_at: datetime


class IndustryChainCompanyPosition(BaseModel):
    id: int
    company_id: int
    company_name: str
    symbol: str
    node_id: int
    role: str
    detail: str
    source_name: str
    source_url: str
    verification: str
    valid_from: date | None = None
    valid_to: date | None = None


class IndustryChainNode(BaseModel):
    id: int
    theme_id: int
    stage_id: int
    parent_id: int | None = None
    name: str
    node_type: str
    description: str
    source_name: str
    source_url: str
    verification: str
    node_order: int
    positions: list[IndustryChainCompanyPosition] = Field(default_factory=list)


class IndustryChainStage(BaseModel):
    id: int
    theme_id: int
    name: str
    stage_kind: str
    description: str
    stage_order: int
    nodes: list[IndustryChainNode] = Field(default_factory=list)


class IndustryChainEdge(BaseModel):
    id: int
    theme_id: int
    from_node_id: int
    to_node_id: int
    relation_type: str
    detail: str
    source_name: str
    source_url: str
    verification: str


class IndustryChainView(BaseModel):
    id: int
    name: str
    chain_type: str
    description: str
    is_default: bool = False
    stages: list[IndustryChainStage] = Field(default_factory=list)
    edges: list[IndustryChainEdge] = Field(default_factory=list)
    node_count: int = 0
    company_count: int = 0
    boundary: str
    created_at: datetime
    updated_at: datetime


class CompanyIndustryChainTheme(BaseModel):
    theme_id: int
    theme_name: str
    chain_type: str
    positions: list[dict[str, Any]] = Field(default_factory=list)


class CompanyIndustryChainPositions(BaseModel):
    company_id: int
    themes: list[CompanyIndustryChainTheme] = Field(default_factory=list)


class ResearchReport(BaseModel):
    id: int
    company_id: int
    company_name: str
    symbol: str
    version: int
    title: str
    body: str
    business: list[str] = []
    changes: list[str] = []
    implications: list[str] = []
    # 深度报告（联网那一版）。**必须在这里声明**——响应模型会把没声明的键
    # 静默丢掉，页面就画不出图。这个坑已经踩过三次。
    kind: str = "local"
    cards: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    themes: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    queries: list[str] = []
    facts: dict[str, Any] = {}
    # 每条带 ref / evidence_id / url：正文里的 [3] 要能点回真正的那条证据。
    citations: list[dict[str, Any]]
    unknowns: list[str]
    source_count: int
    model: str
    created_at: datetime
    billing: Billing = Billing()


class BackgroundJob(BaseModel):
    id: int
    kind: str
    target_id: int
    label: str
    status: str
    progress: int
    total: int
    note: str
    error: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    credits: int = 0
    tokens: int = 0
    metered: bool = False
    # 任务的结构化产出（读图结果这类）。没有就是 None，不是空对象。
    result: dict[str, Any] | None = None


class UniverseRederiveResult(BaseModel):
    derived: int
    total: int
    pe_coverage: int
    pb_coverage: int
    market_cap_coverage: int
    note: str


class NewsFeedInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    url: HttpUrl
    key: str | None = Field(default=None, max_length=40)
    enabled: bool = True


class NewsFeed(BaseModel):
    id: int
    key: str
    name: str
    url: str
    enabled: bool
    builtin: bool
    last_ok_at: datetime | None = None
    last_error: str = ""
    item_count: int = 0


class DailyBriefing(BaseModel):
    as_of: str
    headline: str
    market: str = ""
    holdings: str = ""
    pending: str = ""
    watchlist: str = ""
    actions: list[str] = []
    gaps: list[str] = []
    # 生成这份简报时代码算好的那批数（涨跌家数、行业涨跌、持仓浮盈）。
    # **必须在这里声明**——响应模型会把没声明的键静默丢掉，页面就画不出图。
    # 这个坑今天是第三次踩了（前两次是候选初筛的 verdict/reasons、产业链的 label）。
    context: dict[str, Any] = {}
    boundary: str = ""
    model: str = ""
    created_at: datetime
    billing: Billing = Billing()
