import { apiUrl, ROUTE_BASE } from "./config";
import { formatDateTime } from "./lib/datetime";
import { errorMessage } from "./lib/errormessage";
import { nextCursor } from "./lib/listcursor";
import { PanelTitle } from "./components/PanelTitle";
import { Fold } from "./components/Fold";
import { Headline } from "./components/Headline";
import { Boundary } from "./components/Boundary";
import { Source } from "./components/Source";
import { PlatformFooter, PlatformHeader } from "./components/PlatformChrome";
import { ResearchSummary } from "./components/ResearchSummary";
import { IndustryPositionMap } from "./components/IndustryPositionMap";
import {
  Archive,
  ArrowLeft,
  BookOpen,
  FileText,
  ChevronRight,
  CircleGauge,
  ClipboardCheck,
  Database,
  HardDriveDownload,
  Map as MapIcon,
  Network,
  ListChecks,
  Scale,
  SlidersHorizontal,
  History,
  LayoutDashboard,
  LibraryBig,
  Link2,
  ListTodo,
  Menu,
  Plus,
  Wallet,
  Search,
  Settings2,
  ShieldCheck,
  X,
  ChevronDown,
  Workflow,
  Compass,
  Repeat2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Fragment, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

import {
  getMoneyFlow,
  getSchedule,
  type MoneyFlowView,
  type ScheduleView,
  createCompanyFromQuote,
  createEvidence,
  archiveInboxItem,
  createBackup,
  createPortfolio,
  createResearchEvent,
  createResearchTask,
  createThesisReview,
  createThesis,
  createTrade,
  setHolding,
  deletePortfolio,
  deleteHolding,
  getDecisionBoard,
  getInboxLearning,
  saveRuleTerm,
  deleteRuleTerm,
  deleteTrade,
  getBackups,
  getCompanies,
  lookupUniverse,
  getCompany,
  getDataProviders,
  getDashboard,
  getHeatmap,
  archiveInboxBatch,
  classifyInbox,
  confirmChainLink,
  confirmNews,
  deleteChainLink,
  generateReport,
  getNews,
  getNewsFeeds,
  saveNewsFeed,
  toggleNewsFeed,
  deleteNewsFeed,
  getReports,
  getSupplyChain,
  ignoreNews,
  markNewsRead,
  autoReviewTask,
  getJob,
  getBriefing,
  generateBriefing,
  refreshNews,
  refreshSupplyChain,
  rederiveUniverse,
  draftThesis,
  getMethod,
  tidyInbox,
  getAssessment,
  getTimeline,
  getAssessmentMatrix,
  getSyncStrip,
  writeThesis,
  deleteThesis,
  startCandidateReview,
  getCandidateReviewJob,
  saveCandidateReview,
  getSavedCandidateReview,
  checkCounterHits,
  runAssessment,
  getSettings,
  saveSettings,
  getMethodLibrary,
  getInbox,
  getIndustries,
  getIndustryComparison,
  getLocalData,
  getPortfolio,
  getPortfolios,
  getQuotePreview,
  getAllTheses,
  loadSamples,
  removeSamples,
  type ThesisListItem,
  getReviewContext,
  getResearchTasks,
  getReviewQueue,
  getScreenFields,
  getScreenStrategies,
  getAiPickOptions,
  getAiPickStatus,
  startAiPick,
  getRevisions,
  getSyncJobs,
  getUniverseSummary,
  getWatchGroups,
  getSyncRuns,
  ignoreInboxByRelevance,
  ignoreInboxItem,
  reopenInboxItem,
  refreshCompanyFinancials,
  refreshCompanyMarketHistory,
  refreshCompanyProfile,
  refreshCompanyValuation,
  refreshMarket,
  restoreBackup,
  reviseThesis,
  importWatchlist,
  deleteScreenStrategy,
  previewScreen,
  runScreen,
  saveScreenStrategy,
  runSyncJob,
  updateCompany,
  updateResearchTask,
  deleteResearchTask,
  updateSyncJob,
  updateTaskItem,
  reviseTrade,
  updateResearchEvent,
  updateThesis,
  getSegments,
  refreshSegments,
  getEvidenceDirection,
  getEvidenceDirectionPlan,
  judgeEvidenceDirection,
  getPeerTable,
  assessTaskItem,
  getDeepReportPlan,
  makeDeepReport,
  addChainLink,
  deleteReport,
} from "./api";
import type { AssessmentView, DeepReportPlan, EvidenceDirectionPlan, EvidenceDirectionView, PeerTableView, SegmentView, ValueCandidates } from "./api";
import type { TimelinePayload } from "./components/CompanyTimeline";
import type { MatrixRow } from "./components/AssessmentMatrix";
import type { SyncStripJob } from "./api";
import type {
  BackgroundJob,
  DailyBriefing,
  NewsFeed,
  ResearchTaskItem,
  NewsItem,
  NewsPage,
  ResearchReport,
  SupplyChainView,
  ThesisDraft,
  ThesisStructure,
  Billing,
  DecisionBoard,
  InboxLearning,
  ThesisMethod,
  ThesisMethodLibrary,
  BackupManifest,
  CompanyCalendarEvent,
  EvidencePolarity,
  EventImportance,
  InboxItem,
  HeatmapView,
  InboxPage,
  IndustryComparison,
  IndustryAggregate,
  IndustrySummary,
  CompanyDetail,
  CompanyRecord,
  UniverseMatch,
  DataProviderStatus,
  DashboardSummary,
  EvidenceInput,
  FinancialMetricCard,
  FinancialPeriod,
  FinancialSummary,
  LocalDataSummary,
  PortfolioDetail,
  PortfolioSummary,
  PositionRecord,
  RecordRevision,
  ResearchEventInput,
  ResearchTaskRecord,
  ReviewQueueItem,
  ReviewVerdict,
  AiPickOptions,
  AiPickResult,
  ScreenCandidate,
  ScreenCheck,
  ScreenField,
  ScreenRule,
  ScreenResult,
  ScreenStrategy,
  SyncJobStatus,
  SyncJobUpdateInput,
  SyncRunRecord,
  ThesisInput,
  UniverseSummary,
  ThesisRecord,
  ThesisReviewContext,
  WatchGroupSummary,
  WatchlistImportResult,
  WatchlistImportRow,
  ThesisStatus,
  TradeRecord,
  QuotePreview,
} from "./types";
import { TRADE_SIDE_LABEL } from "./types";
import { ShowMore } from "./components/ShowMore";
import { ConfirmHost, confirmAction } from "./lib/confirm";
import { useSpendGuard } from "./lib/credits";
import { useIsOwner } from "./lib/owner";

const emptyDashboard: DashboardSummary = {
  as_of: new Date().toISOString(),
  demo: false,
  counter_hits: 0,
  counter_uncompared: 0,
  theses_without_counter: 0,
  inbox_backlog: 0,
  intact_theses: 0,
  theses_to_review: 0,
  total_theses: 0,
  theses_watching: 0,
  next_review_due: null,
  unread_events: 0,
  data_health: "等待本地 API 连接",
  data_alerts: [],
  market_tiles: [],
  watchlist: [],
  theses: [],
  events: [],
  portfolio_exposure: [],
  exposure_basis: "研究池分布",
  holding_market_value: null,
  holding_unrealized_percent: null,
  holdings_reviews_due: 0,
  inbox_pending: 0,
  viewer_is_guest: false,
  drift_questions: [],
  promises_due: [],
};

const PriceTrend = lazy(async () => {
  const module = await import("./components/PriceTrend");
  return { default: module.PriceTrend };
});

import { ThesisBar, TodayCard, type TodoBucket } from "./components/TodayCard";

// 拆分器搬到 lib/ 并单测了：它切错过两次，而切错的表现是"内容对、读不通"，
// 人会以为模型写坏了。见 lib/thesisText.test.ts。
import { splitClauses, thesisRest } from "./lib/thesisText";

/**
 * 驾驶舱是**唯一一个直接 import 的图表组件**，而它把 echarts（626 kB）
 * 拽进了首屏包——于是公司列表、研究任务、设置这些一张图都没有的页面
 * 也要先下完这 626 kB 才开始渲染。实测：三个页面首屏都是 1716 kB。
 *
 * 改成懒加载之后，只有真正要画图的那一屏才去取它。
 */
const MarketCockpit = lazy(() => import("./components/MarketCockpit").then((m) => ({ default: m.MarketCockpit })));
const AgentPool = lazy(() => import("./components/AgentPool").then((m) => ({ default: m.AgentPool })));
const QuickThesis = lazy(() => import("./components/QuickThesis").then((m) => ({ default: m.QuickThesis })));
const CommonRisk = lazy(() => import("./components/CommonRisk").then((m) => ({ default: m.CommonRisk })));
const IndustryMetrics = lazy(() => import("./components/IndustryMetrics").then((m) => ({ default: m.IndustryMetrics })));
const MoneyFlow = lazy(() => import("./components/MoneyFlow").then((m) => ({ default: m.MoneyFlow })));
const ChainPosition = lazy(() => import("./components/ChainPosition").then((m) => ({ default: m.ChainPosition })));
const Promises = lazy(() => import("./components/Promises").then((m) => ({ default: m.Promises })));
const Schedule = lazy(() => import("./components/Schedule").then((m) => ({ default: m.Schedule })));
const Documents = lazy(() => import("./components/Documents").then((m) => ({ default: m.Documents })));
const Advocate = lazy(() => import("./components/Advocate").then((m) => ({ default: m.Advocate })));
const CounterHitBanner = lazy(() => import("./components/CounterHitBanner").then((m) => ({ default: m.CounterHitBanner })));
const ValuationScenarios = lazy(() => import("./components/ValuationScenarios").then((m) => ({ default: m.ValuationScenarios })));
// 常量单独同步导入：懒加载的模块要等点开才到，而这个 key 在渲染卡片时就要用。
const AGENT_POOL_KEY = "__agent_pool__";
/** AI 选股也用哨兵值占一个位置：它跟策略并排出现在同一个选择里，
 *  但它不在策略库里——拿去查库必然查不到（综合榜为此漏过一次内部标识符到页面上）。 */
const AI_PICK_KEY = "__ai_pick__";
/** 不在策略库里的那几个 key。拿它们去查库必然查不到，
 *  而漏掉一个的表现是页面上冒出一条英文红字「strategy not found」。 */
const SENTINEL_KEYS = new Set([AGENT_POOL_KEY, AI_PICK_KEY]);
const EvidenceAxis = lazy(() => import("./components/EvidenceAxis").then((m) => ({ default: m.EvidenceAxis })));
const BriefingCharts = lazy(() => import("./components/BriefingCharts").then((m) => ({ default: m.BriefingCharts })));
const MarketPeerTable = lazy(() => import("./components/MarketPeerTable").then((m) => ({ default: m.MarketPeerTable })));
const DeepReport = lazy(() => import("./components/DeepReport").then((m) => ({ default: m.DeepReport })));
const ReportBody = lazy(() => import("./components/ReportBody").then((m) => ({ default: m.ReportBody })));
const ChainMap = lazy(() => import("./components/ChainMap").then((m) => ({ default: m.ChainMap })));
const IndustryChainPage = lazy(() => import("./components/IndustryChainPage").then((m) => ({ default: m.IndustryChainPage })));
const CompanyChainPositions = lazy(() => import("./components/CompanyChainPositions").then((m) => ({ default: m.CompanyChainPositions })));
const SegmentMix = lazy(() => import("./components/SegmentMix").then((m) => ({ default: m.SegmentMix })));
const GrowthChart = lazy(() => import("./components/GrowthChart").then((m) => ({ default: m.GrowthChart })));

// 我的判断新增的三页。**都走 lazy**：它们各自带着一套判据表与图，
// 而大多数会话里一页都不会打开。
const DecisionLoop = lazy(() => import("./components/DecisionLoop").then((m) => ({ default: m.DecisionLoop })));
const SwingLab = lazy(() => import("./components/SwingLab").then((m) => ({ default: m.SwingLab })));
const RallyType = lazy(() => import("./components/RallyType").then((m) => ({ default: m.RallyType })));

const HeatmapChart = lazy(async () => {
  const module = await import("./components/HeatmapChart");
  return { default: module.HeatmapChart };
});

const ValuationTrend = lazy(async () => {
  const module = await import("./components/ValuationTrend");
  return { default: module.ValuationTrend };
});

type Page = "dashboard" | "review" | "reviews" | "companies" | "company" | "industries" | "screener" | "heatmap" | "tasks" | "methods" | "news" | "chain" | "reports" | "prefs" | "portfolio" | "data" | "backups" | "docs" | "loop" | "swing" | "rally";
type Composer = "thesis" | "evidence" | "event" | null;

const statusCopy: Record<ThesisStatus, { label: string; detail: string }> = {
  intact: { label: "成立", detail: "现有事实继续支持" },
  watching: { label: "待观察", detail: "等待验证窗口" },
  challenged: { label: "受挑战", detail: "已出现重要反证" },
  broken: { label: "已破坏", detail: "关键条件不再成立" },
};

interface NavItem {
  id?: Exclude<Page, "company">;
  label: string;
  icon: LucideIcon;
  available?: boolean;
  /** 只给站主看。备份/还原/整库导出是 require_owner 的，
   *  对其他人显示等于给一个点了就 403 的入口。 */
  ownerOnly?: boolean;
}

interface NavGroup {
  label: string;
  /** 一句话说清这一段在漏斗里干什么。导航要回答"我这一步要做什么"，不是"这里有什么数据"。 */
  hint: string;
  items: NavItem[];
}

/**
 * 导航按**研究漏斗**排，不按数据类型排。
 *
 * ## 为什么要改
 *
 * 原来是 16 项，分「研判 / 研究 / 系统」三组，而「研究」那一组里躺着
 * 公司档案、持仓、行业对照、价值候选、市场云图、研究任务、方法库、资讯证据、
 * 产业链地图、研究报告十项——它们是按**数据类型**并列的，等于把
 * 「你这一步要干什么」这件事全部推给用户自己在脑子里拼。
 *
 * 而个人投资者研究的实际形状是一个漏斗（这是查到的公开经验，不是拍脑袋）：
 * 宽筛几千只 → 挑出 10–20 只浅研究（每家 1–2 小时）→ 再挑 3–5 只深研究
 * （每家 5–10 小时）。每周 5–10 小时的人，一个月能真正研究透 4–8 家。
 *
 * 所以一级导航就是这个漏斗的四段 + 设置：
 *
 *   今天（今天有什么变了）→ 找票（宽筛）→ 公司（深研）→ 我的判断（决策与复盘）
 *
 * ## 为什么第一项叫「今天」
 *
 * 散户最普遍的痛点是信息过载：四千多只票、研报读不懂、热点轮动快。
 * 同花顺被诟病最多的一条是「瀑布流式的资讯无法保证用户在付出阅读时间后
 * 收获期望价值」——**时间投入不转化为价值**。所以这一段的承诺必须是
 * 「今天只有这几件事值得你看」，而不是"这里有很多信息"。
 *
 * ## 为什么保留「我的判断」
 *
 * 一度想把它折叠掉（那几张表现在是空的）。但公开的亏损归因里，
 * 排在追涨杀跌之后的就是「缺乏系统的交易记录和复盘能力」——
 * 它不是等你成熟了才用的高级功能，它就是亏钱的直接原因之一。
 * 该做的是降低写下判断的门槛，不是把入口藏起来。
 *
 * ## 产业链底图放在找票，经营关系线索留在公司
 *
 * 产业链底图是跨公司的行业研究资产：先画产品/服务，再把多家公司定位进去，
 * 所以属于找票。某家公司可能跟谁采购、销售或竞争，只是公司级经营关系线索，
 * 留在公司详情页，不能再冒充产业链地图。
 */
const navGroups: NavGroup[] = [
  {
    label: "今天",
    hint: "今天有什么变了",
    items: [
      { id: "dashboard", label: "决策总览", icon: LayoutDashboard, available: true },
      { id: "review", label: "待办复核", icon: ListTodo, available: true },
      { id: "news", label: "资讯证据", icon: LibraryBig, available: true },
    ],
  },
  {
    label: "找票",
    hint: "从五千只里挑出值得花时间的",
    items: [
      { id: "screener", label: "价值候选", icon: SlidersHorizontal, available: true },
      // 研究任务是找票的**产出**（我存下的清单），紧跟着候选。
      { id: "tasks", label: "研究任务", icon: ListChecks, available: true },
      { id: "chain", label: "产业链地图", icon: Network, available: true },
      // 云图与行业对照排最后：它们是背景，**不改变任何一个决定**。
      // 不删（看板块在动是有用的上下文），但不该跟"找票"平起平坐。
      { id: "heatmap", label: "市场云图", icon: MapIcon, available: true },
      { id: "industries", label: "行业对照", icon: Scale, available: true },
    ],
  },
  {
    label: "公司",
    hint: "一家一家看透",
    items: [
      { id: "companies", label: "公司档案", icon: Archive, available: true },
      { id: "methods", label: "投资方法库", icon: BookOpen, available: true },
      // **读文档跟投资方法库并列**：两者都是跨公司的工具，不属于某一家。
      // 不放「今天」——那一页是"今天有什么变了"的看板，而读 PDF 是个长耗时的动作，
      // 混进去之后它就不再是扫一眼就知道该干什么。
      { id: "docs", label: "读文档", icon: FileText, available: true },
    ],
  },
  {
    label: "我的判断",
    hint: "写下来、跟踪、复盘",
    items: [
      // **闭环排第一。** 这一段原来只有账本和复核两项，等于"写完之后"的工具；
      // 而使用者卡住的地方在"写完到动手"之间 —— 研究完了不知道什么时候买，
      // 价格到了不知道该不该买，涨了不知道是不是自己错了。
      // 决策闭环就是那一段，所以它是这一组的第一项。
      { id: "loop", label: "我的跟踪", icon: Workflow, available: true },
      { id: "portfolio", label: "持仓账本", icon: Wallet, available: true },
      // 涨跌归因跟做 T 回测都是**给判断当参照的算术**：一个回答"它为什么涨"，
      // 一个回答"波动到底能不能吃到"。放在账本之后、复核之前——
      // 它们服务的是"我要不要改主意"，而不是"我记了什么"。
      { id: "rally", label: "涨跌归因", icon: Compass, available: true },
      { id: "swing", label: "做 T 回测", icon: Repeat2, available: true },
      { id: "reviews", label: "复核工作台", icon: ClipboardCheck, available: true },
    ],
  },
  {
    label: "设置",
    hint: "",
    items: [
      { id: "data", label: "数据状态", icon: Database, available: true, ownerOnly: true },
      { id: "backups", label: "备份与恢复", icon: HardDriveDownload, available: true, ownerOnly: true },
      { id: "prefs", label: "偏好设置", icon: Settings2, available: true },
    ],
  },
];

/** 当前页属于哪个分区。分区页签靠它决定显示哪一条。 */
function sectionOf(page: Page): NavGroup {
  const key = page === "company" ? "companies" : page;
  return navGroups.find((group) => group.items.some((item) => item.id === key)) ?? navGroups[0];
}



function formatShortDate(value: string | null): string {
  if (!value) return "未复核";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date(`${value}T00:00:00`));
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatMoney(value: number | null, digits = 2): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `¥ ${value.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function formatSigned(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** A 股惯例：红涨绿跌。这里只描述盈亏方向，不表示应当买入或卖出。 */
function signedPercentText(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "暂无数据";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function pnlClass(value: number | null): string {
  if (value === null || value === 0) return "";
  return value > 0 ? "quote-up" : "quote-down";
}



function StatusBadge({ status }: { status: ThesisStatus }) {
  return (
    <span className={`status-badge status-badge--${status}`} title={statusCopy[status].detail}>
      <span />
      {statusCopy[status].label}
    </span>
  );
}

function Sidebar({
  open,
  page,
  reviewCount,
  dataSource,
  onClose,
  onNavigate,
}: {
  open: boolean;
  dataSource: "loading" | "api" | "error";
  page: Page;
  reviewCount: number;
  onClose: () => void;
  onNavigate: (page: Exclude<Page, "company">) => void;
}) {
  const isOwner = useIsOwner();
  return (
    <>
      {open && <button className="sidebar-scrim" aria-label="关闭导航" onClick={onClose} />}
      <aside className={`sidebar ${open ? "sidebar--open" : ""}`}>
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true"><span /><span /><span /></div>
          <div><strong>虾米看股</strong><span>长期研究工作台</span></div>
          <button className="icon-button sidebar-close" aria-label="关闭导航" onClick={onClose}><X size={18} /></button>
        </div>
        {/* **一级导航只有五项**：漏斗的四段 + 设置。
            分区里的具体页面做成内容区顶部的页签——十六个并列入口等于把
            "我这一步要干什么"全推给用户自己在脑子里拼。 */}
        <nav aria-label="主导航">
          {navGroups.map((group) => {
            // **落到他打得开的第一项。** 「设置」这一组的第一项是数据状态，
            // 而它现在是站主专属 —— 非站主点「设置」会正好落在那句「只有站主能看」上。
            const landing = group.items.find((item) => !item.ownerOnly || isOwner === true) ?? group.items[0];
            const current = sectionOf(page);
            const active = current.label === group.label;
            const Icon = group.items[0].icon;
            // **徽章只报反证，不报公告未读数。**
            //
            // 原来挂的是「未读公告 + 待分级」，实测长期停在 646——
            // 一个永远清不完的红点，第三天就被当成背景了，
            // 之后真正要紧的事再也没法用徽章提醒你。
            // 而反证命中是唯一一种"你自己写下的那件事真的发生了"的提醒，
            // 它天然是个位数，也天然值得中断你。
            const badge = group.label === "今天" ? reviewCount : 0;
            return (
              <button
                className={`nav-item nav-section ${active ? "nav-item--active" : ""}`}
                key={group.label}
                aria-current={active ? "page" : undefined}
                onClick={() => onNavigate(landing.id as Exclude<Page, "company">)}
              >
                <Icon size={17} strokeWidth={1.8} />
                {/* **副标题只留在选中那一项上。**
                    五项各带一行小字，等于侧栏永远有五行解释在那儿；
                    而它们要回答的是"我现在在哪、这里是干什么的"——
                    那只对当前这一项成立。其余四项只需要认得出名字。 */}
                <span>{group.label}{active && group.hint && <em className="nav-hint">{group.hint}</em>}</span>
                {badge > 0 && <em>{badge}</em>}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          {/* 数据源状态从顶部工具条挪到这里：它是常驻状态而不是操作，
              放在顶部会和平台页眉挤在一起，也和右上角的账号区争注意力。 */}
          <span className={`sidebar-source sidebar-source--${dataSource}`}><i />{dataSource === "api" ? "StockSDK 已同步" : dataSource === "loading" ? "正在连接" : "API 未连接"}</span>
          <div className="sidebar-note"><ShieldCheck size={15} /><strong>只辅助研究，不替你决策</strong></div>
        </div>
      </aside>
    </>
  );
}

function ThesisLedger({ dashboard, onOpenCompany }: { dashboard: DashboardSummary; onOpenCompany: (id: number) => void }) {
  const statusSegments = [
    { key: "intact", label: "成立", value: dashboard.intact_theses, className: "tstate--intact" },
    { key: "watching", label: "观察中", value: dashboard.theses_watching, className: "tstate--watching" },
    { key: "due", label: "待复核", value: dashboard.theses_to_review, className: "tstate--due" },
  ].filter((item) => item.value > 0);
  const supportTotal = dashboard.theses.reduce((sum, thesis) => sum + thesis.evidence_count, 0);
  const counterTotal = dashboard.theses.reduce((sum, thesis) => sum + thesis.counter_evidence_count, 0);
  const evidenceTotal = supportTotal + counterTotal;

  return (
    <section className="panel ledger-panel" aria-labelledby="ledger-title">
      <div className="panel-heading"><div><span className="eyebrow">核心工作区</span><PanelTitle id="ledger-title" hint="先看哪些判断需要重审，再决定要不要看价格。">投资逻辑账本</PanelTitle><p className="ledger-heading-note">把长句压成一句判断，状态和证据用图看。</p></div><span className="muted-label">点击条目进入档案</span></div>
      <div className="ledger-visual-summary" aria-label={`共 ${dashboard.total_theses} 条投资逻辑，支持证据 ${supportTotal} 条，反证证据 ${counterTotal} 条`}>
        <div className="ledger-summary-total"><strong>{dashboard.total_theses}</strong><span>条判断</span></div>
        <div className="ledger-summary-status">
          <div className="ledger-status-bar" role="img" aria-label={statusSegments.map((item) => `${item.label} ${item.value}`).join("、") || "暂无判断"}>
            {statusSegments.map((item) => <i key={item.key} className={item.className} style={{ flexGrow: item.value }} title={`${item.label} ${item.value}`} />)}
          </div>
          <div className="ledger-status-labels">
            {statusSegments.map((item) => <span key={item.key}><i className={item.className} />{item.label} {item.value}</span>)}
          </div>
        </div>
        <div className="ledger-summary-evidence">
          <span><i className="ledger-evidence-dot ledger-evidence-dot--support" />支持 {supportTotal}</span>
          <span><i className="ledger-evidence-dot ledger-evidence-dot--counter" />反证 {counterTotal}</span>
          {evidenceTotal === 0 && <em>还没有归档证据</em>}
        </div>
      </div>
      <div className="ledger-list">
        {dashboard.theses.length === 0 && <div className="empty-state">还没有逻辑。先建立公司档案，再写下第一条可验证的判断。</div>}
        {dashboard.theses.map((thesis) => {
          const company = dashboard.watchlist.find((item) => item.id === thesis.company_id) ?? dashboard.watchlist.find((item) => item.symbol === thesis.symbol);
          const rowEvidenceTotal = thesis.evidence_count + thesis.counter_evidence_count;
          const supportWidth = rowEvidenceTotal > 0 ? (thesis.evidence_count / rowEvidenceTotal) * 100 : 0;
          const counterWidth = rowEvidenceTotal > 0 ? (thesis.counter_evidence_count / rowEvidenceTotal) * 100 : 0;
          return (
            <button className={`ledger-row ledger-row--${thesis.status}`} key={thesis.id} onClick={() => company && onOpenCompany(company.id)}>
              <div className="ledger-index" aria-hidden="true">{thesis.company_name.slice(-2)}</div>
              <div className="ledger-company"><span>{thesis.symbol}</span><strong>{thesis.company_name}</strong></div>
              <div className="ledger-claim"><p title={thesis.claim}>{thesis.claim}</p><span>下次复核：{thesis.next_review_trigger}</span></div>
              <div className="evidence-balance" aria-label={`支持 ${thesis.evidence_count} 条，反证 ${thesis.counter_evidence_count} 条`}>
                <div className="evidence-balance-track" aria-hidden="true"><i className="evidence-balance-support" style={{ width: `${supportWidth}%` }} /><i className="evidence-balance-counter" style={{ width: `${counterWidth}%` }} /></div>
                <div className="evidence-balance-labels"><span className="evidence-support">支持 {thesis.evidence_count}</span><span className="evidence-counter">反证 {thesis.counter_evidence_count}</span></div>
              </div>
              <StatusBadge status={thesis.status} />
            </button>
          );
        })}
      </div>
    </section>
  );
}

function EventsPanel({ dashboard, onOpenCompany }: { dashboard: DashboardSummary; onOpenCompany: (id: number) => void }) {
  return (
    <section className="panel event-panel" aria-labelledby="events-title">
      <div className="panel-heading compact"><div><span className="eyebrow">证据收件箱</span><h2 id="events-title">需要你判断的变化</h2></div><span className="count-chip">{dashboard.events.length}</span></div>
      <div className="event-list">
        {dashboard.events.length === 0 && <div className="empty-state">没有待处理事件。</div>}
        {dashboard.events.map((event) => <button className="event-item" key={event.id} onClick={() => onOpenCompany(event.company_id)}><div className={`event-pin event-pin--${event.importance}`} aria-hidden="true" /><div className="event-body"><div className="event-meta"><span>{event.company_name}</span><i>·</i><span>{event.category}</span><time dateTime={event.occurred_at}>{formatDateTime(event.occurred_at)}</time></div><h3>{event.title}</h3><span className="verification">{event.verification}</span></div></button>)}
      </div>
      <div className="panel-footnote">点击事件可归档证据、关联逻辑或完成核验。</div>
    </section>
  );
}

function ExposurePanel({ dashboard }: { dashboard: DashboardSummary }) {
  const byHolding = dashboard.exposure_basis === "持仓市值";
  return <section className="panel exposure-panel" aria-labelledby="exposure-title"><div className="panel-heading compact"><div><span className="eyebrow">{byHolding ? "持仓视角" : "研究视角"}</span><h2 id="exposure-title">{byHolding ? "持仓集中度" : "行业关注度"}</h2></div><CircleGauge size={19} aria-hidden="true" /></div><div className="exposure-list">{dashboard.portfolio_exposure.map((item) => <div className="exposure-row" key={item.name}><div><span>{item.name}</span><strong>{item.weight}%</strong></div><div className="exposure-track" aria-label={`${item.name} ${item.weight}%`}><span style={{ width: `${item.weight}%` }} /></div></div>)}</div><p className="exposure-note">{byHolding ? `按持仓市值计算，合计 ${formatMoney(dashboard.holding_market_value)}${dashboard.holding_unrealized_percent === null ? "" : `，浮动盈亏 ${dashboard.holding_unrealized_percent.toFixed(2)}%`}。集中度只描述现状，不构成加减仓建议。` : "这是研究池分布，不是持仓仓位；在持仓账本记录第一笔交易后，这里会改为按持仓市值计算。"}</p></section>;
}

function WatchlistPanel({ dashboard, onOpenCompany, onCreate }: { dashboard: DashboardSummary; onOpenCompany: (id: number) => void; onCreate: () => void }) {
  const items = dashboard.watchlist;
  return <section className="panel watchlist-panel" id="watchlist" aria-labelledby="watchlist-title"><div className="panel-heading"><div><span className="eyebrow">研究池</span><PanelTitle id="watchlist-title">关注公司</PanelTitle></div><button className="page-action" onClick={onCreate}><Plus size={15} />建立公司档案</button></div><div className="watch-table" role="table" aria-label="关注公司"><div className="watch-row watch-head" role="row"><span role="columnheader">公司</span><span role="columnheader">逻辑状态</span><span role="columnheader">最新行情 <Source kind="底座" /></span><span role="columnheader">PE / PB <Source kind="底座" /></span><span role="columnheader">最后复核</span></div>{items.map((item) => <button className="watch-row watch-row--button" role="row" key={item.id} onClick={() => onOpenCompany(item.id)}><div className="watch-company" role="cell"><strong>{item.name}</strong><span>{item.symbol} · {item.industry}</span></div><div role="cell"><StatusBadge status={item.thesis_status} /></div><div className="quote-copy" role="cell">{item.latest_price === null ? <span>未同步</span> : <><strong>¥ {item.latest_price.toFixed(2)}</strong><em className={item.change_percent !== null && item.change_percent < 0 ? "quote-down" : "quote-up"}>{item.change_percent === null ? "—" : `${item.change_percent > 0 ? "+" : ""}${item.change_percent.toFixed(2)}%`}</em></>}</div><span className="roe-copy" role="cell">{item.pe === null ? "待同步" : `PE ${item.pe.toFixed(2)}`}<br />{item.pb === null ? "" : `PB ${item.pb.toFixed(2)}`}</span><time role="cell" dateTime={item.last_reviewed_at ?? undefined}>{formatShortDate(item.last_reviewed_at)}</time></button>)}{items.length === 0 && <div className="empty-state">没有匹配的公司。建立一份公司档案开始研究。</div>}</div></section>;
}

function BriefingCard() {
  const [briefing, setBriefing] = useState<DailyBriefing | null>(null);
  const [job, setJob] = useState<BackgroundJob | null>(null);
  const [error, setError] = useState("");
  const running = job !== null && (job.status === "运行中" || job.status === "排队中");

  function todayInShanghai() {
    return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(new Date());
  }

  const briefingDate = briefing?.as_of?.slice(0, 10) ?? "";
  const briefingIsStale = Boolean(briefingDate && briefingDate < todayInShanghai());
  const briefingDateLabel = briefingIsStale ? `已过期 · ${briefingDate}` : briefingDate ? `数据截至 ${briefingDate}` : "日期未记录";

  async function load() {
    try { setBriefing(await getBriefing()); } catch (caught) { setError(errorMessage(caught)); }
  }
  useEffect(() => { void load(); void getJob("briefing", 0).then(setJob).catch(() => undefined); }, []);

  async function make() {
    setError("");
    try {
      setJob(await generateBriefing());
      const poll = async () => {
        const next = await getJob("briefing", 0);
        setJob(next);
        if (next && (next.status === "运行中" || next.status === "排队中")) window.setTimeout(() => void poll(), 3000);
        else await load();
      };
      window.setTimeout(() => void poll(), 3000);
    } catch (caught) { setError(errorMessage(caught)); }
  }

  const sections: Array<[string, string]> = briefing
    ? [["市场分布", briefing.market], ["持仓与逻辑", briefing.holdings], ["待处理", briefing.pending], ["研究池", briefing.watchlist]]
    : [];
  return <details className="panel briefing-panel">
    <summary className="briefing-summary">
      <span className="briefing-caret" aria-hidden="true">▸</span>
      <div className="briefing-summary-copy">
        <span className="eyebrow">只重述你库里的数据 · 不预测走势</span>
        <div className="briefing-title-row">
          <h2>今日简报</h2>
          {briefing && <span className={`briefing-status${briefingIsStale ? " briefing-status--stale" : ""}`}>{briefingDateLabel}</span>}
        </div>
        {briefing && <p className="briefing-headline">{briefing.headline}</p>}
      </div>
      <button className="page-action" disabled={running} onClick={(event) => { event.preventDefault(); event.stopPropagation(); void make(); }}>
        {running ? "后台生成中…" : briefing && !briefingIsStale ? "重新生成" : "生成今日简报"}
      </button>
    </summary>
    {error && <p className="form-error">{error}</p>}
    {job && running && <p className="restore-message">{job.label}…　任务在服务端跑，你可以切到别的页面，回来还在。</p>}
    {job && job.status === "失败" && <p className="form-error">生成失败：{job.error}</p>}
    {!briefing && !running && <div className="empty-state">还没有简报。点击“生成今日简报”后，它会按报告日期保存；跨日后会明确标记为过期，不会继续冒充今天。</div>}

    {/* 动作先于图表和叙述：生成简报的第一价值，是告诉你今天可以做什么。 */}
    {briefing && briefing.actions.length > 0 && <div className="briefing-body briefing-body--actions">
      <div className="briefing-section briefing-section--actions">
        <h4>今天可以做的</h4><ol>{briefing.actions.map((item) => <li key={item}>{item}</li>)}</ol>
      </div>
    </div>}

    {/* **数字由这里画，模型只说这些数意味着什么。**
        涨跌家数、行业涨跌、持仓浮盈本来就是代码算好喂给模型的，
        它抄一遍既没有新信息，抄错了页面也发现不了。提示词里也禁了复述。 */}
    {briefing && <Suspense fallback={null}>
      <BriefingCharts context={briefing.context} />
    </Suspense>}
    {briefing && <div className="briefing-body">
      {sections.filter(([, text]) => text).map(([label, text]) => <div className="briefing-section" key={label}>
        <h4>{label}</h4><p>{text}</p>
      </div>)}
      {briefing.gaps.length > 0 && <details className="briefing-section briefing-section--gaps">
        <summary>它承认自己不知道的 <span>{briefing.gaps.length} 条</span></summary>
        <ul className="draft-unknown">{briefing.gaps.map((item) => <li key={item}>{item}</li>)}</ul>
      </details>}
      <p className="briefing-foot">{briefingDate || "日期未记录"} · 模型 {briefing.model || "未记录"}{jobCostText(job) ? ` · ${jobCostText(job)}` : ""}</p>
    </div>}
  </details>;
}

type DashNav = "reviews" | "review" | "data" | "heatmap" | "portfolio" | "companies";

/** 还没回答的假设漂移。
 *
 * **这一块存在的全部理由，是它会撞到你脸上。** 同样的内容在公司页的估值页签里
 * 也有一份，但那里要你自己想起来去看——而这个机制专门用来对付"想不起来"。
 * 一个你会绕开的诚实机制，等于没有。
 *
 * 只放 ask 与 unexplained 两档（后端已经筛过）：**首页每多一条，
 * 每一条的分量就少一分**。没有就整块不出现。
 */

function DriftQuestions({ rows, onOpenCompany }: {
  rows: DashboardSummary["drift_questions"]; onOpenCompany: (id: number) => void;
}) {
  if (!rows || rows.length === 0) return null;
  return (
    <section className="panel drift-panel">
      <div className="panel-heading"><div>
        <span className="eyebrow">你说过的话</span>
        <PanelTitle hint="你改过估值假设，而这几次改动说不清依据。调高假设可能完全正确——这里只摆事实，答案由你给。">{rows.length} 个还没回答的问题</PanelTitle>
      </div></div>
      {rows.map((row) => (
        <article className={`drift-q drift-q--${row.level}`} key={`${row.company_id}-${row.at}`}>
          <div className="drift-q-head">
            <button className="text-button" onClick={() => onOpenCompany(row.company_id)}>
              {row.company_name} · {row.symbol}
            </button>
            <span>{row.at?.slice(0, 10)}</span>
          </div>
          <strong>{row.headline}</strong>
          {row.question.split("\n\n").map((para, index) => (
            <p key={index}>{para.split("**").map((part, i) =>
              i % 2 === 1 ? <b key={i}>{part}</b> : <span key={i}>{part}</span>)}</p>
          ))}
        </article>
      ))}
    </section>
  );
}

/**
 * 到期还没核对的管理层承诺。
 *
 * 承诺台账那个面板的说明写着「到期顶到你面前」，而在这块出现之前，
 * 兑现方式是：你自己走进那家公司的档案页、翻到简报页签、往下拉。
 * 后端 `due_promises()` 的注释也写着"给今日概览用"——它被 import 过，
 * 但**从来没有被调用过**。跟认错条件那次一样：算法是对的，缺的是出口。
 *
 * 跟假设漂移并排放，因为它们是同一件事的两半：一边是**你**说过的话，
 * 一边是**公司**说过的话，到期都该有人拿事实去对。
 */
function PromisesDue({ rows, onOpenCompany }: {
  rows: DashboardSummary["promises_due"]; onOpenCompany: (id: number) => void;
}) {
  if (!rows || rows.length === 0) return null;
  return (
    <section className="panel drift-panel">
      <div className="panel-heading"><div>
        <span className="eyebrow">公司说过的话</span>
        <PanelTitle hint="到期日过了两周还没人核对的承诺。两周是给定期报告留的披露时间。这里只提醒，兑没兑现由你判断。">
          {rows.length} 条承诺到期了
        </PanelTitle>
      </div></div>
      {rows.map((row) => (
        <article className="drift-q drift-q--ask" key={row.id}>
          <div className="drift-q-head">
            <button className="text-button" onClick={() => onOpenCompany(row.company_id)}>
              {row.company_name} · {row.symbol}
            </button>
            <span>{row.category} · 到期 {row.due_date}</span>
          </div>
          <strong>{row.subject}</strong>
          <p>{row.statement}</p>
          {row.source_url && <p><a href={row.source_url} target="_blank" rel="noreferrer">打开当时那份公告</a></p>}
        </article>
      ))}
    </section>
  );
}

function DashboardPage({ dashboard, onOpenCompany, onCreate, onStartJudgment, onRefreshMarket, refreshing, marketError, onNavigate }: { dashboard: DashboardSummary; onOpenCompany: (id: number) => void; onCreate: () => void; onStartJudgment: () => void; onRefreshMarket: () => void; refreshing: boolean; marketError: string; onNavigate: (page: DashNav) => void }) {
  // 决策看板在这一层取一次，一页纸和下面的看板共用。
  // 各取一次的话，同一个数字有可能在同一屏上出现两个值——中间用户点了一下"检查反证"。
  const [board, setBoard] = useState<DecisionBoard | null>(null);
  const [boardError, setBoardError] = useState("");
  const loadBoard = useCallback(() => {
    getDecisionBoard().then(setBoard).catch((caught) => setBoardError(errorMessage(caught)));
  }, []);
  useEffect(loadBoard, [loadBoard]);

  // 次序与后端 _ACTION_WEIGHT 一致（命中 > 反证 > 复核 > 公告 > 补全 > 体检）。
  // **不在这里另定一套**：两处各排一次迟早会不一致，而不一致的那次没人会发现。
  //
  // 这句话在 2026-08-16 之前是半句真的：这里的**计数**早就把「命中」算进来了，
  // 而后端的**排序**表里压根没有「命中」这一项，`.get(kind, 9)` 把它兜到了
  // 跟「今天不用管」同一档 —— 同一个概念，两处各写了一份名单，
  // 改了一处忘了另一处。后端那边现在有守卫盯着（test_decision_board_order.py）。
  const byKind = (kind: string) => board?.rows.filter((row) => row.action_kind === kind).length ?? 0;
  const buckets: TodoBucket[] = [
    // **「命中」必须一起数。**
    //
    // 后端把两种情况分成了两个 action_kind：「命中」是公告真的踩到了你写的
    // 认错条件（最急的一件），「反证」是归档的反证证据还没让你改状态。
    // 这里原来只数「反证」——于是**最该报警的那一种，首页这个红点根本不认**，
    // 而文案写的正是"有事实踩到了你写下的反证条件"，说的就是「命中」。
    { key: "counter", label: "反证出现", count: byKind("命中") + byKind("反证"), tone: "critical",
      hint: "有事实踩到了你写下的反证条件", go: () => onNavigate("reviews") },
    { key: "review", label: "到期复核", count: byKind("复核"), tone: "serious",
      hint: "到了当初约定的复核日", go: () => onNavigate("reviews") },
    { key: "events", label: "公告待核", count: dashboard.inbox_pending + dashboard.unread_events, tone: "warning",
      hint: "收件箱里还没读过的实质公告", go: () => onNavigate("review") },
  ];

  return <>
    <section className="page-intro page-intro--cockpit">
      <div>
        <span className="section-kicker">MARKET COCKPIT · {formatDateTime(dashboard.as_of)}</span>
        <h1>A 股研究驾驶舱</h1>
        <p>先看市场，再看自己的公司。</p>
      </div>
      <div className="intro-actions">
        <button className="page-action" onClick={onRefreshMarket} disabled={refreshing}>
          {refreshing ? "正在同步…" : "同步实时行情"}</button>
        <div className="local-stamp"><span>STOCKSDK</span><strong>本地快照</strong></div>
      </div>
    </section>
    {/* 同步失败要落在按钮底下 —— 那是人刚点过的地方。 */}
    {marketError && <p className="form-error">{marketError}</p>}
    {boardError && <p className="form-error">{boardError}</p>}

    {/* 图表包是按需取的，取的过程里先占住位子，别让下面的内容跳上来 */}
    <Suspense fallback={<div className="empty-state page-loading">正在打开今日概览…</div>}>
    <MarketCockpit
      dashboard={dashboard}
      actions={buckets.map((bucket) => ({ label: bucket.label, count: bucket.count, tone: bucket.tone, onClick: bucket.go }))}
      onOpenCompany={onOpenCompany}
      onOpenMarket={() => onNavigate("heatmap")}
      onOpenCompanies={() => onNavigate("companies")}
      onCreateCompany={onCreate}
    />
    </Suspense>

    {/* 研究工作流保留，但不再占据新用户进入后的第一视觉层。 */}
    {/* hint 里带上「还有多少条没比对过」——**这一条必须在折叠状态下也看得见**。
        比对的入口就在这个分区里面，而分区默认是收起来的：折叠时不渲染 children，
        于是那个按钮连 DOM 都没有。用户不会去展开一个他不知道里面有什么的分区。 */}
    <Fold label="我的判断与复核"
          hint={[
            "判断 · 证据 · 简报 · 待办",
            dashboard.counter_uncompared > 0
              ? `${dashboard.counter_uncompared} 条公告还没比对过认错条件` : "",
            // 没写认错条件的那几条**不在网里**，而这件事在别处一个字都不会说
            dashboard.theses_without_counter > 0
              ? `${dashboard.theses_without_counter} 条判断还差认错条件` : "",
            // 假设漂移同样只在这个折叠区里出现一次，没有第二个入口。
            // 而它的设计说明写着"藏在公司页的一个页签里它就废了" —— 藏在折叠区里也一样。
            (dashboard.drift_questions ?? []).length > 0
              ? `${(dashboard.drift_questions ?? []).length} 个假设漂移还没回答` : "",
            // 到期承诺同理：以前它只在公司档案页的一个页签里，
            // 而「到期了」这件事本来就该来找你，不该等你想起来去翻。
            (dashboard.promises_due ?? []).length > 0
              ? `${(dashboard.promises_due ?? []).length} 条承诺到期没核对` : "",
          ].filter(Boolean).join(" · ")}>
      <Headline theses={dashboard.theses} companyCount={dashboard.watchlist.length}
                onOpenCompany={onOpenCompany} onWrite={onStartJudgment} />
      <TodayCard dashboard={dashboard} buckets={buckets}
                 onGoHoldings={() => onNavigate("portfolio")}
                 onGoData={() => onNavigate("data")} />
      <DriftQuestions rows={dashboard.drift_questions ?? []} onOpenCompany={onOpenCompany} />
      <PromisesDue rows={dashboard.promises_due ?? []} onOpenCompany={onOpenCompany} />
      <BriefingCard />
      <DecisionBoardPanel board={board} error={boardError} onReload={loadBoard}
                          onOpenCompany={onOpenCompany} uncompared={dashboard.counter_uncompared} />
      <div className="primary-grid">
        <div className="thesis-ledger-stack">
          <ThesisBar dashboard={dashboard} onGo={() => onNavigate("reviews")} />
          <ThesisLedger dashboard={dashboard} onOpenCompany={onOpenCompany} />
        </div>
        <EventsPanel dashboard={dashboard} onOpenCompany={onOpenCompany} />
      </div>
    </Fold>

    <Fold label="我的研究池" hint="行业分布 · 关注公司列表">
      <ExposurePanel dashboard={dashboard} />
      <WatchlistPanel dashboard={dashboard} onOpenCompany={onOpenCompany} onCreate={onCreate} />
    </Fold>
  </>;
}

/**
 * 新建档案：**用名字就能建，不必先去别处查代码。**
 *
 * 原来这一栏只认六位代码。想研究哪家公司的时候，脑子里有的是名字不是代码——
 * 于是第一步不是研究，是去别的网站查一个数字回来。那是把数据库主键当成人的入口。
 *
 * 但**校验这一关一步都不能省**：名字只用来找到代码，档案里的名称与交易所
 * 仍然只取自 StockSDK 校验回来的那份数据。底座里的名字可能过时（改名、退市），
 * 而档案一旦建错，后面所有行情、财务、公告都会挂在错的票上。
 */
function CompanyForm({ onSaved, onCancel }: { onSaved: (company: CompanyDetail) => void; onCancel: () => void }) {
  const [text, setText] = useState("");
  const [symbol, setSymbol] = useState("");
  const [matches, setMatches] = useState<UniverseMatch[]>([]);
  const [searching, setSearching] = useState(false);
  const [preview, setPreview] = useState<QuotePreview | null>(null);
  const [resolving, setResolving] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const isCode = /^\d{6}$/.test(text.trim());

  async function resolveSymbol(code: string) {
    if (!code.trim()) { setError("先输入公司名称或 6 位代码。"); return; }
    setResolving(true);
    setError("");
    try {
      setPreview(await getQuotePreview(code));
      setSymbol(code.trim());
    } catch (caught) {
      setPreview(null);
      setSymbol("");
      setError(errorMessage(caught));
    } finally {
      setResolving(false);
    }
  }

  // 输入的是名字就去底座里找候选；是六位代码就直接校验。**两条路都不花积分。**
  useEffect(() => {
    const needle = text.trim();
    if (!needle || isCode) { setMatches([]); setSearching(false); return; }
    setSearching(true);
    let live = true;
    const timer = window.setTimeout(() => {
      void lookupUniverse(needle, 6)
        .then((rows) => { if (live) setMatches(rows); })
        .catch(() => { if (live) setMatches([]); })
        .finally(() => { if (live) setSearching(false); });
    }, 180);
    return () => { live = false; window.clearTimeout(timer); };
  }, [text, isCode]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!symbol) { setError("先选中一家公司并通过校验，再建档。"); return; }
    setSaving(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const company = await createCompanyFromQuote({
        symbol,
        watch_group: String(form.get("watch_group") ?? "观察池"),
        description: String(form.get("description") ?? ""),
      });
      onSaved(company);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="editor-form" onSubmit={submit}>
      <div className="form-heading">
        <div><span className="eyebrow">新建档案</span><h2>先确认是哪一家公司</h2></div>
        <button type="button" className="text-button" onClick={onCancel}>取消</button>
      </div>
      <p className="form-hint">名称和交易所只取自 StockSDK 校验结果；行业、研究缘起和投资逻辑不会自动编写。</p>
      <div className="form-grid">
        <label>
          公司名称或代码
          <div className="symbol-input-row">
            <input
              name="lookup"
              value={text}
              onChange={(event) => { setText(event.target.value); setPreview(null); setSymbol(""); }}
              onBlur={() => { if (isCode) void resolveSymbol(text); }}
              placeholder="例如 贵州茅台 或 600519"
              autoComplete="off"
              required
            />
            <button className="secondary-action" type="button" disabled={resolving || !isCode}
                    onClick={() => void resolveSymbol(text)}>
              {resolving ? "校验中…" : "校验代码"}
            </button>
          </div>
        </label>
        <label>归属分组<input name="watch_group" defaultValue="观察池" required /></label>
      </div>
      {!isCode && text.trim() && !preview && <div className="symbol-matches">
        {searching && matches.length === 0 && <p className="form-note">正在全市场里找…</p>}
        {!searching && matches.length === 0 && <p className="form-note">没找到叫「{text.trim()}」的公司。换两个字，或者直接输入 6 位代码。</p>}
        {matches.map((row) => <button key={row.symbol} type="button" className="symbol-match"
                                      disabled={resolving} onClick={() => void resolveSymbol(row.symbol)}>
          <span className="symbol-match-name">{row.name}</span>
          <span className="symbol-match-meta">{row.symbol}{row.industry ? ` · ${row.industry}` : ""}{capText(row.total_market_cap) ? ` · ${capText(row.total_market_cap)}` : ""}</span>
          {row.in_archive && <span className="symbol-match-note">已建档</span>}
        </button>)}
      </div>}
      {preview && <div className="quote-preview" aria-live="polite">
        <div><span>已找到真实行情</span><strong>{preview.name} · {preview.symbol}</strong><small>{preview.exchange} · 来源 {preview.source}</small></div>
        <div className="quote-preview-price"><strong>{preview.price === null ? "价格待返回" : `¥ ${preview.price.toFixed(2)}`}</strong><span className={preview.change_percent !== null && preview.change_percent < 0 ? "quote-down" : "quote-up"}>{preview.change_percent === null ? "涨跌待返回" : `${preview.change_percent > 0 ? "+" : ""}${preview.change_percent.toFixed(2)}%`}</span></div>
      </div>}
      <label>
        为什么值得研究（可选）
        <textarea name="description" rows={3} placeholder="记录你已知的业务、行业或研究缘起；投资逻辑将在档案中单独确认。" />
      </label>
      {error && <p className="form-error">{error}</p>}
      <div className="form-actions"><button type="submit" className="page-action" disabled={saving || resolving || !symbol}>{saving ? "正在建立…" : "用真实行情建立档案"}</button></div>
    </form>
  );
}

const POOL_SORTS = [
  { key: "group", label: "按分组" },
  { key: "change", label: "按当日涨跌" },
  { key: "name", label: "按名称" },
  { key: "added", label: "按建档时间" },
] as const;

type PoolSort = (typeof POOL_SORTS)[number]["key"];

function sortCompanies(companies: CompanyRecord[], sort: PoolSort): CompanyRecord[] {
  const ordered = [...companies];
  if (sort === "change") {
    ordered.sort((first, second) => (second.change_percent ?? -Infinity) - (first.change_percent ?? -Infinity));
  } else if (sort === "name") {
    ordered.sort((first, second) => first.name.localeCompare(second.name, "zh-CN"));
  } else if (sort === "added") {
    ordered.sort((first, second) => second.created_at.localeCompare(first.created_at));
  } else {
    ordered.sort((first, second) => first.watch_group.localeCompare(second.watch_group, "zh-CN") || first.name.localeCompare(second.name, "zh-CN"));
  }
  return ordered;
}

function WatchlistImportForm({ groups, onDone, onCancel }: { groups: WatchGroupSummary[]; onDone: () => Promise<void>; onCancel: () => void }) {
  const [mode, setMode] = useState<"codes" | "file">("codes");
  const [rows, setRows] = useState<WatchlistImportRow[] | null>(null);
  const [fileName, setFileName] = useState("");
  const [restoreExisting, setRestoreExisting] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<WatchlistImportResult | null>(null);

  async function readFile(file: File) {
    setError(""); setResult(null);
    try {
      const parsed = JSON.parse(await file.text()) as unknown;
      const list = Array.isArray(parsed) ? parsed : (parsed as { records?: { companies?: unknown[] } })?.records?.companies;
      if (!Array.isArray(list)) throw new Error("文件里没有找到公司列表");
      const mapped = list
        .map((item) => item as Record<string, unknown>)
        .filter((item) => typeof item.symbol === "string")
        .map((item) => ({
          symbol: String(item.symbol),
          watch_group: typeof item.watch_group === "string" ? item.watch_group : null,
          description: typeof item.description === "string" ? item.description : null,
          industry: typeof item.industry === "string" ? item.industry : null,
          is_watched: typeof item.is_watched === "boolean" ? item.is_watched : null,
        }));
      if (mapped.length === 0) throw new Error("文件里没有可用的证券代码");
      setRows(mapped);
      setFileName(`${file.name} · ${mapped.length} 家公司`);
    } catch (caught) {
      setRows(null); setFileName("");
      setError(caught instanceof Error ? `读取失败：${caught.message}` : "读取失败");
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true); setError("");
    try {
      if (mode === "file") {
        if (!rows) { setError("请先选择导出的 JSON 文件。"); return; }
        setResult(await importWatchlist({ rows, restore_existing: restoreExisting }));
      } else {
        const symbols = String(form.get("symbols") ?? "").split(/[\s,，;；\n]+/).map((item) => item.trim()).filter(Boolean);
        if (symbols.length === 0) { setError("请至少填一个证券代码。"); return; }
        setResult(await importWatchlist({ symbols, watch_group: String(form.get("watch_group") ?? "观察池") }));
      }
      await onDone();
    } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); }
  }

  return <form className="inline-form" onSubmit={submit}>
    <div className="chart-range-group" role="group" aria-label="选择导入方式">
      <button type="button" className={`chart-range${mode === "codes" ? " chart-range--on" : ""}`} onClick={() => setMode("codes")}>粘贴代码</button>
      <button type="button" className={`chart-range${mode === "file" ? " chart-range--on" : ""}`} onClick={() => setMode("file")}>回灌导出文件</button>
    </div>
    {mode === "codes" ? <>
      <label>证券代码（换行、空格或逗号分隔，一次最多 200 个）
        <textarea name="symbols" rows={3} placeholder="600519 000333 300750" />
      </label>
      <div className="form-grid compact-grid">
        <label>放入分组<input name="watch_group" defaultValue="观察池" list="watch-groups" /></label>
      </div>
      <datalist id="watch-groups">{groups.map((group) => <option value={group.name} key={group.name} />)}</datalist>
    </> : <>
      <label>选择“导出研究池”下载到的 JSON 文件
        <input type="file" accept="application/json,.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) void readFile(file); }} />
      </label>
      {fileName && <p className="form-note">已读取：{fileName}</p>}
      <label className="sync-toggle">
        <input type="checkbox" checked={restoreExisting} onChange={(event) => setRestoreExisting(event.target.checked)} />
        已存在的公司也按文件恢复分组、研究缘起与是否关注
      </label>
    </>}
    {error && <p className="form-error">{error}</p>}
    {result && <div className="import-result">
      <p>新建 {result.created} 家 · 恢复 {result.updated} 家 · 跳过 {result.skipped} 家 · 失败 {result.failed} 家</p>
      <ul>{result.results.map((item) => <li key={item.symbol}><b>{item.symbol}</b><span className={item.status === "失败" ? "quote-up" : ""}>{item.status}</span><em>{item.detail}</em></li>)}</ul>
    </div>}
    <div className="form-actions"><button className="page-action" type="submit" disabled={saving}>{saving ? "正在校验…" : mode === "file" ? "回灌研究池" : "校验并加入"}</button><button className="text-button" type="button" onClick={onCancel}>关闭</button></div>
    <p className="form-note">每个代码都要 StockSDK 返回有效行情才会建档。回灌只会写回分组、研究缘起、行业与是否关注；已有的逻辑、证据、事件和交易记录不会被触碰。</p>
  </form>;
}


/** 空态里那个「先看三份示例」。**不自动种**——自动种是替使用者做决定，
 *  而这三份是示例不是他的研究。载入要几秒（顺带补报表科目，行业指标要用），
 *  所以按钮要说出来，否则又是一次"点了没反应"。 */
function SampleLoader({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  async function run() {
    setBusy(true); setError(""); setNote("");
    try {
      const result = await loadSamples();
      setNote(result.note);
      onDone();
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  return <div className="sample-loader">
    <button className="page-action" type="button" disabled={busy} onClick={() => void run()}>
      {busy ? "正在载入…约几秒" : "载入三份示例档案"}
    </button>
    {note && <p className="restore-message">{note}</p>}
    {error && <p className="form-error">{error}</p>}
  </div>;
}

function CompaniesPage({ showCreate, onOpenCompany, onCreated, onCloseCreate }: { showCreate: boolean; onOpenCompany: (id: number) => void; onCreated: (company: CompanyDetail) => void; onCloseCreate: () => void }) {
  const [companies, setCompanies] = useState<CompanyRecord[]>([]);
  // **这一栏自己的筛选。** 原来它借顶栏那个框——可那个框在别的十几页上什么都不做，
  // 现在改成了全站跳转，筛列表这件事就该回到列表自己身上。
  const [filter, setFilter] = useState("");
  const [groups, setGroups] = useState<WatchGroupSummary[]>([]);
  const [activeGroup, setActiveGroup] = useState("全部");
  const [sort, setSort] = useState<PoolSort>("group");
  const [showArchived, setShowArchived] = useState(false);
  const [importing, setImporting] = useState(false);
  const [busy, setBusy] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function dropSamples() {
    if (!(await confirmAction({
      title: "删掉全部示例档案？",
      detail: "连同它们的判断、证据与承诺一起删。你自己建的公司不受影响。",
      confirmText: "删掉示例", danger: true,
    }))) return;
    setBusy(-1);
    try { await removeSamples(); await reload(); }
    catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(0); }   // busy 是公司 id，空闲态是 0 不是 null
  }

  async function reload() {
    const [nextCompanies, nextGroups] = await Promise.all([getCompanies(filter), getWatchGroups()]);
    setCompanies(nextCompanies);
    setGroups(nextGroups);
  }
  useEffect(() => {
    let current = true;
    setLoading(true);
    reload().then(() => current && setError("")).catch((caught) => current && setError(errorMessage(caught))).finally(() => current && setLoading(false));
    return () => { current = false; };
  }, [filter, showCreate]);

  async function moveGroup(company: CompanyRecord, group: string) {
    setBusy(company.id);
    try { await updateCompany(company.id, { watch_group: group }); await reload(); }
    catch (caught) { setError(errorMessage(caught)); } finally { setBusy(0); }
  }
  async function toggleWatched(company: CompanyRecord) {
    setBusy(company.id);
    try { await updateCompany(company.id, { is_watched: !company.is_watched }); await reload(); }
    catch (caught) { setError(errorMessage(caught)); } finally { setBusy(0); }
  }

  const visible = sortCompanies(
    companies.filter((company) => company.is_watched !== showArchived && (activeGroup === "全部" || company.watch_group === activeGroup)),
    sort,
  );
  const archivedCount = companies.filter((company) => !company.is_watched).length;

  return <>
    <section className="page-intro archive-intro">
      <div><span className="section-kicker">RESEARCH ARCHIVE</span><h1>公司档案</h1></div>
      <div className="intro-actions">
        <a className="text-button" href={apiUrl("/api/v1/companies/export")}>导出研究池</a>
        <button className="text-button" onClick={() => setImporting((value) => !value)}>批量导入</button>
        <button className="page-action" onClick={() => onCloseCreate()}><Plus size={15} />新建公司</button>
      </div>
    </section>
    {showCreate && <CompanyForm onSaved={onCreated} onCancel={onCloseCreate} />}
    {importing && <section className="panel"><WatchlistImportForm groups={groups} onDone={reload} onCancel={() => setImporting(false)} /></section>}
    {error && <p className="form-error">{error}</p>}
    <div className="pool-toolbar">
      <div className="chart-range-group" role="group" aria-label="按分组筛选">
        <button className={`chart-range${activeGroup === "全部" ? " chart-range--on" : ""}`} onClick={() => setActiveGroup("全部")}>全部</button>
        {groups.map((group) => <button key={group.name} className={`chart-range${activeGroup === group.name ? " chart-range--on" : ""}`} onClick={() => setActiveGroup(group.name)}>{group.name}<em>{showArchived ? group.archived : group.watched}</em></button>)}
      </div>
      <div className="pool-toolbar-right">
        <label className="pool-filter"><Search size={14} aria-hidden="true" />
          <input type="search" value={filter} onChange={(event) => setFilter(event.target.value)}
                 placeholder="筛选这些档案" aria-label="按名称、代码或行业筛选档案" />
        </label>
        <label className="sync-interval">排序<select value={sort} onChange={(event) => setSort(event.target.value as PoolSort)}>{POOL_SORTS.map((item) => <option value={item.key} key={item.key}>{item.label}</option>)}</select></label>
        <label className="sync-toggle"><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />只看已移出（{archivedCount}）</label>
      </div>
    </div>
    <section className="company-grid" aria-label="公司档案列表">
      {loading && <div className="empty-state">正在打开本地研究库…</div>}
      {!loading && !error && visible.map((company) => <article className="company-card" key={company.id}>
        <button className="company-card-open" onClick={() => onOpenCompany(company.id)}>
          <div className="company-card-top"><span>{company.watch_group}</span><ChevronRight size={16} /></div>
          <h2>{company.name}</h2>
          <p>{company.symbol} · {company.industry}</p>
          <div className="company-card-body">{company.description || "尚未补充研究缘起。"}</div>
          <div className="company-card-foot">
            <span>{company.latest_price === null ? "行情未同步" : `¥ ${company.latest_price.toFixed(2)} · ${company.change_percent && company.change_percent > 0 ? "+" : ""}${company.change_percent?.toFixed(2) ?? "—"}%`}</span>
            <span>{company.market_source ?? "StockSDK"}</span>
          </div>
        </button>
        <div className="company-card-actions">
          {/* **看不出是示例的示例，会被当成他自己的研究**——
              而他会以为自己已经写过三条判断了。 */}
          {company.is_sample && <span className="sample-chip">示例</span>}
          <label>分组
            <select value={company.watch_group} disabled={busy === company.id} onChange={(event) => void moveGroup(company, event.target.value)} aria-label={`${company.name} 所在分组`}>
              {[...new Set([company.watch_group, ...groups.map((group) => group.name), "观察池", "重点观察", "持仓池"])].map((name) => <option value={name} key={name}>{name}</option>)}
            </select>
          </label>
          <button className="text-button" disabled={busy === company.id} onClick={() => void toggleWatched(company)}>{company.is_watched ? "移出研究池" : "放回研究池"}</button>
        </div>
      </article>)}
      {/* **不能删的示例等于强塞。** 有示例时这个入口必须在手边，
          不能藏进设置页——他想清掉的那一刻就该找得到。 */}
      {!loading && !error && visible.some((c) => c.is_sample) && <p className="restore-message">
        这里面有 <strong>{visible.filter((c) => c.is_sample).length} 份示例档案</strong>（带「示例」记号）。
        <button className="text-button" type="button" disabled={busy === -1}
          onClick={() => void dropSamples()}>{busy === -1 ? "正在删…" : "删掉全部示例"}</button>
      </p>}
      {/* **筛没筛出来，跟一份档案都没有，是两回事。** 后者该请他看示例，
          前者只该告诉他这次没匹配上——把"还没有档案"摆给一个有 40 份档案的人看，
          他会以为数据丢了。 */}
      {!loading && !error && visible.length === 0 && filter.trim()
        ? <div className="empty-state">
            <p>「{filter.trim()}」在{showArchived ? "已移出的" : ""}档案里没有匹配。</p>
            <p>顶栏那个搜索框能搜全市场，还没建档的公司也找得到。</p>
          </div>
        : null}
      {!loading && !error && visible.length === 0 && !filter.trim() && (showArchived
        ? <div className="empty-state">没有已移出的档案。</div>
        : <div className="empty-state">
            {/* **空态是这个产品最该解释自己的地方，也是唯一该解释的地方。**
                一个空的研究台没法用文案说明白自己是干什么的——给三份带真数据的
                示例，比再写三段话有用。不自动种：那是替使用者做决定。 */}
            <p><strong>还没有档案。</strong>点「新建公司」开始，或者先看三份示例。</p>
            <p>示例是<strong>茅台、寒武纪、格力</strong>——各带一条写好的判断、认错条件与证据，
            数据都是真的（茅台的合同负债、寒武纪 88.66% 的客户集中度、格力的回购承诺）。
            带「示例」记号，随时一键删掉。</p>
            <SampleLoader onDone={() => void reload()} />
          </div>)}
    </section>
    <p className="data-status-note">移出研究池只是不再出现在关注列表与总览；档案、逻辑、证据、事件和交易记录都会保留，可以随时放回。</p>
  </>;
}

// 从方法库带去公司档案的草稿。只在内存里传递，不落库——用户没确认前不该产生记录。

/** 一次 AI 操作花了多少积分。
 *
 * 按下按钮之前算不准（token 数事先不知道），所以事后必须如实说。
 * `metered=false` 是「这次根本没计费」——本地单机、没登录、或闸口不可达。
 * 那种情况下显示「0 积分」会被读成免费，所以分开写。 */
function costText(billing?: Billing | null): string {
  if (!billing) return "";
  if (!billing.metered) return "本次未计费（未接入虾米伙伴积分或未登录）";
  const calls = billing.calls > 1 ? `${billing.calls} 次调用、` : "";
  return `本次消耗 ${billing.credits} 积分（${calls}${billing.tokens.toLocaleString()} tokens）`;
}

function BillingNote({ billing }: { billing?: Billing | null }) {
  const text = costText(billing);
  if (!text) return null;
  return <p className="billing-note">{text}</p>;
}

/** 后台任务跑完后的花费。任务不在请求里，账记在任务行上。 */
/**
 * 任务没跑完时的那一行。**中断要给出下一步动作，不能只报状态。**
 *
 * 「已中断」是服务重启把任务打断了，跟这次活儿本身没关系；而页面原来跟
 * 「失败」写成同一句红字，读起来像是"这事儿干不成"。用户于是要么重新找一遍
 * 入口，要么以为积分白花了——两个念头都是我们没说清造成的。
 *
 * 重跑是安全的：后端按 (任务种类, 目标) 去重，重启后旧任务已不在运行中，
 * 新提交会正常开始；上一次冻结的额度由积分服务自动退回。
 */
function JobTrouble({ job, onRetry, retrying }: {
  job: BackgroundJob | null;
  /** 有重跑入口就给按钮；纯展示的地方可以不传。 */
  onRetry?: () => void;
  retrying?: boolean;
}) {
  if (!job || (job.status !== "失败" && job.status !== "已中断")) return null;
  // 中断那句后端已经写全了（重启了、能重跑、不会重复计费），前端再加个前缀
  // 就变成「服务重启把它打断了：服务重启，任务未完成…」——同一件事说两遍。
  // 失败那句是异常文本，需要前缀才知道这是什么。
  const interrupted = job.status === "已中断";
  return <p className="form-error job-trouble">
    <span>{interrupted ? "" : "这次没跑成："}{job.error || job.note || job.status}</span>
    {onRetry && <button className="text-button" type="button" disabled={retrying} onClick={onRetry}>
      {retrying ? "正在重跑…" : "重新跑一次"}
    </button>}
  </p>;
}

function jobCostText(job: BackgroundJob | null): string {
  if (!job || (job.status !== "已完成" && job.status !== "失败")) return "";
  if (!job.metered) return job.tokens > 0 ? `本次未计费（${job.tokens.toLocaleString()} tokens）` : "";
  return `本次消耗 ${job.credits} 积分（${job.tokens.toLocaleString()} tokens）`;
}

let pendingThesisDraft: { claim: string; counter: string; trigger: string; method: string } | null = null;
function takeThesisDraft() { const draft = pendingThesisDraft; pendingThesisDraft = null; return draft; }
function hasThesisDraft() { return pendingThesisDraft !== null; }

function MethodDetailPanel({ methodKey, companies, onDraft }: { methodKey: string; companies: CompanyRecord[]; onDraft: (companyId: number) => void }) {
  const [method, setMethod] = useState<ThesisMethod | null>(null);
  const [error, setError] = useState("");
  const [target, setTarget] = useState("");
  useEffect(() => {
    let current = true;
    setMethod(null);
    getMethod(methodKey)
      .then((next) => { if (current) { setMethod(next); setError(""); } })
      .catch((caught) => { if (current) setError(errorMessage(caught)); });
    return () => { current = false; };
  }, [methodKey]);

  if (error) return <p className="form-error">{error}</p>;
  if (!method) return <div className="empty-state">正在打开方法…</div>;
  const draftable = method.claim_template.startsWith("（") === false;

  return <div className="method-detail">
    <p className="method-origin"><strong>出处</strong>{method.origin}</p>
    <div className="method-columns">
      <div>
        <h4>怎么做</h4>
        <ol className="method-steps">{method.steps.map((step) => <li key={step}>{step}</li>)}</ol>
      </div>
      <div>
        <h4>照着填</h4>
        <dl className="method-templates">
          <dt>判断</dt><dd>{method.claim_template}</dd>
          <dt>反证条件</dt><dd>{method.counter_template}</dd>
          <dt>复核触发</dt><dd>{method.trigger_template}</dd>
        </dl>
      </div>
    </div>
    <div className="method-columns">
      {method.fits.length > 0 && <div><h4>什么时候用它</h4><ul className="method-list">{method.fits.map((item) => <li key={item}>{item}</li>)}</ul></div>}
      {method.not_fits.length > 0 && <div><h4>什么时候别用</h4><ul className="method-list method-list--warn">{method.not_fits.map((item) => <li key={item}>{item}</li>)}</ul></div>}
    </div>
    {method.caution && <p className="method-caution">{method.caution}</p>}
    {draftable && <div className="method-draft">
      <label className="sync-interval">套用到
        <select value={target} onChange={(event) => setTarget(event.target.value)}>
          <option value="">选一家已建档的公司</option>
          {companies.map((company) => <option value={company.id} key={company.id}>{company.name} · {company.symbol}</option>)}
        </select>
      </label>
      <button className="page-action" type="button" disabled={!target} onClick={() => {
        pendingThesisDraft = { claim: method.claim_template, counter: method.counter_template, trigger: method.trigger_template, method: method.name };
        onDraft(Number(target));
      }}>带着模板去写</button>
      <span className="method-draft-note">模板会填进新建逻辑的表单，方括号里的内容需要你替换成具体事实后才保存。</span>
    </div>}
    {!draftable && <p className="method-draft-note">这个方法不产生买入理由，它是下单前的自检；结论写进你已有逻辑的反证条件里。</p>}
  </div>;
}

// 显示偏好只存在浏览器里：它不影响任何研究结论，没必要占数据库，也不该被备份带走。
const PREF_KEY = "xiami-stock-prefs";
/**
 * 四套预设。**深浅这一档不在这里，在账户中心。**
 *
 * 2026-08-16：外观（随系统 / 白天 / 黑夜）是**平台级**设置，真源是
 * `localStorage["xm-theme"]`，主站、虾米会计、虾米看 AI 都照它走。本仓原来
 * 自己也有一套（paper/contrast/warm/night/auto），两套都往 `<html data-theme>`
 * 上写，词汇表还不一样 —— 实测四种场景全是坏的：
 *
 *   系统深色 · 没设过    页面浅、平台页眉深   一页两个外观
 *   系统浅色 · 选了黑夜  页面浅、页眉也白     账户中心那个开关对本站完全无效
 *   系统深色 · 选了白天  页面浅、页眉却是深的
 *
 * 所以拆成两条轴，各管各的，谁也不占谁的属性：
 *
 *   data-theme  light | dark | （不写＝随系统）   ← 平台开关，唯一真源
 *   data-look   paper | contrast | warm          ← 本仓自己的浅色变体
 *
 * 「夜间」和「跟随系统」从这张表里去掉了：它们现在是账户中心那三个图标的事，
 * 在两个地方各放一个同名开关，正是这次要修的那个毛病。
 */
const THEMES = [
  { key: "paper", name: "纸感", hint: "默认。米白纸面配靛蓝，长时间阅读的基线。" },
  { key: "contrast", name: "高对比", hint: "纯白纸面、更深的字，关掉方格底纹。屏幕反光或视力疲劳时用。" },
  { key: "warm", name: "暖光护眼", hint: "偏黄的纸面，降低蓝光比例。夜里或长时间看盘用。" },
];
const SCALES = [
  { key: "1", name: "标准" },
  { key: "1.12", name: "大" },
  { key: "1.25", name: "特大" },
];

interface Prefs { theme: string; scale: string; grid: boolean; v?: number; }
// 研究台固定采用精简首屏：只展示结论、数字和动作；单个面板仍可点问号或边界说明按需核查。
const DEFAULT_PREFS: Prefs = { theme: "paper", scale: "1", grid: true, v: 4 };

/** 存过的偏好版本。旧版本里的 depth 字段会被自然忽略，不再恢复已移除的模式开关。 */
const PREF_VERSION = 4;   // v4：深浅那一档交给平台开关，本地只留浅色变体

function readPrefs(): Prefs {
  try {
    const saved = JSON.parse(window.localStorage.getItem(PREF_KEY) ?? "{}");
    // 只读取仍然存在的偏好字段，避免旧版本的 depth 开关继续被写回本地存储。
    return {
      theme: typeof saved.theme === "string" ? saved.theme : DEFAULT_PREFS.theme,
      scale: typeof saved.scale === "string" ? saved.scale : DEFAULT_PREFS.scale,
      grid: typeof saved.grid === "boolean" ? saved.grid : DEFAULT_PREFS.grid,
      v: PREF_VERSION,
    };
  }
  catch { return { ...DEFAULT_PREFS, v: PREF_VERSION }; }
}

/** 平台外观偏好的键名。真源在 tools-frontend/lib/theme.ts，本仓只读不定义。 */
const PLATFORM_THEME_KEY = "xm-theme";

/** 现在该是深色还是浅色。没手动选过就问系统。 */
export function resolveAppearance(): "light" | "dark" {
  try {
    const saved = window.localStorage.getItem(PLATFORM_THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch { /* 隐私模式下读不到，当作随系统 */ }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** 把深浅那一档写到 <html data-theme> 上。index.html 里的引导脚本做的是同一件事。 */
function applyAppearance() {
  document.documentElement.dataset.theme = resolveAppearance();
}

// 选了「随系统」之后，系统在半夜切过去也要跟着切——只在打开页面那一刻算一次，
// 等于没有跟随。监听器挂在模块加载时，一次就够。
//
// **这也是引导脚本敢在「随系统」时写死一个值的前提**（见 index.html 里那段说明）：
// 有它在，写进去的那个值不是快照，系统一变就重解。
if (typeof window !== "undefined" && window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyAppearance);
  // 账户中心在另一个页面改了外观，回到本页要跟上；同源共用 localStorage，
  // storage 事件正好是为这种跨标签页同步准备的。
  window.addEventListener("storage", (event) => {
    if (event.key === PLATFORM_THEME_KEY) applyAppearance();
  });
}

export function applyPrefs(prefs: Prefs) {
  const root = document.documentElement;
  // **两条轴，各写各的属性。** data-theme 只说深浅（平台开关说了算），
  // data-look 只说本仓这几套浅色变体。混用同一个属性正是这次要修的毛病：
  // 平台的 `[data-theme="dark"]` 会永远匹配不到，而它的
  // `:not([data-theme="light"])` 会永远匹配得到 —— 于是页眉和页面各走各的。
  applyAppearance();
  if (prefs.theme && prefs.theme !== "paper") root.dataset.look = prefs.theme;
  else delete root.dataset.look;
  delete root.dataset.depth;
  // 写平台变量而不是本仓的 --font-scale：后者已绑到它。
  // 一处调整，本站与嵌入进来的平台页眉页脚一起缩放，不会出现"正文缩了页眉没缩"。
  root.style.setProperty("--xm-font-scale", prefs.scale);
  // 方格底纹在长时间阅读时是持续的视觉噪声，所以给一个开关而不是硬留着
  root.style.setProperty("--grid-alpha", prefs.grid ? "" : "0");
  if (!prefs.grid) root.style.setProperty("--grid-alpha", "0");
  window.localStorage.setItem(PREF_KEY, JSON.stringify(prefs));
}

function FeedManager() {
  // **订阅源是整台实例的配置**，不是个人偏好：加一条，所有人的资讯证据都会多这个来源。
  // 所以它跟主题、字号不一样，不该出现在每个人的偏好设置里。
  const ownerHere = useIsOwner();
  const [feeds, setFeeds] = useState<NewsFeed[]>([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function reload() {
    try { setFeeds(await getNewsFeeds()); setError(""); } catch (caught) { setError(errorMessage(caught)); }
  }
  useEffect(() => { if (ownerHere === true) void reload(); }, [ownerHere]);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    try { await saveNewsFeed({ name, url }); setName(""); setUrl(""); await reload(); }
    catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  }
  async function act(feed: NewsFeed, kind: "toggle" | "delete") {
    setBusy(true); setError("");
    try {
      if (kind === "toggle") await toggleNewsFeed(feed.id, !feed.enabled);
      else if (await confirmAction({
        title: `删除订阅源「${feed.name}」？`,
        detail: "已经抓下来的资讯会保留。", confirmText: "删除订阅源", danger: true,
      })) await deleteNewsFeed(feed.id);
      await reload();
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  }

  // 不是站主就整块不显示（后端那四个接口也是 require_owner）。
  if (ownerHere !== true) return null;

  return <section className="panel">
    <div className="panel-heading"><div><span className="eyebrow">资讯证据的来源</span><PanelTitle hint="内置的都实测过能取到内容。一个源长期抓不到就等于没有这个源，所以每次抓取的成败都记在这里。">订阅源</PanelTitle></div></div>
    <div className="pref-feeds">
      {feeds.map((feed) => <div className={`pref-feed${feed.enabled ? "" : " pref-feed--off"}`} key={feed.id}>
        <label className="sync-toggle">
          <input type="checkbox" checked={feed.enabled} disabled={busy} onChange={() => void act(feed, "toggle")} />
          <strong>{feed.name}</strong>
        </label>
        <a href={feed.url} target="_blank" rel="noreferrer">{feed.url}</a>
        <span className="pref-feed-state">
          {feed.builtin ? "内置" : "自定义"}
          {feed.last_error ? ` · 上次失败：${feed.last_error.slice(0, 40)}` : feed.last_ok_at ? ` · 上次成功 ${formatDateTime(feed.last_ok_at)} · 累计 ${feed.item_count} 条` : " · 还没抓过"}
        </span>
        {!feed.builtin && <button className="text-button" disabled={busy} onClick={() => void act(feed, "delete")}>删除</button>}
      </div>)}
    </div>
    <form className="inline-form pref-feed-form" onSubmit={add}>
      <div className="form-grid compact-grid">
        <label>名称<input value={name} onChange={(event) => setName(event.target.value)} required placeholder="例如：某行业垂直媒体" /></label>
        <label>RSS 地址<input value={url} onChange={(event) => setUrl(event.target.value)} required placeholder="https://…/rss.xml" /></label>
      </div>
      {error && <p className="form-error">{error}</p>}
      <div className="form-actions">
        <button className="page-action" type="submit" disabled={busy}>{busy ? "正在保存…" : "加一个源"}</button>
      </div>
      <p className="form-note">支持 RSS 2.0 与 Atom。加进来之后到「资讯证据」页点抓取；抓不到会把失败原因写在上面，不会静默跳过。</p>
    </form>
  </section>;
}

function PreferencesPage() {
  const [prefs, setPrefs] = useState<Prefs>(() => readPrefs());
  // 当下是深是浅。深浅归账户中心管，这一页只用它决定要不要说那句话。
  const [dark, setDark] = useState(() => resolveAppearance() === "dark");
  useEffect(() => {
    const sync = () => setDark(resolveAppearance() === "dark");
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    media?.addEventListener("change", sync);
    window.addEventListener("storage", sync);
    return () => { media?.removeEventListener("change", sync); window.removeEventListener("storage", sync); };
  }, []);
  // 备份那一行只给站主。它后面那几个接口都是 require_owner。
  const ownerHere = useIsOwner();
  function update(patch: Partial<Prefs>) {
    const next = { ...prefs, ...patch };
    setPrefs(next);
    applyPrefs(next);
  }
  return <>
    <section className="page-intro archive-intro">
      <div><span className="section-kicker">PREFERENCES</span><h1>偏好设置</h1>
        <p>只影响显示，不影响任何研究结论与数据。设置存在这台浏览器里，不进数据库、也不会被备份带走。</p></div>
      <div className="local-stamp"><span>LOCAL</span><strong>本机生效</strong></div>
    </section>

    <section className="panel">
      <div className="panel-heading"><div><span className="eyebrow">看着累就换一套</span><PanelTitle hint="三套预设只改颜色，不改布局。默认那套已经把字号下限从 8px 抬到 10px、次要文字对比度提到 4.7:1。">浅色下的纸面</PanelTitle></div></div>
      {/* **深色下这三套是不起作用的，必须说出来。**
          深浅那一档归账户中心管（平台级，三个站共用）；这里剩下的是浅色纸面的
          三种变体。在黑夜外观下点它们没有任何反应 —— 而一个点了没反应、
          页面又一个字都不说的开关，比没有这个开关更让人怀疑是不是坏了。 */}
      {dark && <p className="form-note pref-appearance-note">
        现在是<strong>黑夜</strong>外观，下面这三套是<strong>浅色</strong>下的纸面变体，
        在黑夜下不起作用。深浅在<strong>账户中心 › 设置 › 外观</strong>里切（三个站共用一个设置）。
      </p>}
      <div className="pref-themes">
        {THEMES.map((theme) => <button
          key={theme.key}
          className={`pref-theme pref-theme--${theme.key}${prefs.theme === theme.key ? " pref-theme--on" : ""}`}
          onClick={() => update({ theme: theme.key })}
        >
          <span className="pref-swatch"><i /><i /><i /></span>
          <strong>{theme.name}</strong>
          <em>{theme.hint}</em>
        </button>)}
      </div>
    </section>

    <section className="panel">
      <div className="panel-heading"><div><span className="eyebrow">觉得字小就调这里</span><h2>字号与底纹</h2></div></div>
      <div className="pref-rows">
        <div className="pref-row">
          <div><strong>正文字号</strong><em>整体缩放，不改版式。改完这一页就是效果本身。</em></div>
          <div className="chart-range-group" role="group" aria-label="字号">
            {SCALES.map((scale) => <button key={scale.key} type="button" className={`chart-range${prefs.scale === scale.key ? " chart-range--on" : ""}`} onClick={() => update({ scale: scale.key })}>{scale.name}</button>)}
          </div>
        </div>
        <div className="pref-row">
          <div><strong>方格底纹</strong><em>页面背景那层网格。它在长时间阅读时是持续的视觉噪声，关掉更省眼。</em></div>
          <label className="sync-toggle"><input type="checkbox" checked={prefs.grid} onChange={(event) => update({ grid: event.target.checked })} />显示</label>
        </div>
      </div>
    </section>

    <FeedManager />

    <section className="panel">
      <div className="panel-heading"><div><span className="eyebrow">其余设置在各自的页面里</span><h2>去哪里改别的</h2></div></div>
      <div className="pref-rows">
        {ownerHere === true && <div className="pref-row"><div><strong>同步频率与开关</strong><em>七个后台任务各自的周期、暂停与手动触发。</em></div><a className="text-button" href={`${ROUTE_BASE}/data-sources`}>打开数据状态</a></div>}
        {ownerHere === true && <div className="pref-row"><div><strong>备份与恢复</strong><em>手动备份、导出研究记录、从备份恢复。</em></div><a className="text-button" href={`${ROUTE_BASE}/backups`}>打开备份与恢复</a></div>}
        <div className="pref-row"><div><strong>候选策略的条件</strong><em>改门槛、加条件、存成自己的一套。</em></div><a className="text-button" href={`${ROUTE_BASE}/screener`}>打开价值候选</a></div>
        <div className="pref-row"><div><strong>模型配置</strong><em>接口地址与密钥在项目根目录的 <code>.env</code> 里（已 gitignore）：<code>MINIMAX_API_KEY</code>、<code>MINIMAX_BASE_URL</code>、<code>MINIMAX_MODEL</code>。没配也能用，规则会独立工作。</em></div><span className="pref-feed-state">改完需重启服务</span></div>
      </div>
    </section>
  </>;
}

function NewsPageView({ onOpenCompany }: { onOpenCompany: (id: number) => void }) {
  type NewsDisposition = "待确认" | "全部" | "已归档" | "已忽略";
  type NewsReadFilter = "全部" | "已读" | "未读";
  type NewsFocus = "相关" | "未匹配" | "全部";
  const dispositionTabs: Array<{ key: NewsDisposition; label: string; count: (next: NewsPage | null) => number }> = [
    { key: "待确认", label: "待处理", count: (next) => next?.pending ?? 0 },
    { key: "全部", label: "全部", count: (next) => next?.all ?? 0 },
    { key: "已归档", label: "已归档", count: (next) => next?.archived ?? 0 },
    { key: "已忽略", label: "已忽略", count: (next) => next?.ignored ?? 0 },
  ];
  const readTabs: Array<{ key: NewsReadFilter; label: string; count: (next: NewsPage | null) => number }> = [
    { key: "全部", label: "全部", count: (next) => next?.all ?? 0 },
    { key: "未读", label: "未读", count: (next) => next?.unread ?? 0 },
    { key: "已读", label: "已读", count: (next) => next?.read ?? 0 },
  ];
  const [page, setPage] = useState<NewsPage | null>(null);
  const [companies, setCompanies] = useState<CompanyRecord[]>([]);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [dispositionTab, setDispositionTab] = useState<NewsDisposition>("待确认");
  const [readTab, setReadTab] = useState<NewsReadFilter>("全部");
  const [focus, setFocus] = useState<NewsFocus>("相关");

  async function reload(nextDisposition: NewsDisposition = dispositionTab, nextRead: NewsReadFilter = readTab) {
    try {
      const [next, list] = await Promise.all([getNews(nextDisposition, 200, nextRead), getCompanies()]);
      setPage(next);
      setCompanies(list);
      setError("");
    }
    catch (caught) { setError(errorMessage(caught)); }
  }
  useEffect(() => {
    let live = true;
    setLoading(true);
    void reload(dispositionTab, readTab).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [dispositionTab, readTab]);

  // 抓取走后台任务：一轮 20 秒以上，同步跑页面就那么卡着，
  // 切走再回来还得从头点一次——而这一轮的花费已经产生了。
  const [job, setJob] = useState<BackgroundJob | null>(null);
  const running = job !== null && (job.status === "运行中" || job.status === "排队中");

  useEffect(() => {
    let live = true;
    const poll = async () => {
      try {
        const next = await getJob("news_refresh", 0);
        if (!live) return;
        setJob(next);
        if (next && (next.status === "运行中" || next.status === "排队中")) {
          window.setTimeout(() => void poll(), 3000);
        } else if (next?.status === "已完成") {
          await reload(dispositionTab, readTab);
        }
      } catch { /* 轮询失败不打断页面 */ }
    };
    void poll();
    return () => { live = false; };
  }, []);

  async function pull() {
    setError(""); setNotice("");
    try {
      setJob(await refreshNews());
      const poll = async () => {
        const next = await getJob("news_refresh", 0);
        setJob(next);
        if (next && (next.status === "运行中" || next.status === "排队中")) {
          window.setTimeout(() => void poll(), 3000);
        } else if (next?.status === "已完成") {
          await reload(dispositionTab, readTab);
          setNotice(next.note);
        }
      };
      window.setTimeout(() => void poll(), 2500);
    } catch (caught) { setError(errorMessage(caught)); }
  }
  async function confirm(item: NewsItem, companyId: number) {
    setBusy(`c${item.id}`); setError("");
    try { await confirmNews(item.id, companyId); await reload(dispositionTab, readTab); setNotice(`已归档为证据：${item.title.slice(0, 24)}…（极性中性，方向由你判断）`); }
    catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }
  async function drop(item: NewsItem) {
    setBusy(`i${item.id}`);
    try { await ignoreNews(item.id); await reload(dispositionTab, readTab); } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }
  async function markRead(item: NewsItem) {
    if (item.read_at) return;
    setBusy(`r${item.id}`); setError("");
    try {
      const result = await markNewsRead(item.id);
      if (readTab === "未读") {
        await reload(dispositionTab, readTab);
      } else {
        setPage((current) => current ? {
          ...current,
          items: current.items.map((candidate) => candidate.id === item.id ? { ...candidate, read_at: result.read_at } : candidate),
          read: current.read + 1,
          unread: Math.max(0, current.unread - 1),
        } : current);
      }
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }

  const activeDisposition = dispositionTabs.find((tab) => tab.key === dispositionTab) ?? dispositionTabs[0];
  const activeRead = readTabs.find((tab) => tab.key === readTab) ?? readTabs[0];
  const relatedCount = page?.items.filter((item) => item.company_id !== null).length ?? 0;
  const unmatchedCount = page?.items.filter((item) => item.company_id === null).length ?? 0;
  const visibleItems = (page?.items ?? []).filter((item) =>
    focus === "全部" || (focus === "相关" ? item.company_id !== null : item.company_id === null));
  return <>
    <section className="page-intro archive-intro">
      <div><span className="section-kicker">NEWS</span><h1>资讯证据</h1><p>先处理与你研究公司有关的变化。</p></div>
      <div className="local-stamp"><span>FEED</span><strong>{page ? `${activeDisposition.label} · ${activeRead.label} ${page.total} 条` : "等待抓取"}</strong></div>
    </section>
    {error && <p className="form-error">{error}</p>}
    {notice && <p className="restore-message">{notice}</p>}
    {job && <p className={job.status === "失败" || job.status === "已中断" ? "form-error" : "restore-message"}>
      {running ? `${job.label}…　任务在服务端跑，你可以切到别的页面，回来还在。`
        : job.status === "已完成" ? `${job.note}${jobCostText(job) ? `　${jobCostText(job)}` : ""}`
        : `${job.status}：${job.error || job.note}`}
    </p>}
    {loading && <div className="empty-state page-loading">正在读取资讯…</div>}
    {!loading && <>
      <ResearchSummary
        eyebrow="当前收件箱"
        title={relatedCount > 0 ? `${relatedCount} 条与研究公司相关` : "暂未发现相关资讯"}
        items={[
          { label: "待处理", value: page?.pending ?? 0, tone: (page?.pending ?? 0) > 0 ? "warn" : "neutral" },
          { label: "未匹配", value: unmatchedCount, tone: unmatchedCount > 0 ? "neutral" : "good" },
          { label: "已归档", value: page?.archived ?? 0, tone: "good" },
        ]}
        action={<button className="page-action" disabled={running} onClick={() => void pull()}>{running ? "后台抓取中…" : "抓取新资讯"}</button>}
      />
      <section className="panel news-panel--compact">
      <div className="chart-toolbar">
        <div className="news-filter-groups" aria-label="资讯筛选">
          <div className="chart-range-group news-status-tabs" role="group" aria-label="研究相关性">
            <span className="news-filter-label">范围</span>
            {(["相关", "未匹配", "全部"] as NewsFocus[]).map((item) => <button key={item} type="button"
              className={`chart-range${focus === item ? " chart-range--on" : ""}`}
              onClick={() => setFocus(item)}>
              {item}<span className="news-tab-count">{item === "相关" ? relatedCount : item === "未匹配" ? unmatchedCount : page?.items.length ?? 0}</span>
            </button>)}
          </div>
          <div className="chart-range-group news-status-tabs" role="group" aria-label="处理状态">
            <span className="news-filter-label">处理</span>
            {dispositionTabs.map((tab) => <button key={tab.key} type="button"
              className={`chart-range${dispositionTab === tab.key ? " chart-range--on" : ""}`}
              onClick={() => setDispositionTab(tab.key)}>
              {tab.label}<span className="news-tab-count">{tab.count(page)}</span>
            </button>)}
          </div>
          <div className="chart-range-group news-status-tabs" role="group" aria-label="阅读状态">
            <span className="news-filter-label">阅读</span>
            {readTabs.map((tab) => <button key={tab.key} type="button"
              className={`chart-range${readTab === tab.key ? " chart-range--on" : ""}`}
              onClick={() => setReadTab(tab.key)}>
              {tab.label}<span className="news-tab-count">{tab.count(page)}</span>
            </button>)}
          </div>
        </div>
      </div>
      <div className="news-list">
        {visibleItems.length === 0 && <div className="empty-state">
          {focus === "相关" && unmatchedCount > 0
            ? <>当前没有对应到研究公司的资讯。<button className="text-button" onClick={() => setFocus("未匹配")}>查看 {unmatchedCount} 条未匹配</button></>
            : "当前分类还没有资讯。"}
        </div>}
        {/* 13.8 屏的页面没人会滚到底——先给一屏，其余按需展开。见 ShowMore。 */}
        <ShowMore items={visibleItems} step={12} render={(item) => <article className={`news-card news-card--${item.status === "已归档" ? "archived" : item.status === "已忽略" ? "ignored" : "pending"} news-card--${item.read_at ? "read" : "unread"}`} key={item.id}>
          <div className="news-head">
            <span className="news-feed">{item.feed_name}</span>
            <div className="news-head-badges">
              <span className={`news-read-chip news-read-chip--${item.read_at ? "read" : "unread"}`}>{item.read_at ? "已读" : "未读"}</span>
              <span className={`news-disposition-chip news-disposition-chip--${item.status === "已归档" ? "archived" : item.status === "已忽略" ? "ignored" : "pending"}`}>{item.status === "已归档" ? "已归档" : item.status === "已忽略" ? "已忽略" : "待处理"}</span>
            </div>
            <time>{formatDateTime(item.published_at)}</time>
          </div>
          <a className="news-title" href={item.url} target="_blank" rel="noreferrer" onClick={() => { if (!item.read_at) void markRead(item); }}>{item.title}</a>
          <p className="news-match">
            {item.company_id
              ? <><span className={`grade-chip grade-chip--${item.match_confidence === "确定" ? "高" : "中"}`}>{item.company_name}</span>{item.match_reason}</>
              : <span className="news-nomatch">没有对应到已建档公司{item.match_reason ? ` · ${item.match_reason}` : ""}</span>}
          </p>
          {item.summary && <details className="news-context"><summary>内容摘要</summary><p>{item.summary.slice(0, 240)}</p></details>}
          {item.status === "待确认" && <div className="news-actions">
            {item.company_id
              ? <>
                  <button className="page-action page-action--row page-action--small" disabled={busy !== ""} onClick={() => void confirm(item, item.company_id!)}>{busy === `c${item.id}` ? "归档中…" : "归档为证据"}</button>
                  <button className="text-button" onClick={() => onOpenCompany(item.company_id!)}>打开档案</button>
                </>
              : <label className="sync-interval">归到
                  <select defaultValue="" onChange={(event) => { if (event.target.value) void confirm(item, Number(event.target.value)); }}>
                    <option value="">选一家公司</option>
                    {companies.map((company) => <option value={company.id} key={company.id}>{company.name}</option>)}
                  </select>
                </label>}
            {!item.read_at && <button className="text-button" disabled={busy !== ""} onClick={() => void markRead(item)}>{busy === `r${item.id}` ? "标记中…" : "标记已读"}</button>}
            <button className="text-button" disabled={busy !== ""} onClick={() => void drop(item)}>忽略</button>
          </div>}
          {item.status === "已归档" && <div className="news-actions">{item.company_id && <button className="text-button" onClick={() => onOpenCompany(item.company_id!)}>打开档案</button>}{!item.read_at && <button className="text-button" disabled={busy !== ""} onClick={() => void markRead(item)}>{busy === `r${item.id}` ? "标记中…" : "标记已读"}</button>}</div>}
          {item.status === "已忽略" && !item.read_at && <div className="news-actions"><button className="text-button" disabled={busy !== ""} onClick={() => void markRead(item)}>{busy === `r${item.id}` ? "标记中…" : "标记已读"}</button></div>}
        </article>} />
      </div>
      {page && <Boundary text={page.boundary} />}
      </section>
    </>}
  </>;
}

/** 主营构成。单独取一次——它跟产业链是两个数据源，一个是年报事实、一个是模型推断。 */
function SegmentPanel({ companyId }: { companyId: number }) {
  const [data, setData] = useState<SegmentView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setData(null);
    getSegments(companyId).then((next) => { if (live) setData(next); })
      .catch((caught) => { if (live) setError(errorMessage(caught)); });
    return () => { live = false; };
  }, [companyId]);

  async function refresh() {
    setBusy(true); setError("");
    try { setData(await refreshSegments(companyId)); }
    catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  }

  if (error) return <p className="form-error">{error}</p>;
  if (!data) return <div className="trend-loading">正在读取主营构成…</div>;
  return <Suspense fallback={<div className="trend-loading">正在绘制…</div>}>
    <SegmentMix data={data} onRefresh={() => void refresh()} refreshing={busy} />
  </Suspense>;
}

/** 公司级经营关系线索。
 *
 * 这块只回答“可能向谁买、卖给谁、跟谁竞争”。它不再承担产业链地图的职责；
 * 真正的底图先画产品与服务，放在找票分区。
 */
function BusinessRelationshipClues({ fixedCompanyId }: { fixedCompanyId?: number } = {}) {
  const [companies, setCompanies] = useState<CompanyRecord[]>([]);
  const [active, setActive] = useState<number | null>(fixedCompanyId ?? null);
  const [view, setView] = useState<SupplyChainView | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    getCompanies()
      .then((list) => { setCompanies(list); if (fixedCompanyId === undefined) setActive(list[0]?.id ?? null); })
      .catch((c) => setError(errorMessage(c)));
  }, [fixedCompanyId]);
  useEffect(() => {
    if (active === null) return;
    let live = true;
    getSupplyChain(active).then((next) => { if (live) setView(next); }).catch((c) => { if (live) setError(errorMessage(c)); });
    return () => { live = false; };
  }, [active]);

  const [job, setJob] = useState<BackgroundJob | null>(null);
  const running = job !== null && (job.status === "运行中" || job.status === "排队中");
  useEffect(() => {
    if (active === null) return;
    let live = true;
    const poll = async () => {
      try {
        const next = await getJob("supply_chain", active);
        if (!live) return;
        setJob(next);
        if (next && (next.status === "运行中" || next.status === "排队中")) window.setTimeout(() => void poll(), 3000);
        else if (next?.status === "已完成") setView(await getSupplyChain(active));
      } catch { /* 轮询失败不打断页面 */ }
    };
    void poll();
    return () => { live = false; };
  }, [active]);
  async function build() {
    if (active === null) return;
    setError("");
    try {
      setJob(await refreshSupplyChain(active));
      const poll = async () => {
        const next = await getJob("supply_chain", active);
        setJob(next);
        if (next && (next.status === "运行中" || next.status === "排队中")) window.setTimeout(() => void poll(), 3000);
        else if (next?.status === "已完成") setView(await getSupplyChain(active));
      };
      window.setTimeout(() => void poll(), 2500);
    } catch (caught) { setError(errorMessage(caught)); }
  }
  async function act(linkId: number, kind: "confirm" | "delete") {
    setBusy(`${kind}${linkId}`); setError("");
    try {
      if (kind === "confirm") await confirmChainLink(linkId); else await deleteChainLink(linkId);
      if (active !== null) setView(await getSupplyChain(active));
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }

  return <>
    {/* 并进公司页之后就不需要页头和选公司了：那两样东西是"独立页面"才需要的，
        在公司页里它们只会跟档案的标题重复一遍。 */}
    {fixedCompanyId === undefined && <section className="page-intro archive-intro">
      <div><span className="section-kicker">RELATION CLUES</span><h1>经营关系线索</h1><p>可能的采购、客户、竞争与替代关系；核验前只作为研究入口。</p></div>
      <div className="intro-actions">
        <label className="sync-interval">公司
          <select value={active ?? ""} onChange={(event) => setActive(Number(event.target.value))}>
            {companies.map((company) => <option value={company.id} key={company.id}>{company.name} · {company.symbol}</option>)}
          </select>
        </label>
        <div className="local-stamp"><span>LINKS</span><strong>{view ? `${view.confirmed}/${view.links.length} 已证实` : "等待生成"}</strong></div>
      </div>
    </section>}
    {error && <p className="form-error">{error}</p>}
    {job && <p className={job.status === "失败" || job.status === "已中断" ? "form-error" : "restore-message"}>
      {running ? `${job.label} · 后台运行中` : job.status === "已完成" ? `经营关系线索 · ${job.note.replace("条关系", "条线索")}${jobCostText(job) ? `　${jobCostText(job)}` : ""}` : `${job.status}：${job.error || job.note}`}
    </p>}
    {/* **真数据排在推断前面。** 主营构成来自年报分部附注，是披露过的事实；
        下面那张链条图每条都还标着「待证实」。混着排的话，"待证实"三个字
        会被读成整页的免责声明，而不是只针对推断那一块。 */}
    {/* **年报那两块合成一张纸。**
        原来是两张并排的白卡，等高——主营构成还没同步时，左边是半屏空白
        对着右边满满的集中度数字。而且它俩回答的是同一个问题的两半：
        「靠什么赚钱」和「这门生意依赖谁」，本来就该在一张纸上。 */}
    {active !== null && <section className="panel chain-facts">
      <div className="chain-facts-col"><SegmentPanel companyId={active} /></div>
    {/* **产业链位置的硬数排在推断之前。**
        年报强制披露「前五名客户占销售总额多少、前五名供应商占采购总额多少」——
        寒武纪 88.66%、茅台 10.10%，这一个数比下面整张示意图有用得多，
        而且能点回年报原文核对。下面那张图是模型凭世界知识画的，
        实测中国平安的上游七条里有三条是同一件事、两条字面完全相同。 */}
      <div className="chain-facts-col">
        <div className="chain-facts-head">
          <span className="eyebrow">年报披露</span>
          <h3>客户与供应商集中度</h3>
        </div>
        <Suspense fallback={<div className="empty-state">正在加载…</div>}>
          <ChainPosition companyId={active} />
        </Suspense>
      </div>
    </section>}
    {/* **推断那一块要看得出不是一张纸。**
        原来它跟上面两块用同一个 .panel（白底 + 阴影 + 实线边框），
        三块并排看下来是平级的——而它们的可靠性差着一整个数量级：
        上面是年报里点得回原文的数字，这里是模型凭世界知识写的业务类别。
        改成虚线边框、无阴影、沉一档的底：虚线是「未定稿」的通用语汇，
        不用多写一句免责声明，形状本身就说清楚了。 */}
    <section className="chain-infer">
      <div className="chart-toolbar">
        <div>
              <span className="eyebrow">经营关系线索</span>
          {/* **「年报原文」和「模型推断」必须一眼分得开**——那是这个产品
              最该守住的区别，而原来它只靠一段文字说明（「关系来自模型的
              世界知识，可能过期也可能记错」）。一段说明挡不住任何人
              把推断当事实；一个没有链接的记号挡得住。 */}
          <Source kind="模型推断" />
        </div>
        <div className="pool-toolbar-right">
          <button className="page-action" disabled={running || active === null} onClick={() => void build()}>{running ? "后台整理中…" : view && view.links.length > 0 ? "更新线索" : "整理线索"}</button>
        </div>
      </div>
      {view && view.links.length === 0 && <div className="empty-state">还没有经营关系线索。整理后，每条都需要人工确认。</div>}
      {view && view.links.length > 0 && <Suspense fallback={<div className="trend-loading">正在绘制链条…</div>}>
        <ChainMap links={view.links} busy={busy}
                  companyName={companies.find((c) => c.id === active)?.name ?? "本公司"}
                  onConfirm={(id) => void act(id, "confirm")}
                  onDelete={(id) => void act(id, "delete")}
                  onAdd={async (payload) => {
                    if (active === null) return;
                    setError("");
                    try { setView(await addChainLink(active, payload)); }
                    catch (caught) { setError(errorMessage(caught)); }
                  }} />
      </Suspense>}
      {view && <Boundary text={view.boundary} />}
    </section>
  </>;
}

/** 研究报告。**报告是给具体公司做的**，所以它并进了公司详情页的页签。
 *
 * `fixedCompanyId` 一给，就只显示这家公司的报告，也不再问"给哪家生成"。
 */
function ReportsPage({ onOpenCompany, fixedCompanyId }: {
  onOpenCompany: (id: number) => void; fixedCompanyId?: number;
}) {
  const [companies, setCompanies] = useState<CompanyRecord[]>([]);
  const [reports, setReports] = useState<ResearchReport[]>([]);
  const [target, setTarget] = useState<number | null>(fixedCompanyId ?? null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [error, setError] = useState("");

  async function reload() {
    try {
      const [list, rows] = await Promise.all([getCompanies(), getReports()]);
      setCompanies(list);
      // 并进公司页时只留这家公司的报告——别的公司的报告出现在这家的档案里是错的
      setReports(fixedCompanyId === undefined ? rows : rows.filter((r) => r.company_id === fixedCompanyId));
      setTarget((prev) => fixedCompanyId ?? prev ?? list[0]?.id ?? null);
      setError("");
    }
    catch (caught) { setError(errorMessage(caught)); }
  }
  useEffect(() => { void reload(); }, []);

  const [job, setJob] = useState<BackgroundJob | null>(null);
  const running = job !== null && (job.status === "运行中" || job.status === "排队中");
  useEffect(() => {
    if (target === null) return;
    let live = true;
    void (async () => {
      try { const next = await getJob("report", target); if (live) setJob(next); } catch { /* 忽略 */ }
    })();
    return () => { live = false; };
  }, [target]);
  async function make() {
    if (target === null) return;
    setError("");
    try {
      setJob(await generateReport(target));
      const poll = async () => {
        const next = await getJob("report", target);
        setJob(next);
        if (next && (next.status === "运行中" || next.status === "排队中")) window.setTimeout(() => void poll(), 3000);
        else await reload();
      };
      window.setTimeout(() => void poll(), 2500);
    } catch (caught) { setError(errorMessage(caught)); }
  }

  const [plan, setPlan] = useState<DeepReportPlan | null>(null);
  useEffect(() => {
    if (target === null) { setPlan(null); return; }
    let live = true;
    getDeepReportPlan(target).then((p) => { if (live) setPlan(p); }).catch(() => undefined);
    return () => { live = false; };
  }, [target]);

  async function makeDeep() {
    if (target === null) return;
    setError("");
    try {
      setJob(await makeDeepReport(target));
      const poll = async () => {
        const next = await getJob("deep_report", target);
        setJob(next);
        if (next && (next.status === "运行中" || next.status === "排队中")) window.setTimeout(() => void poll(), 4000);
        else await reload();
      };
      window.setTimeout(() => void poll(), 4000);
    } catch (caught) { setError(errorMessage(caught)); }
  }

  return <>
    {fixedCompanyId === undefined && <section className="page-intro archive-intro">
      <div><span className="section-kicker">REPORTS</span><h1>研究报告</h1><p>联网找公开资料，配上库里的真实数字写成报告。<strong>数字只用本站同步的那一份</strong>——网页上的财务数字经常过期或口径不同。每条判断都带资料编号，查不到的如实写「还不知道」。</p></div>
      <div className="local-stamp"><span>VERSIONS</span><strong>{reports.length} 份</strong></div>
    </section>}
    {error && <p className="form-error">{error}</p>}
    {job && <p className={job.status === "失败" || job.status === "已中断" ? "form-error" : "restore-message"}>
      {running ? `${job.label} · 后台运行中` : job.status === "已完成" ? `${job.note}${jobCostText(job) ? `　${jobCostText(job)}` : ""}` : `${job.status}：${job.error || job.note}`}
    </p>}
    <section className="panel reports-panel--compact">
      <div className="chart-toolbar">
        {fixedCompanyId === undefined
          ? <label className="sync-interval">给哪家生成
              <select value={target ?? ""} onChange={(event) => setTarget(Number(event.target.value))}>
                {companies.map((company) => <option value={company.id} key={company.id}>{company.name} · {company.symbol}</option>)}
              </select>
            </label>
          : <div><span className="eyebrow">研究报告</span><strong className="reports-count">{reports.length} 份历史版本</strong></div>}
        <div className="pool-toolbar-right">
          <button className="page-action" disabled={running || target === null}
                  title={plan?.note}
                  onClick={() => void makeDeep()}>
            {running ? "后台生成中…" : `生成深度报告${plan ? ` · ${plan.credits} 分` : ""}`}
          </button>
          <button className="text-button" disabled={running || target === null} onClick={() => void make()}>{running ? "…" : "生成档案摘要"}</button>
        </div>
      </div>
      {reports.length === 0 && <div className="empty-state">还没有报告。先归档证据，再生成第一份。</div>}
      <ShowMore items={reports} step={5} noun="份" render={(report) => {
        const previewRaw = report.cards[0]?.point || report.sections[0]?.lines[0] || report.business[0]
          || report.changes[0] || report.body.split("\n").find((line) => line.trim()) || "暂无摘要";
        const preview = previewRaw.replace(/^#{1,6}\s*/, "").replace(/\*\*/g, "").trim();
        return <article className={`report-card report-card--compact${openId === report.id ? " report-card--open" : ""}`} key={report.id}>
          <div className="report-card-top">
            <button className="report-head" onClick={() => setOpenId(openId === report.id ? null : report.id)}>
              <div><strong>{report.title}</strong><span className="method-chip">v{report.version}</span>
                {report.kind === "deep" && <span className="method-chip method-chip--deep">联网</span>}</div>
              <p className="report-preview">{preview}</p>
              <span>引用 {report.source_count} 条 · {formatDateTime(report.created_at)}</span>
            </button>
            <button className="text-button text-button--danger report-drop"
                    aria-label={`删除${report.title}`}
                    onClick={async () => {
                      try { await deleteReport(report.id); await reload(); }
                      catch (caught) { setError(errorMessage(caught)); }
                    }}>删除</button>
          </div>
          {openId === report.id && <div className="report-body">
          <Suspense fallback={<div className="trend-loading">正在展开…</div>}>
            {/* 老报告 kind='local'，走旧版式；联网那一版有结论卡、主题图与资料覆盖 */}
            {report.kind === "deep"
              ? <DeepReport report={report} />
              : <ReportBody report={report} />}
          </Suspense>
          {report.unknowns.length > 0 && <div><h5>档案里还没有答案的</h5><ul className="draft-unknown">{report.unknowns.map((u) => <li key={u}>{u}</li>)}</ul></div>}
          <p className="report-note">{report.model} · {report.source_count} 条资料 <button className="text-button" onClick={() => onOpenCompany(report.company_id)}>公司档案</button></p>
          </div>}
        </article>;
      }} />
    </section>
  </>;
}

function MethodsPage({ onOpenCompany }: { onOpenCompany: (id: number) => void }) {
  const [library, setLibrary] = useState<ThesisMethodLibrary | null>(null);
  const [companies, setCompanies] = useState<CompanyRecord[]>([]);
  const [beginnerOnly, setBeginnerOnly] = useState(false);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    Promise.all([getMethodLibrary(), getCompanies()])
      .then(([nextLibrary, nextCompanies]) => { if (current) { setLibrary(nextLibrary); setCompanies(nextCompanies); setError(""); } })
      .catch((caught) => { if (current) setError(errorMessage(caught)); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, []);

  const total = library ? library.categories.reduce((sum, category) => sum + category.methods.length, 0) : 0;
  return <>
    <section className="page-intro archive-intro">
      <div>
        <span className="section-kicker">METHODS</span>
        <h1>投资逻辑方法库</h1>
        <p>不知道买入理由怎么写的时候，从这里挑一个方法照着填。每个方法都写了出处、适用边界，和它自己的盲区。</p>
      </div>
      <div className="local-stamp"><span>LIBRARY</span><strong>{total} 个方法</strong></div>
    </section>
    {error && <p className="form-error">{error}</p>}
    {/* 矩阵放在方法清单之前：这一页在讲「有哪些方法」，
        而「你的池子在这些方法下什么样」是更该先看到的那一句。 */}
    <AssessmentMatrixPanel onOpenCompany={onOpenCompany} />
    {loading && <div className="empty-state page-loading">正在读取方法库…</div>}
    {library && <>
      <div className="chart-toolbar">
        <div className="chart-range-group" role="group" aria-label="筛选方法">
          <button type="button" className={`chart-range${beginnerOnly ? "" : " chart-range--on"}`} onClick={() => setBeginnerOnly(false)}>全部</button>
          <button type="button" className={`chart-range${beginnerOnly ? " chart-range--on" : ""}`} onClick={() => setBeginnerOnly(true)}>先看容易上手的</button>
        </div>
        <span className="chart-legend-note">方法可以叠加用，也应该叠加：多数方法只覆盖判断的一个侧面。</span>
      </div>
      {library.categories.map((category) => {
        const items = category.methods.filter((method) => !beginnerOnly || method.beginner);
        if (items.length === 0) return null;
        return <section className="panel" key={category.key}>
          <div className="panel-heading"><div><span className="eyebrow">{category.intro}</span><h2>{category.label}</h2></div></div>
          <div className="method-list-stack">
            {items.map((method) => <article className={`method-card${openKey === method.key ? " method-card--open" : ""}`} key={method.key}>
              <button className="method-card-head" onClick={() => setOpenKey(openKey === method.key ? null : method.key)}>
                <div>
                  <strong>{method.name}</strong>
                  {method.beginner && <span className="method-chip">容易上手</span>}
                  <span className="method-effort">{method.effort}</span>
                </div>
                <em>{method.one_liner}</em>
                <p className="method-question">它逼你回答：{method.core_question}</p>
              </button>
              {openKey === method.key && <MethodDetailPanel methodKey={method.key} companies={companies} onDraft={onOpenCompany} />}
            </article>)}
          </div>
        </section>;
      })}
      <Boundary text={library.boundary} />
    </>}
  </>;
}

function ThesisForm({ companyId, onSaved, onCancel }: { companyId: number; onSaved: () => Promise<void>; onCancel: () => void }) {
  const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  const [draft] = useState(() => takeThesisDraft());
  // 方法可以在这里直接选，不用先跑一趟方法库
  const [library, setLibrary] = useState<ThesisMethodLibrary | null>(null);
  const [methodKey, setMethodKey] = useState("");
  const [applied, setApplied] = useState<string | null>(draft?.method ?? null);
  const [claim, setClaim] = useState(draft?.claim ?? "");
  const [counter, setCounter] = useState(draft?.counter ?? "");
  const [trigger, setTrigger] = useState(draft?.trigger ?? "手动复核");
  useEffect(() => { let live = true; getMethodLibrary().then((next) => { if (live) setLibrary(next); }).catch(() => undefined); return () => { live = false; }; }, []);
  const [drafted, setDrafted] = useState<ThesisDraft | null>(null);
  const [job, setJob] = useState<BackgroundJob | null>(null);
  // 价钱不挂在按钮上，扣之前弹一句（见 lib/credits.ts 的 useSpendGuard）。
  const confirmSpend = useSpendGuard();
  // **起草改成后台任务了。**
  //
  // 它自己查库之后从 7 秒变成 57 秒实测，而接口一直是同步阻塞的——
  // 界面上唯一的反馈是按钮文字变一下，使用者等几秒看不出进展就判定它坏了。
  // 现在跟承诺抽取、反方 Agent 一样：提交、轮询、失败要说出来。
  const drafting = job !== null && (job.status === "运行中" || job.status === "排队中");
  useEffect(() => {
    if (!drafting) return;
    const timer = window.setInterval(() => {
      void getJob("thesis_draft", companyId).then((next) => {
        setJob(next);
        if (next?.status === "已完成" && next.result) {
          const result = (next.result as unknown) as ThesisDraft;
          setClaim(result.claim); setCounter(result.counter_condition);
          setTrigger(result.next_review_trigger);
          setDrafted(result);
          setApplied(result.method ? `${result.method}｜模型起草` : "模型起草");
        }
      }).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [drafting, companyId]);

  async function askModel() {
    if (!(await confirmSpend("thesis-draft", "让模型自己去查这家公司的库，起草一条判断。"))) return;
    setSaving(true); setError(""); setDrafted(null);
    try { setJob(await draftThesis(companyId, methodKey || undefined)); }
    catch (caught) { setError(errorMessage(caught)); }
    finally { setSaving(false); }
  }
  async function applyMethod(key: string) {
    setMethodKey(key);
    if (!key) return;
    const overwriting = claim.trim() !== "" || counter.trim() !== "";
    if (overwriting && !(await confirmAction({
      title: "套用模板会覆盖你已经写下的内容",
      detail: "现在框里的字会被模板整段替换掉，换回来只能重打。",
      confirmText: "覆盖并套用", danger: true,
    }))) { setMethodKey(""); return; }
    try {
      const method = await getMethod(key);
      setClaim(method.claim_template); setCounter(method.counter_template); setTrigger(method.trigger_template); setApplied(method.name);
    } catch (caught) { setError(errorMessage(caught)); }
  }
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setSaving(true); setError(""); const form = new FormData(event.currentTarget); const payload: ThesisInput = { claim: String(form.get("claim") ?? ""), counter_condition: String(form.get("counter_condition") ?? ""), status: String(form.get("status") ?? "watching") as ThesisStatus, next_review_trigger: String(form.get("next_review_trigger") ?? "手动复核") }; try { await createThesis(companyId, payload); await onSaved(); onCancel(); } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); } }
  return <form className="inline-form" onSubmit={submit}><label className="thesis-method-pick">不知道怎么写？先挑一个方法
      <select value={methodKey} onChange={(event) => void applyMethod(event.target.value)}>
        <option value="">不套模板，自己写</option>
        {library?.categories.map((category) => <optgroup label={category.label} key={category.key}>
          {category.methods.map((method) => <option value={method.key} key={method.key}>{method.name}{method.beginner ? "（容易上手）" : ""} — {method.one_liner}</option>)}
        </optgroup>)}
      </select>
    </label>
    <div className="draft-bar">
      <button className="page-action" type="button" disabled={saving || drafting}
        onClick={() => void askModel()}>
        {drafting ? "正在查库起草…约一分钟" : saving ? "正在提交…" : "让模型自己查库起草"}
      </button>
      {/* **一分钟的等待必须有话说。** 只让按钮变个文字，跟卡死长得一样。 */}
      {drafting && <span className="form-note">
        <strong>它在服务端一张表一张表地查</strong>，可以切走，回来还在。
      </span>}
      {/* 任务失败要摆出来，否则又是"点了没反应"。 */}
      <JobTrouble job={job} onRetry={() => void askModel()} retrying={saving} />
      <span><strong>它会自己去查这家公司的库</strong>——看什么由它按这家公司决定。不给目标价、不给买卖时点，是草稿，保存前请逐句核对。</span>
    </div>
    {drafted && <div className="draft-report">
      {/* **查了哪几张表要摆在最前面。** 这是"它没瞎说"最直接的证明，
          也是你判断这条草稿值不值得逐句读的第一个信号。 */}
      {drafted.read && <p className="draft-read">查了：{drafted.read}</p>}
      <div><h5>它用到的事实（{drafted.used_facts.length} 条）</h5><ul>{drafted.used_facts.map((fact) => <li key={fact}>{fact}</li>)}</ul></div>
      {drafted.unknowns.length > 0 && <div><h5>它承认自己不知道的</h5><ul className="draft-unknown">{drafted.unknowns.map((item) => <li key={item}>{item}</li>)}</ul></div>}
      <p>{drafted.boundary}（模型 {drafted.model}）</p>
      <BillingNote billing={drafted.billing} />
    </div>}
    {applied && <p className="method-applied">套用「{applied}」的模板。把方括号里的内容换成这家公司的具体事实再保存——原样保存等于没有理由。</p>}<label>可验证的主张<textarea name="claim" rows={applied ? 3 : 2} required value={claim} onChange={(event) => setClaim(event.target.value)} placeholder="例如：产品结构升级能改善毛利率，同时现金回收不恶化。" /></label><label>什么事实会推翻它？<textarea name="counter_condition" rows={applied ? 3 : 2} value={counter} onChange={(event) => setCounter(event.target.value)} placeholder="写下反证条件，而不是泛泛风险。" /></label><div className="form-grid compact-grid"><label>当前状态<select name="status" defaultValue="watching"><option value="intact">成立</option><option value="watching">待观察</option><option value="challenged">受挑战</option><option value="broken">已破坏</option></select></label><label>下次复核触发<input name="next_review_trigger" value={trigger} onChange={(event) => setTrigger(event.target.value)} required /></label></div>{error && <p className="form-error">{error}</p>}<div className="form-actions"><button className="page-action" type="submit" disabled={saving}>{saving ? "正在保存…" : "保存投资逻辑"}</button><button className="text-button" type="button" onClick={onCancel}>取消</button></div></form>;
}

function EvidenceForm({ company, onSaved, onCancel }: { company: CompanyDetail; onSaved: () => Promise<void>; onCancel: () => void }) {
  const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setSaving(true); setError(""); const form = new FormData(event.currentTarget); const sourceUrl = String(form.get("source_url") ?? "").trim(); const thesisId = String(form.get("thesis_id") ?? ""); const payload: EvidenceInput = { thesis_id: thesisId ? Number(thesisId) : null, source_name: String(form.get("source_name") ?? ""), ...(sourceUrl ? { source_url: sourceUrl } : {}), excerpt: String(form.get("excerpt") ?? ""), polarity: String(form.get("polarity") ?? "neutral") as EvidenceInput["polarity"], verification: String(form.get("verification") ?? "待核验") }; try { await createEvidence(company.id, payload); await onSaved(); onCancel(); } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); } }
  return <form className="inline-form" onSubmit={submit}><div className="form-grid compact-grid"><label>证据来源<input name="source_name" placeholder="例如：2025 年年报" required /></label><label>关联逻辑<select name="thesis_id" defaultValue=""><option value="">暂不关联</option>{company.theses.map((thesis) => <option value={thesis.id} key={thesis.id}>{thesis.claim.slice(0, 28)}…</option>)}</select></label><label>证据方向<select name="polarity" defaultValue="neutral"><option value="support">支持逻辑</option><option value="counter">构成反证</option><option value="neutral">中性记录</option></select></label><label>核验状态<input name="verification" defaultValue="待核验" required /></label></div><label>来源链接（可选）<input name="source_url" type="url" placeholder="https://…" /></label><label>关键原文或你的事实摘录<textarea name="excerpt" rows={3} required placeholder="只摘录能支持、反驳或验证某条逻辑的事实。" /></label>{error && <p className="form-error">{error}</p>}<div className="form-actions"><button className="page-action" type="submit" disabled={saving}>{saving ? "正在保存…" : "归档证据"}</button><button className="text-button" type="button" onClick={onCancel}>取消</button></div></form>;
}

function EventForm({ company, onSaved, onCancel }: { company: CompanyDetail; onSaved: () => Promise<void>; onCancel: () => void }) {
  const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setSaving(true); setError(""); const form = new FormData(event.currentTarget); const thesisId = String(form.get("thesis_id") ?? ""); const payload: ResearchEventInput = { thesis_id: thesisId ? Number(thesisId) : null, category: String(form.get("category") ?? ""), title: String(form.get("title") ?? ""), importance: String(form.get("importance") ?? "medium") as ResearchEventInput["importance"], verification: String(form.get("verification") ?? "待核验") }; try { await createResearchEvent(company.id, payload); await onSaved(); onCancel(); } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); } }
  return <form className="inline-form" onSubmit={submit}><div className="form-grid compact-grid"><label>事件类型<input name="category" defaultValue="公司公告" required /></label><label>重要程度<select name="importance" defaultValue="medium"><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label><label>关联逻辑<select name="thesis_id" defaultValue=""><option value="">暂不关联</option>{company.theses.map((thesis) => <option value={thesis.id} key={thesis.id}>{thesis.claim.slice(0, 28)}…</option>)}</select></label><label>核验状态<input name="verification" defaultValue="待核验" required /></label></div><label>发生了什么？<textarea name="title" rows={3} required placeholder="用事实描述事件，不要直接写结论或操作建议。" /></label>{error && <p className="form-error">{error}</p>}<div className="form-actions"><button className="page-action" type="submit" disabled={saving}>{saving ? "正在保存…" : "记录事件"}</button><button className="text-button" type="button" onClick={onCancel}>取消</button></div></form>;
}

function formatMarketChange(value: number | null): string {
  return value === null ? "暂无数据" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatBillion(value: number | null): string {
  return value === null ? "—" : `${(value / 100_000_000).toFixed(1)} 亿`;
}

function formatShares(value: number | null): string {
  if (value === null) return "—";
  return value >= 100_000_000 ? `${(value / 100_000_000).toFixed(2)} 亿股` : `${(value / 10_000).toFixed(2)} 万股`;
}

function formatYi(value: number | null): string {
  if (value === null) return "—";
  return value >= 100_000_000 ? `${(value / 100_000_000).toFixed(2)} 亿元` : `${(value / 10_000).toFixed(2)} 万元`;
}

/** 从“10派28.5元(含税)”这类方案文字里取出每股分红；取不到就不估算股息率。 */
function dividendPerShare(plan: string | null): number | null {
  if (!plan) return null;
  const match = plan.match(/(\d+(?:\.\d+)?)\s*[股]?\s*派\s*(\d+(?:\.\d+)?)/);
  if (!match) return null;
  const base = Number(match[1]);
  const payout = Number(match[2]);
  if (!base || !Number.isFinite(payout)) return null;
  return payout / base;
}

type BriefTab = "essentials" | "profile" | "calendar";

function CompanyBriefPanel({ company, refreshing, onRefresh, onSaved }: { company: CompanyDetail; refreshing: boolean; onRefresh: () => void; onSaved: () => Promise<void> }) {
  const [briefTab, setBriefTab] = useState<BriefTab>("essentials");
  const profile = company.profile;
  const perShare = dividendPerShare(profile?.latest_dividend_plan ?? null);
  const dividendYield = perShare !== null && company.latest_price ? (perShare / company.latest_price) * 100 : null;
  const nextEvent = profile?.upcoming_events[0] ?? null;
  const overview: Array<{ label: string; value: string | null; link?: string | null }> = profile ? [
    { label: "主营业务", value: profile.main_business },
    { label: "主要产品", value: profile.product_type },
    { label: "所属行业", value: profile.industry },
    { label: "所属市场", value: profile.market ? `${profile.market} · ${company.symbol}` : company.exchange },
    { label: "法人代表", value: profile.legal_representative },
    { label: "注册资金", value: profile.registered_capital === null ? null : formatYi(profile.registered_capital) },
    { label: "成立日期", value: profile.founded_date },
    { label: "上市日期", value: profile.listed_date },
    { label: "注册地址", value: profile.registered_address },
    { label: "办公地址", value: profile.office_address },
    { label: "公司全称", value: profile.full_name },
    { label: "英文名称", value: profile.english_name },
    { label: "官方网站", value: profile.website, link: profile.website ? `https://${profile.website.replace(/^https?:\/\//, "")}` : null },
  ] : [];
  const essentials = profile ? [
    {
      label: "股本结构",
      value: formatShares(profile.total_shares),
      detail: `流通股 ${formatShares(profile.circulating_shares)}${profile.share_structure_date ? ` · 截至 ${profile.share_structure_date}` : ""}`,
    },
    {
      label: "最近一次分红",
      value: profile.latest_dividend_plan ?? "来源未提供",
      detail: [profile.latest_dividend_period, profile.latest_dividend_progress, profile.latest_dividend_ex_date && `除权除息 ${profile.latest_dividend_ex_date}`].filter(Boolean).join(" · ") || "—",
    },
    {
      label: "股息率估算",
      value: dividendYield === null ? "无法估算" : `${dividendYield.toFixed(2)}%`,
      detail: dividendYield === null ? "方案文字无法解析或未同步现价" : `按最新价 ¥${company.latest_price?.toFixed(2)} 与每股 ${perShare?.toFixed(4)} 元估算`,
    },
    {
      label: "股利支付率",
      value: profile.latest_dividend_payout_ratio ?? "来源未提供",
      detail: profile.latest_dividend_period ? `${profile.latest_dividend_period}口径` : "以数据源披露为准",
    },
    {
      label: "上市与发行",
      value: profile.listed_date ?? "来源未提供",
      detail: [profile.issue_price !== null && `发行价 ¥${profile.issue_price}`, profile.raised_net !== null && `募资净额 ${formatYi(profile.raised_net)}`].filter(Boolean).join(" · ") || "—",
    },
    {
      label: "下一件已排期的事",
      value: nextEvent ? `${nextEvent.category} · ${nextEvent.event_date}` : "近期无已排期事项",
      detail: nextEvent ? nextEvent.title : `已归档 ${profile.event_count} 条大事记录`,
    },
  ] : [];
  return <section className="panel brief-panel">
    <div className="panel-heading">
      <div>
        <span className="eyebrow">已接入的公开资料</span><PanelTitle hint="概况、股本、分红与大事均来自公开披露，只搬运事实、标注来源，不做评级也不给操作建议。">公司简况</PanelTitle>
      </div>
      <button className="page-action" onClick={onRefresh} disabled={refreshing}>{refreshing ? "正在同步简况…" : profile ? "更新公司简况" : "同步公司简况"}</button>
    </div>
    {!profile ? <div className="market-history-empty">尚未同步公司简况。点击右上角，读取巨潮资讯的公司资料、股本与公告，以及同花顺的分红方案和新浪的限售解禁安排。</div> : <>
      <div className="brief-source-line">{profile.source} · 同步于 {formatDateTime(profile.refreshed_at)}{profile.missing_sections.length > 0 ? ` · 本次未取到：${profile.missing_sections.join("、")}` : ""}</div>
      <div className="brief-tabs" role="tablist" aria-label="公司简况分区">
        {([[
          "essentials", "操盘必读", "股本、分红与下一件大事",
        ], [
          "profile", "公司概况", "公开资料与经营范围",
        ], [
          "calendar", "大事提醒", `共归档 ${profile.event_count} 条`,
        ]] as Array<[BriefTab, string, string]>).map(([key, label, hint]) => <button key={key} type="button" role="tab" aria-selected={briefTab === key} className={`brief-tab${briefTab === key ? " brief-tab--on" : ""}`} onClick={() => setBriefTab(key)}><strong>{label}</strong><span>{hint}</span></button>)}
      </div>
      {briefTab === "essentials" && <section className="brief-subsection brief-subsection--essentials">
        <div className="brief-facts">{essentials.map((item) => <article key={item.label}><span>{item.label}</span><strong>{item.value}</strong><em>{item.detail}</em></article>)}</div>
      </section>}
      {briefTab === "profile" && <section className="brief-subsection brief-subsection--profile">
        <div className="brief-profile">
          <dl>{overview.filter((item) => item.value).map((item) => <div key={item.label}><dt>{item.label}</dt><dd>{item.link ? <a href={item.link} target="_blank" rel="noreferrer">{item.value}</a> : item.value}</dd></div>)}</dl>
          {profile.business_scope && <div className="brief-text"><h3>经营范围</h3><p>{profile.business_scope}</p></div>}
          {profile.introduction && <div className="brief-text"><h3>机构简介</h3><p>{profile.introduction}</p></div>}
        </div>
      </section>}
      {briefTab === "calendar" && <section className="brief-subsection brief-subsection--calendar">
        <div className="brief-calendar-scroll">
          <div className="brief-calendar">
            <div className="brief-calendar-group">
              <h3>即将发生</h3>
              {profile.upcoming_events.length === 0 ? <p className="brief-empty">数据源中没有已排期的分红、解禁或公告事项。</p> : profile.upcoming_events.map((event) => <BriefEventRow event={event} company={company} onArchived={onSaved} key={`${event.category}-${event.event_date}-${event.title}`} />)}
            </div>
            <div className="brief-calendar-group">
              <h3>最近发生</h3>
              {profile.recent_events.length === 0 ? <p className="brief-empty">尚未同步到历史事项。</p> : profile.recent_events.map((event) => <BriefEventRow event={event} company={company} onArchived={onSaved} key={`${event.category}-${event.event_date}-${event.title}`} />)}
            </div>
          </div>
        </div>
        <p className="brief-empty brief-calendar-note">事件是否影响你的投资逻辑，仍由你在“事件记录”中确认。</p>
      </section>}
    </>}
  </section>;
}

function BriefEventRow({ event, company, onArchived }: { event: CompanyCalendarEvent; company?: CompanyDetail; onArchived?: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const archivable = event.id !== null && company !== undefined && onArchived !== undefined && event.inbox_status === "待核验";
  const item: InboxItem | null = event.id === null || company === undefined ? null : {
    id: event.id,
    company_id: company.id,
    symbol: company.symbol,
    company_name: company.name,
    category: event.category,
    event_date: event.event_date,
    title: event.title,
    detail: event.detail,
    url: event.url,
    source: event.source,
    inbox_status: event.inbox_status,
    archived_as: event.archived_as,
    archived_ref_id: null,
    handled_at: null,
    relevance: event.relevance ?? null,
    relevance_reason: null,
    relevance_source: null,
    relevance_topic: null,
    summary: null,
  };
  return <article className={`brief-event brief-event--${event.category}`}>
    <time>{event.event_date}</time>
    <span className="brief-chip">{event.category}</span>
    <div>
      {event.url ? <a href={event.url} target="_blank" rel="noreferrer">{event.title}</a> : <strong>{event.title}</strong>}
      {event.detail && <em>{event.detail}</em>}
      {archivable && <button className="text-button brief-archive" onClick={() => setOpen((value) => !value)}>{open ? "取消归档" : "归档为证据或事件"}</button>}
      {open && item && onArchived && <InboxArchiveForm item={item} onDone={onArchived} onCancel={() => setOpen(false)} />}
    </div>
    <span className="brief-source">{event.inbox_status === "已归档" ? `已归档为${event.archived_as === "evidence" ? "证据" : "事件"}` : event.inbox_status === "已忽略" ? "已忽略" : event.source}</span>
  </article>;
}

function MarketFactsPanel({ company, refreshing, onRefresh }: { company: CompanyDetail; refreshing: boolean; onRefresh: () => void }) {
  const history = company.market_history;
  const intervals = history ? [
    { label: "5 个交易日", value: history.price_5d_change },
    { label: "20 个交易日", value: history.price_20d_change },
    { label: "年初至今", value: history.ytd_change },
    { label: "近一年", value: history.one_year_change },
  ] : [];
  return <section className="panel market-facts-panel">
    <div className="panel-heading">
      <div><span className="eyebrow">已接入的市场事实</span><PanelTitle hint="区间表现基于前复权日线，不是买卖建议。">行情与估值 <Source kind="底座" /></PanelTitle></div>
      <button className="page-action" onClick={onRefresh} disabled={refreshing}>{refreshing ? "正在同步日线…" : history ? "更新日线数据" : "同步日线数据"}</button>
    </div>
    <div className="market-facts-grid">
      <article><span>最新价格</span><strong>{company.latest_price === null ? "暂未同步" : `¥ ${company.latest_price.toFixed(2)}`}</strong><em className={company.change_percent !== null && company.change_percent < 0 ? "quote-down" : "quote-up"}>{formatMarketChange(company.change_percent)}</em></article>
      <article><span>PE / PB</span><strong>{company.pe === null ? "PE 暂无" : `PE ${company.pe.toFixed(2)}`}</strong><em>{company.pb === null ? "PB 暂无" : `PB ${company.pb.toFixed(2)}`}</em></article>
      <article><span>52 周区间</span><strong>{company.low_52w === null || company.high_52w === null ? "暂无返回" : `¥ ${company.low_52w.toFixed(2)} — ${company.high_52w.toFixed(2)}`}</strong><em>来源 {company.market_source ?? "StockSDK"}</em></article>
      <article><span>最新行情时间</span><strong>{company.market_timestamp ? formatDateTime(company.market_timestamp) : "暂未同步"}</strong><em>{company.exchange}</em></article>
    </div>
    {!history && <div className="market-history-empty">尚未同步日线。点击右上角即可加载真实的价格趋势和区间表现。</div>}
    {history && <>
      <div className="market-intervals">{intervals.map((item) => <div key={item.label}><span>{item.label}</span><strong className={item.value !== null && item.value < 0 ? "quote-down" : "quote-up"}>{formatMarketChange(item.value)}</strong></div>)}</div>
      <Suspense fallback={<div className="trend-loading">正在绘制真实日线走势…</div>}><PriceTrend bars={history.bars} high52w={company.high_52w} low52w={company.low_52w} events={company.events} /></Suspense>
      <p className="market-history-note">{history.adjusted} · 截止 {history.latest_trade_date} · {history.source} · 同步于 {formatDateTime(history.refreshed_at)}</p>
    </>}
  </section>;
}

function ValuationPanel({ company, refreshing, onRefresh }: { company: CompanyDetail; refreshing: boolean; onRefresh: () => void }) {
  const valuation = company.valuation;
  const [metricKey, setMetricKey] = useState("pe_ttm");
  const metric = valuation?.metrics.find((item) => item.metric === metricKey) ?? valuation?.metrics[0] ?? null;
  return <section className="panel valuation-panel">
    <div className="panel-heading">
      <div>
        <span className="eyebrow">已接入的历史估值</span><PanelTitle hint="分位只说明当前值在历史样本中的位置，不代表贵或便宜，也不构成买卖建议。">估值分位</PanelTitle>
      </div>
      <button className="page-action" onClick={onRefresh} disabled={refreshing}>{refreshing ? "正在同步估值…" : valuation ? "更新历史估值" : "同步历史估值"}</button>
    </div>
    {!valuation || !metric ? <div className="market-history-empty">尚未同步历史估值。点击右上角，读取百度股市通近五年的市盈率（TTM）与市净率序列，并在本地计算 3 年、5 年分位。</div> : <>
      <div className="chart-toolbar">
        <div className="chart-range-group" role="tablist" aria-label="选择估值指标">
          {valuation.metrics.map((item) => <button key={item.metric} type="button" role="tab" aria-selected={item.metric === metric.metric} className={`chart-range${item.metric === metric.metric ? " chart-range--on" : ""}`} onClick={() => setMetricKey(item.metric)}>{item.label}</button>)}
        </div>
        <span className="chart-legend-note">{valuation.source} · 同步于 {formatDateTime(valuation.refreshed_at)}</span>
      </div>
      <div className="valuation-grid">
        <article className="valuation-current">
          <span>{metric.label}（当前）</span>
          <strong>{metric.current === null ? "来源未提供" : metric.current.toFixed(2)}</strong>
          <em>{metric.current_date ? `数据截至 ${metric.current_date}` : "无截止日"}{company.pe !== null && metric.metric === "pe_ttm" ? ` · 实时行情 PE ${company.pe.toFixed(2)}（口径可能不同）` : ""}</em>
        </article>
        {metric.windows.map((window) => <article className="valuation-window" key={window.window_years}>
          {/* **样本铺不满窗口时，标题就不能叫「近 N 年分位」。**
              实测：寒武纪 2025-04 才转正，之前没有 PE，于是「近 3 年分位」和
              「近 5 年分位」是同一个 5.6% —— 背后是同一批 16 个月的样本。
              读的人会理解成"比过去五年里 94% 的时间都便宜"，
              **而过去五年根本没有数据**。这不是少一句提示，
              是标题在替这个数字说一件没发生过的事。
              所以标题改成真实跨度，数字保留（16 个月也是信息）。 */}
          <div className="valuation-window-head">
            <span>{window.coverage_note && window.covered_years !== null
              ? <>只有 {window.covered_years} 年的分位<em className="valuation-window-asked">（问的是近 {window.window_years} 年）</em></>
              : <>近 {window.window_years} 年分位</>}</span>
            <strong>{window.percentile === null ? "不可用" : `${window.percentile.toFixed(1)}%`}</strong>
          </div>
          {window.percentile === null ? <p className="valuation-reason">{window.unavailable_reason ?? "样本不足"}</p> : <>
            <div className="valuation-scale" aria-label={`当前值位于近 ${window.window_years} 年样本的 ${window.percentile.toFixed(1)}% 处`}>
              <i style={{ left: `${Math.min(100, Math.max(0, window.percentile))}%` }} />
            </div>
            <div className="valuation-scale-labels"><span>最低 {window.minimum?.toFixed(2)}</span><span>中位 {window.median?.toFixed(2)}</span><span>最高 {window.maximum?.toFixed(2)}</span></div>
            {/* **样本没铺满窗口时，这句话必须挨着那个数字。**
                寒武纪 2025-04 才转正、之前没有 PE，于是「近 3 年分位」和
                「近 5 年分位」是同一个 1.7% —— 背后是同一批 16 个月的样本。
                只把「样本 242 个」写在下面是不够的：读的人看的是加粗的那个百分比。 */}
            {/* 原来这里把后端那句完整的警告在每个窗口下面各印一遍 ——
                两段几乎一样的红字并排，第二段不带来任何新信息。
                标题已经改成真实跨度了，这里只留样本本身。 */}
            <p className="valuation-reason">样本 {window.sample_size} 个 · {window.sample_start} → {window.sample_end}</p>
          </>}
        </article>)}
      </div>
      {metric.history.length > 0 && <Suspense fallback={<div className="trend-loading">正在绘制估值序列…</div>}><ValuationTrend points={metric.history} label={metric.label} /></Suspense>}
      {/* **原因说一次，说在整块下面。** 每个窗口各印一遍的那两段红字，
          内容几乎相同（只差「不足 3 年」和「不足 5 年」两个字）。 */}
      {metric.windows.some((w) => w.coverage_note) && <p className="market-history-note market-history-note--warn">
        {metric.windows.find((w) => w.coverage_note)?.coverage_note?.split("——")[0]}
        　—— 上面那几个分位都只是这段样本内的位置，**不能当成 3 年或 5 年的历史位置来读**。
      </p>}
      <p className="market-history-note">
        分位 = 样本中不高于当前值的比例；样本为{valuation.source}近五年序列，亏损期的非正值已剔除并不参与排序。
        {valuation.local_snapshot_days > 0 && ` 本地另有 ${valuation.local_snapshot_days} 天自建行情快照（自 ${valuation.local_snapshot_start} 起），口径与实时行情一致，随每次同步累积。`}
      </p>
    </>}
  </section>;
}

function formatMetricValue(card: FinancialMetricCard): string {
  if (card.value === null) return "—";
  if (card.unit === "元") return formatBillion(card.value);
  if (card.unit === "天") return `${card.value.toFixed(1)} 天`;
  return `${card.value.toFixed(2)}%`;
}

/** 比率可以跨口径比；金额与周转天数按报告期长度缩放，非年报与年报不可直接相比。 */
function metricDelta(card: FinancialMetricCard, comparable: boolean): string | null {
  if (!comparable && card.unit !== "%") return "非年报，与年报口径不可直接相比";
  if (card.value === null || card.previous_annual === null) return null;
  const change = card.value - card.previous_annual;
  const unit = card.unit === "元" ? "" : card.unit === "天" ? " 天" : " 个百分点";
  const shown = card.unit === "元" ? formatBillion(Math.abs(change)) : Math.abs(change).toFixed(card.unit === "天" ? 1 : 2);
  return `较 ${card.previous_annual_date ?? "上一年报"} ${change >= 0 ? "+" : "−"}${shown}${unit}`;
}

function FinancialMetricsGrid({ financials }: { financials: FinancialSummary }) {
  const latest = financials.periods[financials.periods.length - 1];
  const latestIsAnnual = Boolean(latest?.report_date.endsWith("-12-31"));
  return <>
    {financials.warnings.length > 0 && <div className="finance-alerts" aria-label="财务提醒">
      {financials.warnings.map((warning) => <details key={warning.title} className={`finance-alert finance-alert--${warning.level === "缺口" ? "gap" : "note"}`}>
        <summary><span>{warning.level}</span><strong>{warning.title}</strong></summary>
        <p>{warning.detail}</p>
      </details>)}
    </div>}
    <details className="finance-deep-metrics">
      <summary>
        <span>深入指标</span>
        <strong>{financials.metrics.filter((card) => card.value !== null).length}/{financials.metrics.length} 项可用</strong>
      </summary>
      <div className="metric-cards">
        {financials.metrics.map((card) => <article key={card.key} title={card.basis}>
          <span>{card.label}</span>
          <strong>{formatMetricValue(card)}</strong>
          <em>{card.unavailable_reason ?? metricDelta(card, latestIsAnnual) ?? card.basis}</em>
        </article>)}
      </div>
      {latest && <p className="market-history-note">
        TTM：{latest.ttm_basis ?? "—"}
        {latest.revenue_ttm !== null && ` · 营收 ${formatBillion(latest.revenue_ttm)}`}
        {latest.net_profit_ttm !== null && ` · 归母净利润 ${formatBillion(latest.net_profit_ttm)}`}
      </p>}
    </details>
  </>;
}

function FinancialVitals({ financials, latest }: { financials: FinancialSummary; latest: FinancialPeriod }) {
  const roePeriod = [...financials.periods].reverse().find((period) => period.roe_estimate !== null) ?? null;
  const roeValue = roePeriod?.roe_estimate ?? financials.roe_reference_value;
  const roeDate = roePeriod?.report_date ?? financials.roe_reference_report_date;
  const items = [
    { key: "revenue", label: "营收", value: formatBillion(latest.revenue_ttm ?? latest.revenue), note: latest.revenue_ttm !== null ? "TTM" : "本报告期" },
    { key: "profit", label: "归母利润", value: formatBillion(latest.net_profit_ttm ?? latest.net_profit), note: latest.net_profit_ttm !== null ? "TTM" : "本报告期" },
    { key: "roe", label: "ROE", value: roeValue === null || roeValue === undefined ? "—" : `${roeValue.toFixed(1)}%`, note: roeDate ? `${roeDate.slice(0, 4)} 年报${roePeriod ? "估算" : " · 底座"}` : "年报待同步" },
    { key: "cash", label: "经营现金流", value: formatBillion(latest.operating_cash_flow), note: latest.cash_conversion === null ? "本期 · 现金含量待算" : `本期 · 现金含量 ${latest.cash_conversion.toFixed(0)}%` },
    { key: "debt", label: "资产负债率", value: latest.debt_ratio === null ? "—" : `${latest.debt_ratio.toFixed(1)}%`, note: latest.interest_debt_ratio === null ? "有息负债率待算" : `有息 ${latest.interest_debt_ratio.toFixed(1)}%` },
  ];
  return <div className="financial-vitals" aria-label={`截至 ${latest.report_date} 的经营体征`}>
    {items.map((item) => <article className={`financial-vital financial-vital--${item.key}`} key={item.key}>
      <span>{item.label}</span>
      <strong>{item.value}</strong>
      <em>{item.note}</em>
    </article>)}
  </div>;
}

function reportPeriodLabel(reportDate: string): string {
  const [year, month, day] = reportDate.slice(0, 10).split("-");
  if (month === "12" && day === "31") return `${year} 年报`;
  if (month === "06" && day === "30") return `${year} 中报`;
  if (month === "03" && day === "31") return `${year} Q1`;
  if (month === "09" && day === "30") return `${year} Q3`;
  return reportDate.slice(0, 10);
}

/** 只在法定披露窗口结束后才判“缺报告”，避免一进新季度就误报过期。 */
function expectedFinancialReportDate(moment = new Date()): string {
  const year = moment.getFullYear();
  const month = moment.getMonth() + 1;
  if (month <= 4) return `${year - 1}-09-30`;
  if (month <= 8) return `${year}-03-31`;
  if (month <= 10) return `${year}-06-30`;
  return `${year}-09-30`;
}

function FinancialFreshnessBadge({ financials }: { financials: FinancialSummary }) {
  const latest = financials.latest_report_date || financials.periods[financials.periods.length - 1]?.report_date || "";
  const expected = expectedFinancialReportDate();
  const stale = Boolean(latest && latest < expected);
  const refreshed = new Date(financials.refreshed_at);
  const ageDays = Number.isNaN(refreshed.getTime()) ? null : Math.max(0, Math.floor((Date.now() - refreshed.getTime()) / 86_400_000));
  const syncText = ageDays === null ? "同步时间未知" : ageDays === 0 ? "今天同步" : `${ageDays} 天前同步`;
  return <span
    className={`financial-freshness${stale ? " financial-freshness--stale" : ""}`}
    title={`${stale ? `按披露时点应至少覆盖到 ${reportPeriodLabel(expected)}` : "已覆盖当前应披露报告"} · ${syncText}`}
  ><i />{stale ? `缺 ${reportPeriodLabel(expected)}` : `财报到 ${reportPeriodLabel(latest)}`}</span>;
}

function FinancialFactsPanel({ company, refreshing, onRefresh }: { company: CompanyDetail; refreshing: boolean; onRefresh: () => void }) {
  const financials = company.financials;
  const latest = financials?.periods[financials.periods.length - 1] ?? null;
  return <section className="panel financial-facts-panel">
    <div className="panel-heading">
      <div><span className="eyebrow">已接入的定期报告</span><PanelTitle hint="ROE 为年报权益平均值的估算，不是披露值。">经营与财务趋势 <Source kind="财报" /></PanelTitle></div>
      <div className="financial-panel-actions">
        {financials && <FinancialFreshnessBadge financials={financials} />}
        <button className="page-action" onClick={onRefresh} disabled={refreshing}>{refreshing ? "正在同步财报…" : financials ? "更新财务数据" : "同步财务数据"}</button>
      </div>
    </div>
    {!financials || !latest ? <div className="market-history-empty">尚未同步财务报告。点击右上角，读取真实的利润表、现金流量表和资产负债表。</div> : <>
      <FinancialVitals financials={financials} latest={latest} />
      <FinancialMetricsGrid financials={financials} />
      {/* 原来这里是一张双轴五系列图（亿元和 % 共用一张）。双轴让人去比较两条
          不同量纲的线的交叉与起伏，而那个比较毫无意义。拆成两张单轴小图。 */}
      <Suspense fallback={<div className="trend-loading">正在绘制经营走势…</div>}>
        <GrowthChart periods={financials.periods} />
      </Suspense>
      <p className="market-history-note">{financials.source} · 最新报告期 {latest.report_date} · {latest.audit_status || "审计状态未提供"} · 同步于 {formatDateTime(financials.refreshed_at)}</p>
    </>}
  </section>;
}

const VERDICT_TONE: Record<string, string> = {
  有利: "good", 不利: "bad", 中性: "calm", 数据不足: "muted", 未体检: "muted",
};

const CATEGORY_LABEL: Record<string, string> = {
  find: "找什么", business: "生意好不好", price: "价格贵不贵", discipline: "怎么少犯错",
};

/**
 * 方法体检：这家公司在每个投资方法下读出来是什么样。
 *
 * **一行一个方法，默认折叠。** 第一版把结论、依据、缺口全摊开，八个方法排下来
 * 是一屏读不完的字墙——而这一页的用处恰恰是先快速扫一遍「哪几个方法说得上话」，
 * 再挑一两个细看。摊开的版本连这一步都做不到。
 *
 * **方法本身要跟着结论走。** 只给「先分类，再定预期 · 中性」这一行，看不出它在
 * 分哪几类、凭什么这么分，结论就成了无从判断的断言。展开时先显示方法自己的判据表。
 *
 * **一个方法一条逻辑。** 早先做成多选叠加，理由是方法库说「多数方法只覆盖一个
 * 侧面」——但实测叠出来的判断是一坨字，看不出哪句对应哪个方法、反证的阈值从哪来。
 * 看不懂还不如不给。
 */
const CompanyTimeline = lazy(() => import("./components/CompanyTimeline").then((m) => ({ default: m.CompanyTimeline })));

/**
 * 时间轴面板：一根轴回答「我买的时候估值在哪、之后发生了什么」。
 *
 * 放在「行情与估值」页签里而不是单开一页——它是估值走势的增强版，
 * 而不是另一件事。多一个页签，就多一次「该去哪儿看」的犹豫。
 */
function TimelinePanel({ companyId }: { companyId: number }) {
  const [data, setData] = useState<TimelinePayload | null>(null);
  const [years, setYears] = useState(2);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let alive = true;
    getTimeline(companyId, years)
      .then((d) => { if (alive) setData(d); })
      .catch((caught) => { if (alive) setError(errorMessage(caught)); });
    return () => { alive = false; };
  }, [companyId, years, round]);

  async function syncValuation() {
    setSyncing(true); setError("");
    try { await refreshCompanyValuation(companyId); setRound((n) => n + 1); }
    catch (caught) { setError(errorMessage(caught)); }
    finally { setSyncing(false); }
  }

  // 打底的那条线没有，整张图就是空的——公告、财报、买卖都没有纵坐标可落。
  const empty = data !== null && data.valuation.length === 0;

  return <section className="panel">
    <div className="panel-heading compact">
      <div>
        <span className="eyebrow">对齐同一根时间轴</span>
        <PanelTitle hint="估值走势打底，实质公告、财报期、你的买卖和写下判断的时点都落在同一条轴上。">发生了什么，以及当时估值在哪</PanelTitle>
      </div>
      <div className="chart-range-group" role="group" aria-label="时间范围">
        {[1, 2, 5].map((y) => <button key={y} type="button"
          className={`chart-range${years === y ? " chart-range--on" : ""}`}
          onClick={() => setYears(y)}>{y} 年</button>)}
      </div>
    </div>
    {error && <p className="form-error">{error}</p>}
    {/* **空图不能就那么空着。**
        历史估值来自「同步历史估值」，而那个按钮在这一页更下面的另一块面板里——
        于是新建的档案打开来是一张没有曲线的坐标系，看不出是没数据、还是坏了、
        还是该去点什么。缺什么就在缺的地方给入口。 */}
    {empty
      ? <div className="empty-state">
          <p><strong>还没有历史估值。</strong>这条轴以市盈率 TTM 打底，没有它，公告和买卖就没有纵坐标可落。</p>
          <button className="page-action" type="button" disabled={syncing} onClick={() => void syncValuation()}>
            {syncing ? "正在同步…" : "同步历史估值"}
          </button>
        </div>
      : data && <Suspense fallback={<div className="trend-loading">正在画时间轴…</div>}>
          <CompanyTimeline data={data} />
        </Suspense>}
    {data && <Boundary text={data.boundary} />}
    <EvidenceAxisPanel companyId={companyId} />
  </section>;
}

/**
 * 证据方向轴。跟上面那根时间轴同一块面板：一根回答"发生了什么"，
 * 一根回答"那些事对我的判断是好是坏"——分成两块页面的话，
 * 人得自己在两个滚动位置之间对时间。
 */
function EvidenceAxisPanel({ companyId }: { companyId: number }) {
  const [data, setData] = useState<EvidenceDirectionView | null>(null);
  const [plan, setPlan] = useState<EvidenceDirectionPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    let alive = true;
    setData(null); setPlan(null); setNote("");
    Promise.all([getEvidenceDirection(companyId), getEvidenceDirectionPlan(companyId)])
      .then(([view, cost]) => { if (alive) { setData(view); setPlan(cost); } })
      .catch((caught) => { if (alive) setError(errorMessage(caught)); });
    return () => { alive = false; };
  }, [companyId]);

  async function run() {
    setBusy(true); setError(""); setNote("");
    try {
      const result = await judgeEvidenceDirection(companyId);
      setNote(result.note);
      setData(await getEvidenceDirection(companyId));
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  }

  return <div className="axis-block">
    <div className="segment-head">
      <div>
        <h3>那些事，对我的判断是好是坏</h3>
        <p>方向是<strong>相对于你写下的那条判断</strong>说的，不是「对股价好不好」——同一件事对不同的判断方向可以相反。</p>
      </div>
      {/* 花钱的事，点之前就该看到大概多少，而不是点完看账单 */}
      {plan?.ready && <button className="page-action" onClick={() => void run()} disabled={busy}>
        {busy ? "正在判…" : `判一遍方向（${plan.events} 件，约 ${plan.credits} 积分）`}
      </button>}
    </div>
    {plan && !plan.ready && <div className="empty-state">{plan.note}</div>}
    {error && <p className="form-error">{error}</p>}
    {note && <p className="restore-message">{note}</p>}
    {plan?.ready && data && <Suspense fallback={<div className="trend-loading">正在画方向轴…</div>}>
      <EvidenceAxis data={data} />
    </Suspense>}
  </div>;
}

const AssessmentMatrix = lazy(() => import("./components/AssessmentMatrix").then((m) => ({ default: m.AssessmentMatrix })));

/**
 * 研究池 × 方法体检矩阵。
 *
 * 放在方法库页——那一页本来就在讲「有哪些方法」，接着告诉你「你的池子在这些方法下
 * 什么样」是自然的下一句。放进公司档案反而不对：那里是单家视角，看不出横向差异。
 */
/**
 * 同步作业成败条带：每个作业一行，最近 N 次是一排小方块。
 *
 * **列表看不出规律。** 同步记录按时间倒序排一屏，只看得到最近十几条属于哪个作业；
 * 而「实时行情快照连续失败 24 次」这种事，要把同一作业的历史排成一行才看得出来。
 * 实测就是这样发现的：那个作业因为一次半途失败的迁移留下了一列没删的字段，
 * 每次写入都撞非空约束——而在此之前，今天已经因为看不见它白查了三次别的地方。
 *
 * 从左到右是从旧到新，跟时间轴同向：反过来的话「最近变好了」会被读成「最近变差了」。
 */
function SyncStripPanel() {
  const [jobs, setJobs] = useState<SyncStripJob[] | null>(null);

  useEffect(() => {
    let alive = true;
    getSyncStrip().then((d) => { if (alive) setJobs(d); }).catch(() => { /* 不为它打断整页 */ });
    return () => { alive = false; };
  }, []);

  if (!jobs || jobs.every((j) => j.total === 0)) return null;
  const broken = jobs.filter((j) => j.total > 0 && j.failed / j.total > 0.5);

  return <section className="panel">
    <div className="panel-heading compact">
      <div>
        <span className="eyebrow">同步作业</span>
        <PanelTitle hint="每格一次运行，从左到右由旧到新。一整行都是空格，说明这个作业其实一直没跑对。">最近跑得怎么样</PanelTitle>
      </div>
    </div>

    {broken.length > 0 && <p className="form-error">
      {broken.map((j) => `${j.name} 最近 ${j.total} 次里失败 ${j.failed} 次`).join("；")}
    </p>}

    <div className="strip-list">
      {jobs.filter((j) => j.total > 0).map((job) => (
        <div className="strip-row" key={job.job_id}>
          <span className="strip-name">{job.name}<em>{job.category}</em></span>
          <span className="strip-cells">
            {job.runs.map((run, i) => (
              <i key={i}
                 className={`strip-cell strip-cell--${run.status === "成功" ? "ok" : run.status === "运行中" ? "run" : "bad"}`}
                 title={`${run.at}　${run.status}${run.note ? `\n${run.note}` : ""}`} />
            ))}
          </span>
          <span className="strip-count">{job.failed ? `${job.failed}/${job.total} 失败` : `${job.total} 次全好`}</span>
        </div>
      ))}
    </div>
  </section>;
}

function AssessmentMatrixPanel({ onOpenCompany }: { onOpenCompany: (id: number) => void }) {
  const [data, setData] = useState<{ rows: MatrixRow[]; assessed: number; boundary: string } | null>(null);

  useEffect(() => {
    let alive = true;
    getAssessmentMatrix()
      .then((d) => { if (alive) setData(d); })
      .catch(() => { /* 取不到就不显示这一块，别为它打断整页 */ });
    return () => { alive = false; };
  }, []);

  if (!data || data.assessed === 0) return null;

  return <section className="panel">
    <div className="panel-heading compact">
      <div>
        <span className="eyebrow">研究池 × 方法体检</span>
        <PanelTitle hint="一列看下来是「所有公司在这个方法下的表现」，一行看过去是「这家公司哪一类方法说得上好话」。">你的池子在这些方法下什么样</PanelTitle>
      </div>
    </div>
    <Suspense fallback={<div className="trend-loading">正在整理…</div>}>
      <AssessmentMatrix rows={data.rows} onOpenCompany={onOpenCompany} />
    </Suspense>
    <Boundary text={data.boundary} />
  </section>;
}

function AssessmentPanel({ companyId, onSaved }: { companyId: number; onSaved: () => Promise<void> }) {
  const [view, setView] = useState<AssessmentView | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [showManual, setShowManual] = useState(false);
  const [draftingKey, setDraftingKey] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getAssessment(companyId)
      .then((v) => { if (alive) setView(v); })
      .catch(() => { /* 读不到就当没体检过，别为它打断整页 */ });
    return () => { alive = false; };
  }, [companyId]);

  async function run() {
    setRunning(true); setError(""); setNotice("");
    try {
      const result = await runAssessment(companyId);
      setView(result);
      setNotice(`体检完成。${costText(result.billing) ?? ""}`);
    } catch (caught) { setError(errorMessage(caught)); } finally { setRunning(false); }
  }

  /**
   * 按一个方法写一条投资逻辑。
   *
   * **后台跑，而且直接落库。** 原先是「同步生成草稿 + 你再点保存」：生成要二十多秒，
   * 草稿只活在这个组件里，切一个页签回来就没了，得重新生成重新等——实测丢过一次。
   * 现在提交后台任务，切走也照跑，跑完直接写进「逻辑与证据」。
   *
   * 「草稿」这个中间态由投资逻辑自己的状态承担：新写的一律是「待观察」，
   * 不满意可以直接删掉。
   */
  async function draftOne(methodKey: string) {
    setDraftingKey(methodKey); setError(""); setNotice("");
    try {
      const job = await writeThesis(companyId, methodKey);
      setNotice(`${job.label}…　任务在服务端跑，切走页面回来还在。`);
      pollWrite(job.kind, job.target_id);
    } catch (caught) { setError(errorMessage(caught)); setDraftingKey(null); }
  }

  function pollWrite(kind: string, targetId: number) {
    const timer = window.setInterval(async () => {
      try {
        const job = await getJob(kind, targetId);
        if (!job || job.status === "运行中" || job.status === "排队中") return;
        window.clearInterval(timer);
        setDraftingKey(null);
        if (job.status === "失败") {
          setError(`写失败：${job.error}`);
        } else {
          setNotice("已写进「逻辑与证据」。以后公告和财报会照着这条反证条件提醒你。");
          await onSaved();
        }
      } catch {
        window.clearInterval(timer);
        setDraftingKey(null);
      }
    }, 2500);
  }

  const results = view?.results ?? [];
  const stale = results.some((r) => r.stale);
  const tally = results.reduce<Record<string, number>>((acc, r) => {
    acc[r.verdict] = (acc[r.verdict] ?? 0) + 1; return acc;
  }, {});

  return <section className="panel">
    <div className="panel-heading">
      <div>
        <span className="eyebrow">投资逻辑方法库 · 模型代读</span>
        <PanelTitle hint="这家公司放进每个方法里读出来是什么样。挑一个说得上话的方法，用它写你的判断。">方法体检</PanelTitle>
      </div>
      <button className="page-action" onClick={() => void run()} disabled={running}>
        {running ? "正在体检…（约 25 秒）" : view?.checked ? "重新体检" : "开始体检"}
      </button>
    </div>

    {error && <p className="form-error">{error}</p>}
    {notice && <p className="restore-message">{notice}</p>}
    {stale && <p className="market-history-note">财报或估值已更新，下面是按旧数据算的，重跑一次才准。</p>}

    {!view?.checked && !running && <div className="empty-state">
      还没体检过。点右上角，八个方法各跑一遍，告诉你哪个说得上话、还缺什么。
    </div>}

    {view?.checked && <>
      <div className="assess-tally">
        {["有利", "中性", "不利", "数据不足"].map((v) => tally[v] ? (
          <span key={v} className={`assess-chip assess-chip--${VERDICT_TONE[v]}`}>{v} {tally[v]}</span>
        ) : null)}
      </div>

      <div className="assess-list">
        {results.map((item) => {
          const on = open === item.method_key;
          return <article className={`assess-row${on ? " assess-row--open" : ""}`} key={item.method_key}>
            <button className="assess-row-head assess-row-head--company" onClick={() => setOpen(on ? null : item.method_key)}
                    aria-expanded={on}>
              <span className={`assess-chip assess-chip--${VERDICT_TONE[item.verdict] ?? "calm"}`}>{item.verdict}</span>
              <span className="assess-name">
                <strong>{item.method_name}</strong>
                <em>{CATEGORY_LABEL[item.category] ?? item.category}</em>
              </span>
              <span className="assess-summary-wrap assess-summary-wrap--company">
                <span className="assess-summary">{item.summary || "—"}</span>
                <ChevronDown size={15} className={on ? "assess-caret assess-caret--on" : "assess-caret"} />
              </span>
            </button>

            {on && <div className="assess-body">
              <div className="assess-block">
                <h4>这个方法在问什么</h4>
                <p>{item.core_question}</p>
                {item.steps.length > 0 && <ol className="assess-steps">
                  {item.steps.map((step, i) => <li key={i}>{step}</li>)}
                </ol>}
                {item.caution && <p className="assess-caution">盲区：{item.caution}</p>}
              </div>

              {item.evidence.length > 0 && <div className="assess-block">
                <h4>依据</h4>
                <table className="assess-evidence">
                  <tbody>
                    {item.evidence.map((e, i) => <tr key={i}>
                      <th scope="row">{e.fact}</th>
                      <td>{e.value || "—"}</td>
                      <td><em>{e.as_of}</em></td>
                    </tr>)}
                  </tbody>
                </table>
              </div>}

              {item.gaps.length > 0 && <div className="assess-block">
                <h4>还缺什么</h4>
                <ul className="assess-gaps">{item.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
              </div>}

              <button className="page-action" disabled={draftingKey !== null}
                      onClick={() => void draftOne(item.method_key)}>
                {draftingKey === item.method_key ? "正在写…（约 25 秒，可切走）" : `用「${item.method_name}」写一条投资逻辑`}
              </button>
            </div>}
          </article>;
        })}
      </div>
    </>}

    {view && <div className="manual-methods">
      <button className="text-button" onClick={() => setShowManual(!showManual)}>
        {showManual ? "收起" : `还有 ${view.manual.length} 个方法只有你自己能做`}
      </button>
      {showManual && <>
        <p className="market-history-note">
          这几个的判据在你身上——模型替你做只会做出一段像模像样的空话。
        </p>
        <div className="assess-list">
          {view.manual.map((m) => <article className="assess-row" key={m.method_key}>
            <div className="assess-row-head assess-row-head--static">
              <span className="assess-chip assess-chip--muted">待你做</span>
              <span className="assess-name"><strong>{m.method_name}</strong>
                <em>{CATEGORY_LABEL[m.category] ?? m.category}</em></span>
              <span className="assess-summary">{m.core_question}</span>
            </div>
          </article>)}
        </div>
      </>}
    </div>}

    {view && <Boundary text={view.boundary} />}
  </section>;
}

/**
 * 一条投资逻辑的分块渲染。
 *
 * **优先用结构，取不到才回落到平文本。** 老数据（和还没重新起草的逻辑）只有两坨
 * 长文本；新起草的带 structure，判断一句话、依据成条、反证是「盯什么→什么阈值→
 * 意味着什么」的清单。反证写成一段话就没法逐条核对，等于没写。
 */
function ThesisBlocks({ structure, claim, counter, review }: {
  structure?: ThesisStructure | null; claim: string; counter: string; review: string;
}) {
  const s = structure && structure.headline ? structure : null;
  // 没有 structure 的（老数据、手写的）：claim 是一段用「；」连起来的话，
  // 第一段是判断本身，后面是依据——照样拆开，第一句才立得住。
  const fallbackRest = s ? [] : thesisRest(claim);
  return <>
    <div className="assess-block">
      <h4>判断</h4>
      <p className="thesis-headline">{s ? s.headline : thesisHeadline(claim)}</p>
      {s && s.basis.length > 0 && <ul className="assess-steps">
        {s.basis.map((b, i) => <li key={i}>
          {b.point}
          {b.evidence && <span className="thesis-evidence">{b.evidence}{b.as_of ? ` · ${b.as_of}` : ""}</span>}
        </li>)}
      </ul>}
      {fallbackRest.length > 0 && <ul className="assess-steps">
        {fallbackRest.map((part, i) => <li key={i}>{part}</li>)}
      </ul>}
    </div>

    <div className="assess-block">
      {/* 副标题单独一行。挤在标题后面的话，窄一点就撞成「—一它以后真正能提醒你的地方」
          ——实测截图里就是这样。 */}
      <h4>反证条件</h4>
      <p className="assess-hint">它以后真正能提醒你的地方</p>
      {s && s.counters.length > 0
        ? <ol className="thesis-counters">
            {s.counters.map((c, i) => <li key={i}>
              <strong>{c.metric || "触发条件"}</strong>
              <span>{c.threshold}</span>
              {c.means && <em>{c.means}</em>}
            </li>)}
          </ol>
        : <ul className="assess-counters">{splitClauses(counter).map((c, i) => <li key={i}>{c}</li>)}</ul>}
    </div>

    <div className="assess-block">
      <h4>复核触发</h4>
      {s && (s.review.when || s.review.what.length > 0)
        ? <><p>{s.review.when}</p>
            {s.review.what.length > 0 && <ul className="assess-steps">
              {s.review.what.map((w, i) => <li key={i}>{w}</li>)}
            </ul>}</>
        : <p>{review}</p>}
    </div>
  </>;
}

/**
 * 已存逻辑的 claim 是一段用「；」连起来的话（起草时由结构拍平而成）。
 * 第一段是判断本身，后面几段是依据——拆开显示，第一句才立得住。
 * 拆不出来（老数据、手写的）就整段当标题，不硬切。
 */
function thesisHeadline(claim: string): string {
  const parts = String(claim || "").split("；");
  return parts[0] || claim;
}

type DetailTab = "brief" | "market" | "finance" | "ledger" | "research" | "chain";

const DETAIL_TABS: DetailTab[] = ["brief", "market", "finance", "ledger", "research", "chain"];

function tabFromSearch(): DetailTab {
  const value = new URLSearchParams(window.location.search).get("tab");
  if (DETAIL_TABS.includes(value as DetailTab)) return value as DetailTab;
  // 旧链接继续可用：合并页签后，不让收藏的公司档案链接落到空页面。
  const legacy: Record<string, DetailTab> = {
    value: "market",
    method: "ledger",
    events: "research",
    reports: "chain",
  };
  return (value && legacy[value]) || "brief";
}

// onOpenCompany 去掉了：它以前只传给同业对照，而那张表现在比的是全市场同行，
// 绝大多数并不在研究池里，点开也没有档案可看。
function CompanyDetailPage({ companyId, onBack, onArchiveChanged }: { companyId: number; onBack: () => void; onArchiveChanged: () => Promise<void> }) {
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [marketRefreshing, setMarketRefreshing] = useState(false);
  const [financialRefreshing, setFinancialRefreshing] = useState(false);
  const [profileRefreshing, setProfileRefreshing] = useState(false);
  const [valuationRefreshing, setValuationRefreshing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  // 从方法库带模板过来时，直接把新建逻辑的表单打开，省掉一次找按钮
  const [composer, setComposer] = useState<Composer>(hasThesisDraft() ? "thesis" : null);
  const [editingThesis, setEditingThesis] = useState<number | null>(null);
  // 反方建议的反证条件：**只是初值**，交给修订表单，改不改是你的事。
  const [suggestedCounter, setSuggestedCounter] = useState("");
  const [tab, setTab] = useState<DetailTab>(() => (hasThesisDraft() ? "research" : tabFromSearch()));
  function selectTab(next: DetailTab) {
    setTab(next);
    const url = new URL(window.location.href);
    if (next === "brief") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next);
    window.history.replaceState({}, "", `${url.pathname}${url.search}`);
  }
  useEffect(() => {
    const handlePop = () => setTab(tabFromSearch());
    window.addEventListener("popstate", handlePop);
    return () => window.removeEventListener("popstate", handlePop);
  }, []);
  async function refresh() { setLoading(true); try { setCompany(await getCompany(companyId)); setError(""); } catch (caught) { setError(errorMessage(caught)); } finally { setLoading(false); } }
  useEffect(() => { void refresh(); }, [companyId]);
  async function saved() { await refresh(); await onArchiveChanged(); }
  async function refreshHistory() { setMarketRefreshing(true); try { await refreshCompanyMarketHistory(companyId); await refresh(); } catch (caught) { setError(errorMessage(caught)); } finally { setMarketRefreshing(false); } }
  async function refreshProfile() { setProfileRefreshing(true); try { await refreshCompanyProfile(companyId); await refresh(); } catch (caught) { setError(errorMessage(caught)); } finally { setProfileRefreshing(false); } }
  async function refreshValuation() { setValuationRefreshing(true); try { await refreshCompanyValuation(companyId); await refresh(); } catch (caught) { setError(errorMessage(caught)); } finally { setValuationRefreshing(false); } }
  async function refreshFinancials() { setFinancialRefreshing(true); try { await refreshCompanyFinancials(companyId); await refresh(); } catch (caught) { setError(errorMessage(caught)); } finally { setFinancialRefreshing(false); } }
  async function copyArchiveLink() { try { await navigator.clipboard.writeText(window.location.href); setCopied(true); window.setTimeout(() => setCopied(false), 1800); } catch { setError("未能复制链接，请从浏览器地址栏复制。"); } }
  /**
   * 删掉一条投资逻辑。
   *
   * **之前只能加不能减。** 模型起草必然会产生一些不满意的版本，没有删除就只能
   * 标成「已破坏」压在列表里——而那个状态本来的意思是「事实推翻了它」，
   * 不是「我不要这条」。两件事混在一起，列表很快就没法看。
   *
   * 证据和事件不跟着删：它们是已经发生的事实，不因为某条判断被丢掉而失效。
   */
  async function removeThesis(thesisId: number, claim: string) {
    if (!(await confirmAction({
      title: `删掉这条投资逻辑？「${claim.slice(0, 40)}…」`,
      detail: "它的证据和事件会保留——那些是已经发生的事实。",
      confirmText: "删掉这条逻辑", danger: true,
    }))) return;
    try {
      await deleteThesis(thesisId);
      await saved();
    } catch (caught) { setError(errorMessage(caught)); }
  }

  async function changeStatus(thesisId: number, status: ThesisStatus) { try { await updateThesis(thesisId, status); await saved(); } catch (caught) { setError(errorMessage(caught)); } }
  async function changeVerification(eventId: number, verification: string) { try { await updateResearchEvent(eventId, verification); await saved(); } catch (caught) { setError(errorMessage(caught)); } }
  if (loading) return <div className="empty-state page-loading">正在打开公司档案…</div>;
  if (!company) return <div className="empty-state page-loading">{error || "未找到该公司档案。"}<button className="text-button" onClick={onBack}>返回公司档案</button></div>;
  const counterEvidenceCount = company.theses.reduce((total, thesis) => total + thesis.counter_evidence_count, 0);
  const thesisAttentionCount = company.theses.filter((thesis) => thesis.status === "challenged" || thesis.status === "broken").length;
  const tabs: Array<{ key: DetailTab; label: string; hint: string }> = [
    { key: "brief", label: "公司概况", hint: "操盘摘要、公开资料与大事提醒" },
    { key: "market", label: "行情与估值", hint: "价格、区间表现与估值分位" },
    { key: "finance", label: "财务与行业", hint: "定期报告、经营指标与同业对照" },
    { key: "ledger", label: "持仓与方法", hint: "买卖流水、成本与方法体检" },
    { key: "research", label: "逻辑与证据", hint: "投资主张、反证条件与证据" },
    { key: "chain", label: "经营关系与报告", hint: "链上位置、经营关系线索与研究报告" },
  ];
  return <>
    {/* **公司页的舱头。**
     *
     * 这一块套上 `.deck` 之后，公司档案跟「今天」「找票」是同一个视觉世界了 ——
     * 那两页开场就是这块深色屏幕，而公司档案原来开场是白底加一条绿下划线。
     * 使用者的说法是「几个页面使用的白绿配色也与今天、找票用的黑红配色有点不搭」。
     *
     * 名字、代码、行情、页签包在一层里，是因为它们本来就是一件事：**你在看哪家公司**。
     * 两个兄弟元素各自涂成深色再假装拼成一张卡太脆（圆角、边框、缝隙三处都要对齐，
     * 改任何一处都会露缝），包一层是诚实的结构。 */}
    <div className="detail-deck deck">
      <section className="detail-hero">
        <button className="back-link" onClick={onBack}><ArrowLeft size={14} />公司档案</button>
        {/* **一行。** 原来是「分组·代码」一行 + 公司名一行 + 「交易所·行业·研究缘起」一行
            + 右边一张行情卡，加上下面两排大页签，红框那半屏就没了。
            名字、代码、价格是同一件事的三个字段，摆成一行就够。 */}
        <div className="detail-heading">
          <h1>{company.name}</h1>
          <code className="detail-code">{company.symbol}</code>
          <span className="detail-facts">{company.exchange} · {company.industry}</span>
          <span className="detail-quote">
            {company.latest_price === null ? "行情未同步" : `¥ ${company.latest_price.toFixed(2)}`}
            {company.change_percent !== null && <em className={company.change_percent < 0 ? "quote-down" : "quote-up"}>
              {company.change_percent > 0 ? "+" : ""}{company.change_percent.toFixed(2)}%
            </em>}
          </span>
          <button className="archive-link" onClick={() => void copyArchiveLink()}>
            <Link2 size={12} />{copied ? "已复制" : "复制链接"}
          </button>
        </div>
      </section>
      {/* 页签一条，不是十个大方块。**说明进 title**——十行说明常驻在那儿，
          而你每次只会点其中一个。 */}
      <nav className="detail-tabs" role="tablist" aria-label="档案分区">
        {tabs.map((item) => <button
          key={item.key}
          role="tab"
          aria-selected={tab === item.key}
          title={item.hint}
          className={`detail-tab${tab === item.key ? " detail-tab--on" : ""}`}
          onClick={() => selectTab(item.key)}
        >{item.label}</button>)}
      </nav>
      {/* **研究状态收进舱里，当仪表行。**
       *
       * 它原来是舱头下面单独一条：浅色主题里就是**一条白尾巴挂在深色舱头下面**，
       * 而且左缘还有一条 4px 品牌绿 —— 它不是动作，不该是绿的。
       *
       * 而它说的事跟上面完全一样：你在看哪家公司、这家公司的研究到哪一步了。
       * 首页驾驶舱本来就是这个结构（舱头 + 一行信标），照它做。 */}
      <ResearchSummary
        className="research-summary--company"
        eyebrow="研究状态"
        title={company.theses.length > 0 ? `${company.theses.length} 条长期判断` : "还没有长期判断"}
        items={[
          { label: "需留意", value: thesisAttentionCount, tone: thesisAttentionCount > 0 ? "risk" : "good" },
          { label: "反证", value: counterEvidenceCount, tone: counterEvidenceCount > 0 ? "warn" : "neutral" },
          { label: "证据", value: company.evidences.length, tone: company.evidences.length > 0 ? "accent" : "neutral" },
          { label: "事件", value: company.events.length },
        ]}
      />
    </div>
    {error && <p className="form-error">{error}</p>}{tab === "brief" && <><CompanyBriefPanel company={company} refreshing={profileRefreshing} onRefresh={() => void refreshProfile()} onSaved={saved} />
      {/* 紧挨着「大事提醒」：两者是**同一批原料**（这家公司的公告）。
          区别是大事提醒问「刚发生了什么」，承诺台账问「以前说过的话，到期了吗」。 */}
      <section className="panel">
        <div className="panel-heading"><div>
          <span className="eyebrow">承诺台账</span>
          <PanelTitle hint="公司说过的、能被证伪的话记下来，到期顶到你面前。">管理层说过的话</PanelTitle>
        </div></div>
        <Suspense fallback={<div className="empty-state">正在读台账…</div>}>
          <Promises companyId={company.id} />
        </Suspense>
      </section>
      {/* **紧跟着台账，因为它就是台账的另一种读法。**
          台账回答「说过哪些话」，这张甘特图回答「还有多久，以及会不会撞在一起」——
          一批解禁跟一条回购承诺同时到期，是一件跟"分别有这两件事"完全不同的事，
          而列表说不出这个。

          ⚠️ 这一块必须待在 `tab === "brief"` 里面。上一次加面板时
          `</>}` 提前收了分支，于是每一个页签底下都挂了一张桑基图。
          `lib/tabplacement.test.ts` 盯着这件事。 */}
      <section className="panel">
        <div className="panel-heading"><div>
          <span className="eyebrow">日程</span>
          <PanelTitle hint="承诺是「说出口那天 → 期限」，解禁是「公告那天 → 解禁日」。两种都是一段时间，所以能排到同一根轴上。">还有哪些日子在等着</PanelTitle>
        </div></div>
        <Suspense fallback={<div className="empty-state">正在排…</div>}>
          <SchedulePanel companyId={company.id} />
        </Suspense>
      </section></>}
    {tab === "market" && <><TimelinePanel companyId={company.id} /><MarketFactsPanel company={company} refreshing={marketRefreshing} onRefresh={() => void refreshHistory()} /><ValuationPanel company={company} refreshing={valuationRefreshing} onRefresh={() => void refreshValuation()} /><details className="company-subpanel"><summary><span>我的估值</span><em>把假设换算成三种情景</em></summary><Suspense fallback={<div className="empty-state">正在加载估值模型…</div>}><ValuationScenarios companyId={company.id} /></Suspense></details></>}
    {tab === "finance" && <><FinancialFactsPanel company={company} refreshing={financialRefreshing} onRefresh={() => void refreshFinancials()} />
      {/* **不另开一个标签页。** 这就是财务的一部分——只不过通用财务表回答的是
          「它赚了多少」，而这几条回答「这门生意该盯什么」。分成两个标签页，
          你就永远只会看第一个。 */}
      <section className="panel">
        <div className="panel-heading"><div>
          <span className="eyebrow">行业专属指标</span>
          <PanelTitle hint="白酒该看合同负债、银行该看拨贷比——通用指标说不出这些。">这门生意该盯的数</PanelTitle>
        </div></div>
        <Suspense fallback={<div className="empty-state">正在算…</div>}>
          <IndustryMetrics companyId={company.id} />
        </Suspense>
      </section>
      {/* **放在通用财务表和行业指标之间。** 前者回答「它赚了多少」、
          后者回答「这门生意该盯什么」，而这一张回答的是「赚到的钱去了哪」——
          三个问题，同一批报表，摊在同一个页签下才连得起来。

          ⚠️ 上面这句是意图，而代码一度是反的：`</section></>}` 提前收了
          `tab === "finance"`，这一整块落在条件外面，于是**每一个页签上都画一张
          桑基图**（写下判断、待办复核、产业链……）。注释说得对，代码做反了 ——
          加一块的时候只顾着往下写，没看自己插进了哪一层括号里。
          `test_money_flow_lives_on_one_tab` 现在盯着这件事。 */}
      <section className="panel">
        <div className="panel-heading"><div>
          <span className="eyebrow">钱的流向</span>
          <PanelTitle hint="每一根流量都对应年报上的一个科目，停上去能看到科目原名。标着「倒算」的那几根是减出来的，不是报表数据。">钱从哪来，去了哪</PanelTitle>
        </div></div>
        <Suspense fallback={<div className="empty-state">正在算…</div>}>
          <MoneyFlowPanel companyId={company.id} />
        </Suspense>
      </section>
      <PeerComparisonPanel company={company} /></>}
    {tab === "ledger" && <><LedgerFactsPanel company={company} onSaved={saved} /><AssessmentPanel companyId={company.id} onSaved={saved} /></>}
    {tab === "research" && <><div className="detail-grid"><section className="panel research-section"><div className="panel-heading"><div><span className="eyebrow">命题与反证</span><h2>投资逻辑</h2></div><button className="page-action" onClick={() => setComposer(composer === "thesis" ? null : "thesis")}><Plus size={14} />新建逻辑</button></div>{composer === "thesis" && <ThesisForm companyId={company.id} onSaved={saved} onCancel={() => setComposer(null)} />}<div className="research-list">{company.theses.length === 0 && <div className="empty-state">还没有逻辑。先写下你愿意被事实检验的一句话主张。</div>}{company.theses.map((thesis) => <article className="thesis-card" key={thesis.id}><div className="thesis-card-head"><select className={`thesis-status thesis-status--${thesis.status}`} aria-label="这条逻辑现在算不算数" value={thesis.status} onChange={(event) => void changeStatus(thesis.id, event.target.value as ThesisStatus)}><option value="intact">成立</option><option value="watching">待观察</option><option value="challenged">受挑战</option><option value="broken">已破坏</option></select></div><ThesisBlocks claim={thesis.claim} counter={thesis.counter_condition} review={thesis.next_review_trigger} /><footer><span>支持 {thesis.evidence_count} · 反证 {thesis.counter_evidence_count}</span></footer><div className="revision-actions"><button className="text-button" onClick={() => setEditingThesis(editingThesis === thesis.id ? null : thesis.id)}>{editingThesis === thesis.id ? "取消修订" : "修订这条逻辑"}</button><RevisionHistory entity="theses" entityId={thesis.id} count={thesis.revision_count} /><button className="text-button text-button--danger" onClick={() => void removeThesis(thesis.id, thesis.claim)}>删除</button></div>{editingThesis === thesis.id && <ThesisReviseForm thesis={thesis} onSaved={saved} onCancel={() => { setEditingThesis(null); setSuggestedCounter(""); }} suggestedCounter={suggestedCounter || undefined} />}</article>)}</div></section><section className="panel research-section"><div className="panel-heading"><div><span className="eyebrow">可追溯事实</span><h2>证据档案</h2></div><button className="page-action" onClick={() => setComposer(composer === "evidence" ? null : "evidence")}><Plus size={14} />归档证据</button></div>{composer === "evidence" && <EvidenceForm company={company} onSaved={saved} onCancel={() => setComposer(null)} />}<div className="research-list">{company.evidences.length === 0 && <div className="empty-state">还没有证据。公告、财报、访谈或手工观察都可以先归档。</div>}{company.evidences.map((evidence) => <article className={`evidence-card evidence-card--${evidence.polarity}`} key={evidence.id}><div><span>{evidence.source_name}</span><em>{evidence.verification}</em></div><p>{evidence.excerpt}</p><footer>{evidence.source_url ? <a href={evidence.source_url} target="_blank" rel="noreferrer">打开来源</a> : <span>未附来源链接</span>}<time>{formatDateTime(evidence.occurred_at)}</time></footer></article>)}</div></section></div>
      <section className="panel research-section events-section">
        <div className="panel-heading"><div><span className="eyebrow">等待判断的变化</span><h2>事件记录</h2></div><button className="page-action" onClick={() => setComposer(composer === "event" ? null : "event")}><Plus size={14} />记录事件</button></div>
        {composer === "event" && <EventForm company={company} onSaved={saved} onCancel={() => setComposer(null)} />}
        <div className="event-archive">
          {company.events.length === 0 && <div className="empty-state">还没有事件记录。</div>}
          {company.events.map((event) => <article className="archive-event" key={event.id}>
            <div className={`event-pin event-pin--${event.importance}`} aria-hidden="true" />
            <div><span>{event.category} · {formatDateTime(event.occurred_at)}</span><h3>{event.title}</h3></div>
            <select aria-label="更新事件核验状态" value={event.verification} onChange={(change) => void changeVerification(event.id, change.target.value)}>
              <option value="待核验">待核验</option><option value="待交叉核验">待交叉核验</option><option value="已核验">已核验</option><option value="已归档">已归档</option>
            </select>
          </article>)}
        </div>
      </section>
      {/* **反方比荐股有价值十倍。** 一个附和你的 Agent 只会把确信度往上推一格，
          而你已经买了、已经写了逻辑，最缺的恰恰是认真的反面意见。
          放在逻辑与证据下面：它反驳的就是上面那些东西。 */}
      <section className="panel advocate-panel">
        <div className="panel-heading"><div>
          <span className="eyebrow">对抗式复核 · 只读建议</span>
          <h2 id="advocate">让它反驳我</h2>
        </div></div>
        <Suspense fallback={<div className="empty-state">正在加载…</div>}>
          <Advocate companyId={company.id} theses={company.theses}
            onRevise={(thesisId, text) => { setSuggestedCounter(text); setEditingThesis(thesisId); }} />
        </Suspense>
      </section>
      {/* **读文档的快捷入口放在证据档案这一屏。**
          读完的回答一键存成证据，而证据档案就在上面 —— 一屏之内闭环。
          放在别的页签的话，"读完 → 存下来 → 看见它"要跨两次页签，
          而中间那一跳正是最容易丢掉的一步。 */}
      <section className="panel">
        <div className="panel-heading"><div><span className="eyebrow">读文档</span>
          <PanelTitle hint="上传或贴链接读一份年报、公告、研报；问它问题，回答带页码，可以一键存成这家公司的证据。">读一份文件，问它</PanelTitle>
        </div></div>
        <Suspense fallback={<div className="empty-state">正在加载…</div>}>
          <Documents companyId={company.id} />
        </Suspense>
      </section></>}
    {tab === "chain" && <><Suspense fallback={<div className="empty-state">正在读取链上位置…</div>}><CompanyChainPositions companyId={company.id} /></Suspense><BusinessRelationshipClues fixedCompanyId={company.id} /><ReportsPage fixedCompanyId={company.id} onOpenCompany={() => undefined} /></>}
  </>;
}

/** 还有哪些日子在等着：承诺与解禁排成甘特图。 */
function SchedulePanel({ companyId }: { companyId: number }) {
  const [view, setView] = useState<ScheduleView | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setView(null); setError("");
    getSchedule(companyId)
      .then((next) => { if (live) setView(next); })
      .catch((caught) => { if (live) setError(errorMessage(caught)); });
    return () => { live = false; };
  }, [companyId]);
  if (error) return <p className="form-error">{error}</p>;
  if (!view) return <div className="empty-state">正在排…</div>;
  return <Schedule view={view} />;
}

function MoneyFlowPanel({ companyId }: { companyId: number }) {
  const [view, setView] = useState<MoneyFlowView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // **选中的期跟着公司一起记。** 只存一个日期字符串的话，换公司那一下会先带着
  // 上一家的期发一次请求（后端认不出就退回默认，于是图闪一下才回到对的期）。
  // 把公司 id 存在一起，换公司时"当前选择"自然失效，一次多余的请求都没有。
  const [picked, setPicked] = useState<{ id: number; date: string }>({ id: companyId, date: "" });
  const [yearsOpen, setYearsOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  // 取一次分部附注，然后重画。**别让人跨页签去找那个按钮** —— 那块面板在产业链
  // 页签里，使用者的原话是「哪里有这个按钮？我就没看到」。
  const [reloads, setReloads] = useState(0);
  async function syncSegments() {
    setSyncing(true); setError("");
    try { await refreshSegments(companyId); setReloads((n) => n + 1); }
    catch (caught) { setError(errorMessage(caught)); }
    finally { setSyncing(false); }
  }
  const date = picked.id === companyId ? picked.date : "";

  useEffect(() => {
    let live = true;
    setError(""); setBusy(true);
    getMoneyFlow(companyId, date || undefined)
      .then((next) => { if (live) setView(next); })
      .catch((caught) => { if (live) setError(errorMessage(caught)); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [companyId, date, reloads]);

  if (error) return <p className="form-error">{error}</p>;
  if (!view) return <div className="empty-state">正在算…</div>;

  const periods = view.periods ?? [];
  const current = view.report_date ?? "";
  const allYears = [...new Set(periods.map((p) => p.report_date.slice(0, 4)))];
  // **默认只摆最近十二年。** 格力有 34 年，铺开是两整行按钮，比图本身还占地方，
  // 而看年报流向极少要翻到 1993。**但也不能悄悄砍掉** —— 砍掉的部分要在按钮上
  // 报出数目，点一下全出来（选中的那年在更早的区间里时也自动展开）。
  const RECENT = 12;
  const older = allYears.slice(RECENT);
  const showAll = yearsOpen || older.includes(current.slice(0, 4));
  const years = showAll ? allYears : allYears.slice(0, RECENT);
  const inYear = periods.filter((p) => p.report_date.startsWith(current.slice(0, 4)));
  const pick = (report_date: string) => setPicked({ id: companyId, date: report_date });
  // 点年份落到那一年的年报；那一年只出过季报（今年）就落到最新的一期。
  const pickYear = (year: string) => {
    const rows = periods.filter((p) => p.report_date.startsWith(year));
    pick((rows.find((p) => p.annual) ?? rows[0]).report_date);
  };

  return <>
    {periods.length > 1 && <div className="money-flow-periods">
      <div className="chart-range-group" role="group" aria-label="年份">
        {years.map((year) => <button key={year} type="button" disabled={busy}
          className={`chart-range${year === current.slice(0, 4) ? " chart-range--on" : ""}`}
          onClick={() => pickYear(year)}>{year}</button>)}
        {!showAll && older.length > 0 && <button type="button" className="text-button"
          onClick={() => setYearsOpen(true)}>更早的 {older.length} 年</button>}
      </div>
      {/* 只有一期的年份不摆第二行 —— 一个孤零零的「年报」按钮点了什么也不会变。 */}
      {inYear.length > 1 && <div className="chart-range-group" role="group" aria-label="报告期">
        {inYear.map((p) => <button key={p.report_date} type="button" disabled={busy}
          className={`chart-range${p.report_date === current ? " chart-range--on" : ""}`}
          onClick={() => pick(p.report_date)}>{p.label.slice(5)}</button>)}
      </div>}
    </div>}
    <MoneyFlow view={view} onSyncSegments={() => void syncSegments()} syncing={syncing} />
  </>;
}

function InboxArchiveForm({ item, onDone, onCancel }: { item: InboxItem; onDone: () => Promise<void>; onCancel: () => void }) {
  const [target, setTarget] = useState<"evidence" | "event">("evidence");
  const [theses, setTheses] = useState<ThesisRecord[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    getCompany(item.company_id).then((company) => { if (current) setTheses(company.theses); }).catch(() => undefined);
    return () => { current = false; };
  }, [item.company_id]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError("");
    const form = new FormData(event.currentTarget);
    const thesisId = String(form.get("thesis_id") ?? "");
    try {
      await archiveInboxItem(item.id, {
        target,
        thesis_id: thesisId ? Number(thesisId) : null,
        polarity: String(form.get("polarity") ?? "neutral") as EvidencePolarity,
        importance: String(form.get("importance") ?? "medium") as EventImportance,
        verification: String(form.get("verification") ?? "已核验"),
        note: String(form.get("note") ?? ""),
      });
      await onDone();
      onCancel();
    } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); }
  }
  return <form className="inline-form" onSubmit={submit}>
    <div className="chart-range-group" role="group" aria-label="选择归档类型">
      <button type="button" className={`chart-range${target === "evidence" ? " chart-range--on" : ""}`} onClick={() => setTarget("evidence")}>归档为证据</button>
      <button type="button" className={`chart-range${target === "event" ? " chart-range--on" : ""}`} onClick={() => setTarget("event")}>归档为事件</button>
    </div>
    <div className="form-grid compact-grid">
      <label>关联投资逻辑<select name="thesis_id" defaultValue=""><option value="">暂不关联</option>{theses.map((thesis) => <option value={thesis.id} key={thesis.id}>{thesis.claim.slice(0, 26)}{thesis.claim.length > 26 ? "…" : ""}</option>)}</select></label>
      {target === "evidence"
        ? <label>对逻辑的作用<select name="polarity" defaultValue="neutral"><option value="support">支持</option><option value="counter">反证</option><option value="neutral">中性</option></select></label>
        : <label>重要程度<select name="importance" defaultValue="medium"><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label>}
      <label>核验状态<input name="verification" defaultValue="已核验" required /></label>
    </div>
    <label>{target === "evidence" ? "摘录（默认用公告标题，可改成你读到的关键事实）" : "事件描述（默认用公告标题）"}
      <textarea name="note" rows={2} defaultValue={item.title} />
    </label>
    {error && <p className="form-error">{error}</p>}
    <div className="form-actions"><button className="page-action" type="submit" disabled={saving}>{saving ? "正在归档…" : "确认归档"}</button><button className="text-button" type="button" onClick={onCancel}>取消</button></div>
    <p className="form-note">归档会把公告的原文链接与披露日期一并带入{target === "evidence" ? "证据" : "事件"}；是否影响投资逻辑由你判断，系统不会自动认定。</p>
  </form>;
}

/** 收件箱一次最多列多少条。**跟后端的 `le=200` 对齐** —— 超了会 422。 */
const INBOX_MAX = 200;

function InboxCard({ item, onOpenCompany, onChanged }: { item: InboxItem; onOpenCompany: (id: number) => void; onChanged: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function reopen() {
    setBusy(true); setError("");
    try { await reopenInboxItem(item.id); await onChanged(); }
    catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  }
  async function ignore() {
    setBusy(true); setError("");
    try { await ignoreInboxItem(item.id); await onChanged(); }
    catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }
  return <article className="inbox-card">
    <div className="inbox-card-head">
      <span className={`brief-chip brief-chip--${item.category}`}>{item.category}</span>
      <button className="text-button" onClick={() => onOpenCompany(item.company_id)}>{item.company_name} · {item.symbol}</button>
      <time>{item.event_date}</time>
      <span className="inbox-source">{item.source}</span>
    </div>
    {item.url ? <a className="inbox-title" href={item.url} target="_blank" rel="noreferrer">{item.title}</a> : <p className="inbox-title">{item.title}</p>}
    {item.summary && <p className="inbox-summary">{item.summary}</p>}
    {item.detail && <p className="inbox-detail">{item.detail}</p>}
    {item.relevance && <p className="inbox-grade"><span className={`grade-chip grade-chip--${item.relevance}`}>{item.relevance === "高" ? "值得看" : item.relevance === "中" ? "待定" : "程序性"}</span>{item.relevance_reason} · 由{item.relevance_source}判定</p>}
    {error && <p className="form-error">{error}</p>}
    {/* **已忽略的那一档要给一条回头路。** 接口 `POST /inbox/{id}/reopen` 一直都在，
        而前端一次都没调过 —— 于是忽略是个单向门，自动整理成批忽略之后尤其要命。 */}
    <div className="inbox-actions">
      {item.inbox_status === "已忽略" ? <>
        <span className="muted-label">已忽略</span>
        <button className="text-button" onClick={() => void reopen()} disabled={busy}>
          {busy ? "处理中…" : "退回收件箱"}</button>
      </> : item.inbox_status === "已归档" ? <span className="muted-label">
        已归档为{item.archived_as === "evidence" ? "证据" : "事件"}</span> : <>
        <button className="text-button" onClick={() => setOpen((value) => !value)}>{open ? "收起" : "归档为证据或事件"}</button>
        <button className="text-button" onClick={() => void ignore()} disabled={busy}>{busy ? "处理中…" : "忽略"}</button>
      </>}
    </div>
    {open && <InboxArchiveForm item={item} onDone={onChanged} onCancel={() => setOpen(false)} />}
  </article>;
}

const INBOX_WINDOWS = [
  { days: 30, label: "近 30 天" },
  { days: 90, label: "近 90 天" },
  { days: 0, label: "全部" },
];

function InboxSection({ onOpenCompany, onChanged }: { onOpenCompany: (id: number) => void; onChanged: () => Promise<void> }) {
  const [page, setPage] = useState<InboxPage | null>(null);
  const [days, setDays] = useState(90);
  const [grade, setGrade] = useState<string | undefined>(undefined);
  /**
   * 看哪一档处理状态。**原来写死「待核验」** —— 于是一条被忽略的公告
   * 从界面上彻底消失了，尽管接口一直支持按状态查、也支持退回收件箱。
   * 自动整理会成批地忽略程序性文件，"忽略了什么、能不能拿回来"必须看得见。
   */
  const [box, setBox] = useState<"待核验" | "已忽略" | "已归档">("待核验");
  /**
   * 一次取多少条。**原来写死 40，而且没有任何"再看一批"的入口。**
   *
   * 2026-08-19 实测：切到「已归档」页面写着「窗口内 65 条」却只渲染 40 行，
   * 「全部」写着 203 条、还是 40 行 —— 163 条永远够不着，没有翻页、
   * 滚到底也不加载。而「已忽略」正是自动整理成批扫走的那些，
   * 「忽略了什么、能不能拿回来」本来就是这一页存在的理由。
   *
   * list_inbox 的注释里批过同一个病：「页面上就成了"说有 23 条、一条都不给看"」。
   * 那次修的是筛选导致的空列表，这道 40 的天花板是同一件事的另一面。
   */
  const [limit, setLimit] = useState(40);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // 换了筛选就收回展开的批次 —— 否则在「已归档」里展开到 200 条，
  // 切回「待核验」会一次拉 200 条，人却只想看头几条。
  useEffect(() => { setLimit(40); }, [days, grade, box]);
  useEffect(() => {
    let current = true;
    setLoading(true);
    getInbox(box, days, limit, grade)
      .then((next) => { if (current) { setPage(next); setError(""); } })
      .catch((caught) => { if (current) setError(errorMessage(caught)); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [days, grade, box, limit]);
  async function changed() {
    try { setPage(await getInbox(box, days, limit, grade)); setError(""); } catch (caught) { setError(errorMessage(caught)); }
    await onChanged();
  }
  const [autoGrade, setAutoGrade] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    getSettings()
      .then((s) => { if (alive) setAutoGrade(s.inbox_auto_grade); })
      .catch(() => { /* 读不到就不显示开关，别为一个偏好开关报错打断整页 */ });
    return () => { alive = false; };
  }, []);

  async function toggleAutoGrade(next: boolean) {
    const previous = autoGrade;
    setAutoGrade(next);            // 先动，失败再退回去：勾选框卡着不动比错一下更难受
    try {
      const saved = await saveSettings({ inbox_auto_grade: next });
      setAutoGrade(saved.inbox_auto_grade);
      setNotice(next
        ? "已开启：以后每天后台会替你把规则拿不准的送模型分级，按你的账户扣分。"
        : "已关闭：后台每天只跑规则，模型分级需要你在这里点。");
    } catch (caught) {
      setAutoGrade(previous);
      setError(errorMessage(caught));
    }
  }

  async function runClassify(useAi: boolean) {
    setBusy(useAi ? "ai" : "rules"); setError(""); setNotice("");
    try {
      const result = await classifyInbox(useAi);
      await changed();
      const cost = costText(result.billing);
      setNotice(`已分级 ${result.scanned} 条：规则 ${result.by_rules} 条、模型 ${result.by_model} 条；当前 高 ${result.counts["高"] ?? 0} / 中 ${result.counts["中"] ?? 0} / 程序性 ${result.counts["低"] ?? 0}。${result.note}${cost ? `　${cost}` : ""}`);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }
  async function autoTidy() {
    if (!(await confirmAction({
      title: "自动整理收件箱？",
      detail: "实质变化会归档为证据（来源与链接保留、极性留在中性），程序性文件会被忽略（仍可查回），只把规则和模型都拿不准的留给你。",
      confirmText: "开始整理",
    }))) return;
    setBusy("tidy"); setError(""); setNotice("");
    try {
      const result = await tidyInbox(true);
      await changed();
      setNotice(result.note);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }
  async function archiveWorthReading() {
    const count = page?.in_window ?? 0;
    if (!(await confirmAction({
      title: `把当前窗口内 ${count} 条已分级的公告归档为证据？`,
      detail: "来源和链接会保留，极性留在中性等你判断。", confirmText: "归档为证据",
    }))) return;
    setBusy("archive"); setError(""); setNotice("");
    try {
      const result = await archiveInboxBatch("高", days);
      await changed();
      setNotice(result.note);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }
  async function ignoreProcedural() {
    if (!(await confirmAction({
      title: "把所有判定为程序性的公告标记为已忽略？",
      detail: "它们仍然保留在库里，可以按状态查回来。", confirmText: "全部忽略",
    }))) return;
    setBusy("ignore"); setError(""); setNotice("");
    try {
      const result = await ignoreInboxByRelevance("低");
      await changed();
      setNotice(`已忽略 ${result.ignored} 条程序性公告。`);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }
  const items = page?.items ?? [];
  return <section className="panel inbox-panel">
    <div className="panel-heading">
      <div><span className="eyebrow">来自已接入的数据源</span><PanelTitle hint="已同步的公告、分红与解禁先落在这里；只有你确认后，它才会成为证据或事件。">待核验收件箱</PanelTitle></div>
      <span className="muted-label">{page ? `窗口内 ${page.in_window} 条 · 全部 ${page.total} 条待处理` : "正在统计"}</span>
    </div>
    <div className="chart-toolbar screener-toolbar">
      <div className="chart-range-group" role="group" aria-label="选择时间窗口">
        {INBOX_WINDOWS.map((window) => <button key={window.days} type="button" className={`chart-range${window.days === days ? " chart-range--on" : ""}`} onClick={() => setDays(window.days)}>{window.label}</button>)}
      </div>
      {/* **处理状态要能切。** 原来写死「待核验」，忽略掉的条目从界面上彻底消失，
          而自动整理会成批地忽略程序性文件 —— 忽略了什么、能不能拿回来，都得看得见。 */}
      <div className="chart-range-group" role="group" aria-label="按处理状态筛选">
        {(["待核验", "已忽略", "已归档"] as const).map((name) =>
          <button key={name} type="button" className={`chart-range${box === name ? " chart-range--on" : ""}`}
            onClick={() => setBox(name)}>{name}</button>)}
      </div>
      <div className="chart-range-group" role="group" aria-label="按相关度筛选">
        {/* **这个数要等于点开之后真会看到的条数。**
            原来写的是 high + medium，而这一档（不按等级筛）连"还没分级"的一起显示 ——
            2026-08-19 线上：按钮写着「值得看 3」，底下列表却是 17 条。
            未分级的那 14 条是"还没轮到它"，不是"判过了不值得看"，它们确实该在这一档里。 */}
        <button type="button" className={`chart-range${grade === undefined ? " chart-range--on" : ""}`} onClick={() => setGrade(undefined)}>值得看<em>{page ? page.high + page.medium + page.ungraded : 0}</em></button>
        <button type="button" className={`chart-range${grade === "高" ? " chart-range--on" : ""}`} onClick={() => setGrade("高")}>只看实质<em>{page?.high ?? 0}</em></button>
        <button type="button" className={`chart-range${grade === "低" ? " chart-range--on" : ""}`} onClick={() => setGrade("低")}>程序性<em>{page?.low ?? 0}</em></button>
      </div>
      <div className="pool-toolbar-right">
        <button className="page-action" disabled={busy !== ""} onClick={() => void autoTidy()}>{busy === "tidy" ? "正在整理…" : "自动整理收件箱"}</button>
        <button className="text-button" disabled={busy !== ""} onClick={() => void runClassify(true)}>{busy === "ai" ? "正在分级…" : "重新分级（规则＋模型）"}</button>
        <button className="text-button" disabled={busy !== "" || (page?.high ?? 0) === 0} onClick={() => void archiveWorthReading()}>{busy === "archive" ? "正在归档…" : "把实质变化批量归档为证据"}</button>
        <button className="text-button" disabled={busy !== "" || (page?.low ?? 0) === 0} onClick={() => void ignoreProcedural()}>{busy === "ignore" ? "处理中…" : `忽略全部程序性（${page?.low ?? 0}）`}</button>
      </div>
    </div>
    {notice && <p className="restore-message">{notice}</p>}
    {page && page.ungraded > 0 && <p className="market-history-note">还有 {page.ungraded} 条没有分级。分级只判断"这条是不是实质变化"，是否影响你的投资逻辑仍由你在归档时决定。</p>}
    {/* 后台每天只跑规则；模型那一步要花积分，所以做成用户自己勾的开关。
        不把话说清楚的话，「中」会一天天积着不动，看起来像是自动整理坏了。 */}
    {autoGrade !== null && (
      <p className="market-history-note">
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input type="checkbox" checked={autoGrade} onChange={(e) => void toggleAutoGrade(e.target.checked)} />
          后台每天替我做模型分级
        </label>
        {autoGrade
          ? "　开着：每天自动把规则拿不准的送模型，按你的账户扣积分。"
          : "　关着：后台每天只跑规则，规则拿不准的留在这里，要你点「重新分级（规则＋模型）」才让模型看。"}
      </p>
    )}
    <div className="inbox-list">
      {loading && <div className="empty-state">正在读取收件箱…</div>}
      {error && <p className="form-error">{error}</p>}
      {!loading && !error && items.length === 0 && <div className="empty-state">{page && page.total > 0 ? `这个时间窗口内没有${box === "待核验" ? "待处理" : box}的条目，可切换到更长的窗口。` : "收件箱是空的。在公司档案同步“公司简况”后，新的公告会自动进入这里。"}</div>}
      {items.map((item) => <InboxCard item={item} onOpenCompany={onOpenCompany} onChanged={changed} key={item.id} />)}
      {/* **取满了就说还剩多少，并给一个出口。**
          光显示 40 行、上面却写着 203 条，等于告诉人"有东西但你看不到"。 */}
      {!loading && page !== null && items.length >= limit && page.in_window > items.length &&
        <div className="inbox-more">
          <span>这一批显示了 {items.length} 条，窗口内还有 {page.in_window - items.length} 条没展开。</span>
          {/* **接口的上限就是 200**（`limit: int = Query(default=40, ge=1, le=200)`）。
              不夹住的话，点到第六次就是 422，整页报错 —— 那比看不全更糟。
              到顶了就把按钮换成一句实话，并给一条真的走得通的路。 */}
          {limit < INBOX_MAX
            ? <button className="text-button" type="button"
                onClick={() => setLimit((n) => Math.min(n + 40, INBOX_MAX))}>再看 40 条</button>
            : <span>一次最多列 {INBOX_MAX} 条，剩下的用上面的时间窗口或状态筛出来看。</span>}
        </div>}
    </div>
    <InboxLearningPanel />
  </section>;
}

function ReviewPage({ dashboard, onOpenCompany, onChanged }: { dashboard: DashboardSummary; onOpenCompany: (id: number) => void; onChanged: () => Promise<void> }) {
  const items = dashboard.events.filter((event) => event.verification !== "已核验" && event.verification !== "已归档");
  return <><section className="page-intro archive-intro"><div><span className="section-kicker">REVIEW QUEUE</span><h1>待办复核</h1><p>先处理可能改变投资逻辑的事实，再决定是否更新自己的判断。</p></div><div className="local-stamp"><span>QUEUE</span><strong>{items.length + dashboard.inbox_pending} 件待办</strong></div></section>{/* **积压要交代，但不该顶在首页当待办。**
    实测 193 条「中」级待核验里，属于「你写过判断的公司」的是 0 条——
    也就是说它们踩不到任何一条你写下的认错条件。分级对高低两档是有效的
    （高的已归档、低的已忽略），失效的是「中」：它没有出口，就一直堆着。
    堆着可以，说清楚就行；把它算进首页待办数才是错的——
    首页那个数必须等于"点进去真的会让你做事的数量"。 */}
{dashboard.inbox_backlog > 0 && <p className="inbox-backlog">
  另有 <strong>{dashboard.inbox_backlog} 条</strong>「中」级公告还没定性，没有列在这里——
  它们不属于你写过判断的公司，<strong>踩不到你任何一条认错条件</strong>。
  等你给那些公司写下判断，相关的会自动排到前面来。
</p>}
<InboxSection onOpenCompany={onOpenCompany} onChanged={onChanged} /><section className="review-stack">{items.length === 0 && <div className="empty-state">没有待核验事件。你可以回到公司档案记录新的研究变化。</div>}{items.map((event) => <button className="review-card" key={event.id} onClick={() => onOpenCompany(event.company_id)}><div className={`event-pin event-pin--${event.importance}`} /><div><span>{event.company_name} · {event.category}</span><h2>{event.title}</h2><p>{event.verification} · {formatDateTime(event.occurred_at)}</p></div><ChevronRight size={19} /></button>)}</section></>;
}

const INTERVAL_OPTIONS = [
  { minutes: 15, label: "15 分钟" },
  { minutes: 30, label: "30 分钟" },
  { minutes: 60, label: "1 小时" },
  { minutes: 240, label: "4 小时" },
  { minutes: 720, label: "12 小时" },
  { minutes: 1440, label: "1 天" },
  { minutes: 4320, label: "3 天" },
  { minutes: 10080, label: "7 天" },
];

const HEALTH_TONE: Record<string, string> = {
  正常: "ready",
  降级: "warn",
  运行中: "busy",
  已过期: "warn",
  有失败: "warn",
  从未成功: "idle",
  已停用: "idle",
};

function intervalLabel(minutes: number): string {
  const match = INTERVAL_OPTIONS.find((option) => option.minutes === minutes);
  if (match) return match.label;
  if (minutes % 1440 === 0) return `${minutes / 1440} 天`;
  if (minutes % 60 === 0) return `${minutes / 60} 小时`;
  return `${minutes} 分钟`;
}

function SyncJobCard({ job, busy, onRun, onUpdate }: { job: SyncJobStatus; busy: boolean; onRun: () => Promise<void>; onUpdate: (payload: SyncJobUpdateInput) => Promise<void> }) {
  const running = busy || job.last_status === "运行中";
  return <article className="sync-card">
    <div className="sync-card-main">
      <div className="sync-card-head">
        <span className={`provider-dot provider-dot--${HEALTH_TONE[job.health] ?? "idle"}`} />
        <h3>{job.display_name}</h3>
        <span className="sync-chip">{job.category}</span>
        <span className={`sync-health sync-health--${HEALTH_TONE[job.health] ?? "idle"}`}>{job.health}</span>
      </div>
      <p className="sync-desc">{job.description}</p>
      <p className="sync-message">{job.health_message}</p>
      {job.last_error && <p className="sync-error">最近一次错误：{job.last_error}</p>}
    </div>
    <div className="sync-card-meta">
      <div><span>上次成功</span><strong>{job.last_success_at ? formatDateTime(job.last_success_at) : "—"}</strong></div>
      <div><span>最近结果</span><strong>{job.last_status === "未运行" ? "—" : `${job.last_status} · ${job.last_items} 条`}</strong></div>
      <div><span>下次运行</span><strong>{job.enabled ? (job.next_run_at ? formatDateTime(job.next_run_at) : "待定") : "已停用"}</strong></div>
      <div><span>期望新鲜度</span><strong>{job.freshness_hours >= 24 ? `${Math.round(job.freshness_hours / 24)} 天内` : `${job.freshness_hours} 小时内`}</strong></div>
    </div>
    <div className="sync-card-actions">
      <label className="sync-toggle">
        <input type="checkbox" checked={job.enabled} onChange={(event) => void onUpdate({ enabled: event.target.checked })} />
        自动同步
      </label>
      <label className="sync-interval">
        间隔
        <select value={job.interval_minutes} onChange={(event) => void onUpdate({ interval_minutes: Number(event.target.value) })} disabled={!job.enabled}>
          {INTERVAL_OPTIONS.some((option) => option.minutes === job.interval_minutes) ? null : <option value={job.interval_minutes}>{intervalLabel(job.interval_minutes)}</option>}
          {INTERVAL_OPTIONS.map((option) => <option value={option.minutes} key={option.minutes}>{option.label}</option>)}
        </select>
      </label>
      <button className="page-action page-action--row" onClick={() => void onRun()} disabled={running}>{running ? "正在同步…" : "立即运行"}</button>
      {job.weekdays_only && <span className="sync-note">仅交易日运行</span>}
    </div>
  </article>;
}

function UniverseCoveragePanel({ summary }: { summary: UniverseSummary | null }) {
  if (!summary) return null;
  const snapshot = summary.last_snapshot;
  return <section className="panel">
    <div className="panel-heading compact">
      <div>
        <span className="eyebrow">云图与候选清单的共同底座</span><h2>全市场数据底座</h2>
        <p>{summary.coverage}。这一层只存事实与来源；筛选与排序在上层做，并且会带上数据截止日。</p>
      </div>
      <span className="muted-label">{summary.total > 0 ? `${summary.total} 只股票` : "尚未建立"}</span>
    </div>
    {summary.total === 0 ? <div className="market-history-empty">还没有全市场数据。在上面的“全市场底座”任务里点“立即运行”，会抓取全 A 与沪深300、中证500、上证50、中证1000 的成分。</div> : <>
      <div className="universe-facts">
        <article><span>板块分布</span><strong>{summary.boards.map((item) => `${item.name} ${item.count}`).join(" · ")}</strong></article>
        <article><span>主要指数</span><strong>{summary.indexes.map((item) => `${item.index_name} ${item.count}`).join(" · ")}</strong></article>
        <article><span>财务口径</span><strong>{summary.report_date ?? "未同步"} 报告期</strong></article>
        <article><span>自建估值历史</span><strong>{summary.valuation_history_days} 个交易日</strong></article>
      </div>
      <div className="coverage-list">
        {summary.completeness.map((item) => <div className="coverage-row" key={item.field}>
          <span>{item.label}</span>
          <i><b className={item.ratio >= 90 ? "coverage-fill" : item.ratio > 0 ? "coverage-fill coverage-fill--partial" : "coverage-fill coverage-fill--empty"} style={{ width: `${item.ratio}%` }} /></i>
          <strong>{item.ratio}%</strong>
        </div>)}
      </div>
      <p className="market-history-note">{summary.valuation_history_note}</p>
      {snapshot && <p className="market-history-note">
        最近一次：{formatDateTime(snapshot.started_at)} · {snapshot.status} · 行情来自{snapshot.price_source ?? "—"}
        {snapshot.fundamental_source ? ` · 财务来自${snapshot.fundamental_source}` : ""}
        {snapshot.degraded ? "（行情已降级）" : ""}
        {snapshot.note ? ` · ${snapshot.note}` : ""}
      </p>}
    </>}
  </section>;
}

function DataStatusPage() {
  // 这一页是**这台实例的运维面板**（排期、上次成功、每次取回多少条、立即运行），
  // 不是给用户看的内容。直接输网址进来的非站主给一句话，别撞一屏 403。
  const ownerHere = useIsOwner();
  const [jobs, setJobs] = useState<SyncJobStatus[]>([]);
  const [runs, setRuns] = useState<SyncRunRecord[]>([]);
  const [providers, setProviders] = useState<DataProviderStatus[]>([]);
  const [universe, setUniverse] = useState<UniverseSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyJob, setBusyJob] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function reload() {
    const [nextJobs, nextRuns, nextProviders, nextUniverse] = await Promise.all([
      getSyncJobs(), getSyncRuns(12), getDataProviders(), getUniverseSummary(),
    ]);
    setJobs(nextJobs);
    setRuns(nextRuns);
    setProviders(nextProviders);
    setUniverse(nextUniverse);
  }

  useEffect(() => {
    // 不是站主就别去问了 —— 那几个接口现在都是 require_owner，问了只会拿回 403，
    // 而且这个页面还带 20 秒轮询，等于每 20 秒撞一次门。
    if (ownerHere !== true) { if (ownerHere === false) setLoading(false); return; }
    let current = true;
    reload().catch((caught) => { if (current) setError(errorMessage(caught)); }).finally(() => { if (current) setLoading(false); });
    // 后台任务在跑的时候，页面每 20 秒自己刷新一次状态
    const timer = window.setInterval(() => { void reload().catch(() => undefined); }, 20000);
    return () => { current = false; window.clearInterval(timer); };
  }, [ownerHere]);

  async function runNow(job: SyncJobStatus) {
    setBusyJob(job.job_id); setError(""); setMessage("");
    try {
      const result = await runSyncJob(job.job_id);
      await reload();
      setMessage(`${job.display_name}：${result.status} · ${result.detail}${result.error ? `（${result.error}）` : ""}`);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusyJob(""); }
  }

  async function update(job: SyncJobStatus, payload: SyncJobUpdateInput) {
    setError("");
    try { await updateSyncJob(job.job_id, payload); await reload(); }
    catch (caught) { setError(errorMessage(caught)); }
  }

  // **不在这里列名单。** 这一行原来是 ["已过期","有失败","从未成功"]，
  // 而后端算的是四种（多一个「降级」）—— 同一个概念两处各写一份，
  // 结果首页说有事、点进这一页说「全部正常」。判定归后端，这里只读结论。
  const trouble = jobs.filter((job) => job.needs_attention);

  if (ownerHere === false) {
    return <section className="page-intro archive-intro">
      <div><span className="section-kicker">SOURCE HEALTH</span><h1>数据状态</h1>
        <p>同步排期与订阅源是这台实例的配置，改一处影响所有人，所以只有站主能看和改。
           行情、公告这些数据照常在各自的页面里看。</p></div>
    </section>;
  }

  return <>
    <section className="page-intro archive-intro">
      <div><span className="section-kicker">SOURCE HEALTH</span><h1>数据状态</h1><p>已接入的数据源、它们的同步排期与最近结果。自动同步只负责把事实取回来，判断仍由你做。</p></div>
      <div className="local-stamp"><span>SYNC</span><strong>{trouble.length === 0 ? `${jobs.length} 个任务正常` : `${trouble.length} 个需要关注`}</strong></div>
    </section>
    {error && <p className="form-error">{error}</p>}
    {message && <p className="restore-message">{message}</p>}
    {loading && <div className="empty-state page-loading">正在读取同步状态…</div>}
    {!loading && <>
      <section className="panel">
        <div className="panel-heading compact"><div><span className="eyebrow">按数据类型排期</span><PanelTitle hint="每个任务独立运行与重试；一个失败不影响其它任务，手动运行始终可用。">同步任务</PanelTitle></div></div>
        <div className="sync-list">{jobs.map((job) => <SyncJobCard job={job} busy={busyJob === job.job_id} onRun={() => runNow(job)} onUpdate={(payload) => update(job, payload)} key={job.job_id} />)}</div>
      </section>
      <UniverseCoveragePanel summary={universe} />
      <section className="panel">
        <div className="panel-heading compact"><div><span className="eyebrow">最近运行</span><h2>同步记录</h2></div><span className="muted-label">保留最近 12 次</span></div>
        <div className="run-list">
          {runs.length === 0 && <div className="empty-state">还没有运行记录。</div>}
          {runs.map((run) => <div className="run-row" key={run.id}>
            <time>{formatDateTime(run.started_at)}</time>
            <span className="run-name">{run.display_name ?? run.job_id}</span>
            <span className={`run-status run-status--${run.status === "成功" ? "ok" : run.status === "失败" ? "bad" : "warn"}`}>{run.status}</span>
            <span className="run-detail">{run.detail || "—"}{run.error ? ` · ${run.error}` : ""}</span>
            <span className="run-trigger">{run.trigger}</span>
          </div>)}
        </div>
      </section>
      <section className="provider-stack">{providers.map((provider) => <article className="provider-card" key={provider.provider_id}><div className={`provider-dot provider-dot--${provider.last_status === "已同步" ? "ready" : provider.last_status === "异常" ? "error" : "idle"}`} /><div><span>{provider.category}</span><h2>{provider.display_name}</h2><p>{provider.last_status === "已同步" ? `最近同步 ${provider.refreshed_items} 条${provider.category}数据` : provider.last_status === "异常" ? provider.last_error || "最近一次同步失败" : "尚未成功同步"}</p></div><div className="provider-time"><strong>{provider.last_success_at ? formatDateTime(provider.last_success_at) : "暂无成功记录"}</strong><span>最后成功同步</span></div></article>)}</section>
      <p className="data-status-note">当前已接入实时行情、前复权日线、定期报告、公司简况与公告、历史估值序列；研报、新闻与行业数据将在各自数据源确认后单独登记。</p>
    </>}
  </>;
}


/** 一行流水的数字部分。
 *
 * 五种类型该显示的东西完全不同：分红显示到账金额（没有股数与价格），
 * 送股只显示股数，ratio 口径只显示仓位占比。
 * 用同一句「N 股 × 单价」去套，分红那行会显示成「null 股 × null」。 */
function tradeFigures(trade: TradeRecord): string {
  if (trade.weight_percent !== null) return `仓位调整到 ${trade.weight_percent}%`;
  if (trade.side === "dividend") {
    return trade.cash_amount !== null ? `到账 ${formatMoney(trade.cash_amount)}` : "现金分红";
  }
  if (trade.side === "bonus") {
    return trade.shares !== null ? `+${trade.shares.toLocaleString("zh-CN")} 股（成本不变）` : "送股转增";
  }
  if (trade.shares === null || trade.price === null) return TRADE_SIDE_LABEL[trade.side];
  const total = trade.amount !== null ? ` · 合计 ${formatMoney(trade.amount)}` : "";
  return `${trade.shares.toLocaleString("zh-CN")} 股 × ${formatMoney(trade.price)}${total}`;
}


function PortfolioForm({ onSaved, onCancel }: { onSaved: (portfolioId: number) => Promise<void>; onCancel: () => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError("");
    const form = new FormData(event.currentTarget);
    try {
      const created = await createPortfolio({ name: String(form.get("name") ?? ""), objective: String(form.get("objective") ?? "") });
      await onSaved(created.id);
      onCancel();
    } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); }
  }
  return <form className="inline-form" onSubmit={submit}>
    <div className="form-grid compact-grid">
      <label>组合名称<input name="name" required placeholder="例如：长期核心仓" /></label>
      <label>这个组合的定位<input name="objective" placeholder="例如：只放已完成一轮复核的公司" /></label>
    </div>
    {error && <p className="form-error">{error}</p>}
    <div className="form-actions"><button className="page-action" type="submit" disabled={saving}>{saving ? "正在建立…" : "建立组合"}</button><button className="text-button" type="button" onClick={onCancel}>取消</button></div>
  </form>;
}

/** 交易流水按公司分组、可折叠。
 *
 * **两只股票就已经很长了。** 流水是按时间倒序平铺的，而人翻这一页时想的是
 * 「格力这只我都怎么操作的」——那是按公司看的问题，却被打散在时间轴里，
 * 要一屏屏往下找。三十几笔就已经翻不动，几年之后只会更糟。
 *
 * 默认全部折起来，只留一行摘要（几笔、买卖各多少、最近一笔什么时候）。
 * 展开是一次点击，而不展开时整页能一眼看完有哪几只票。
 */
function TradeGroups({ trades, onOpenCompany, onRevised }: {
  trades: TradeRecord[]; onOpenCompany?: (id: number) => void; onRevised?: () => Promise<void>;
}) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  if (trades.length === 0) return <div className="empty-state">还没有交易记录。</div>;

  const groups = new Map<number, TradeRecord[]>();
  for (const trade of trades) {
    const list = groups.get(trade.company_id);
    if (list) list.push(trade); else groups.set(trade.company_id, [trade]);
  }
  // 最近有动作的排前面——你要找的多半是刚操作过的那只。
  const ordered = [...groups.entries()].sort((a, b) =>
    (b[1][0]?.trade_date ?? "").localeCompare(a[1][0]?.trade_date ?? ""));

  return <div className="trade-groups">
    {ordered.map(([companyId, list]) => {
      const expanded = open.has(companyId);
      const buys = list.filter((t) => t.side === "buy").length;
      const sells = list.filter((t) => t.side === "sell").length;
      const others = list.length - buys - sells;
      const head = list[0];
      return <section className="trade-group" key={companyId}>
        <button className="trade-group-head" aria-expanded={expanded}
          onClick={() => setOpen((prev) => {
            const next = new Set(prev);
            next.has(companyId) ? next.delete(companyId) : next.add(companyId);
            return next;
          })}>
          <ChevronRight size={14} className={expanded ? "tg-caret tg-caret--on" : "tg-caret"} />
          <strong>{head.company_name}</strong>
          <span className="tg-symbol">{head.symbol}</span>
          <em>{list.length} 笔 · 买 {buys} 卖 {sells}{others ? ` · 其他 ${others}` : ""}</em>
          <span className="tg-last">最近 {head.trade_date}</span>
        </button>
        {expanded && <div className="trade-list">
          {list.map((trade) => <TradeRow trade={trade} onOpenCompany={onOpenCompany}
            onRevised={onRevised} key={trade.id} />)}
        </div>}
      </section>;
    })}
  </div>;
}

function TradeRow({ trade, onOpenCompany, onRevised }: { trade: TradeRecord; onOpenCompany?: (id: number) => void; onRevised?: () => Promise<void> }) {
  const overdue = trade.review_due !== null && trade.review_due <= todayIso();
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState("");
  async function remove() {
    // 删一笔交易会改变之后所有的成本价与持仓，所以要问一句；
    // 而问句里要带上这笔到底是什么，光问"确定删除吗"人是答不上来的。
    const what = `${TRADE_SIDE_LABEL[trade.side]} ${trade.company_name} ${trade.trade_date} ${tradeFigures(trade)}`;
    if (!(await confirmAction({
      title: `删掉这一笔？${what}`,
      detail: "删掉之后，这之后所有的成本价与持仓都会跟着重算。",
      confirmText: "删掉这一笔", danger: true,
    }))) return;
    setRemoving(true); setRemoveError("");
    // **删失败要说出来。** 原来只有 try/finally：接口报错时按钮转完就停，
    // 那一笔还在列表里 —— 看起来跟"删了但没刷新"一模一样，
    // 而这两件事对账本的意义完全相反。
    try { await deleteTrade(trade.id); await onRevised?.(); }
    catch (caught) { setRemoveError(errorMessage(caught)); }
    finally { setRemoving(false); }
  }
  return <article className={`trade-card trade-card--${trade.side}`} key={trade.id}>
    <div className="trade-card-head">
      <span className={`trade-side trade-side--${trade.side}`}>{TRADE_SIDE_LABEL[trade.side]}</span>
      {onOpenCompany ? <button className="text-button" onClick={() => onOpenCompany(trade.company_id)}>{trade.company_name} · {trade.symbol}</button> : <strong>{trade.company_name} · {trade.symbol}</strong>}
      <span className="trade-figures">{tradeFigures(trade)}</span>
      <time>{trade.trade_date}</time>
    </div>
    <p className="trade-rationale">{trade.rationale}</p>
    {trade.expectation && <p className="trade-expectation"><span>当时预期：</span>{trade.expectation}</p>}
    <footer>
      <span>{trade.thesis_claim_snapshot ? `当时逻辑：${trade.thesis_claim_snapshot}` : "未关联投资逻辑"}</span>
      <span className={overdue ? "quote-up" : ""}>{trade.review_due ? `${overdue ? "复核已到期" : "下次复核"} ${trade.review_due}` : "未设复核日期"} · {trade.portfolio_name} · 费用 {formatMoney(trade.fee)}</span>
    </footer>
    {onRevised && <div className="revision-actions">
      <button className="text-button" onClick={() => setEditing((value) => !value)}>{editing ? "取消修订" : "补记理由或复核日期"}</button>
      <RevisionHistory entity="trades" entityId={trade.id} count={trade.revision_count} />
      {/* **删除此前是没有的**，而逻辑、报告、产业链、策略都能删。
          交易恰恰最需要能删：手记会记错组合、也会记重。删不掉的话，
          唯一的补救是记一笔反向交易去抵消——那是往账本里写一笔从未发生过的事。 */}
      <button className="text-button text-button--danger" disabled={removing}
        onClick={() => void remove()}>{removing ? "正在删…" : "删除这笔"}</button>
    </div>}
    {removeError && <p className="form-error">{removeError}</p>}
    {editing && onRevised && <TradeReviseForm trade={trade} onSaved={onRevised} onCancel={() => setEditing(false)} />}
  </article>;
}

/** 持仓：一只票一行，两个数，只有新增和更新。
 *
 * 使用者 2026-09-23 定的模型，原话：
 *
 * > 持仓：只记持有股票数，只有一个数，新增和更新。
 * > 价格也是一个更新（采用成本价，更新）。
 *
 * 所以这里**没有买入卖出、没有日期、没有理由**——那些是交易的概念，
 * 而这一页记的是现状：打开券商 APP，把股数和成本价抄过来就完了。
 * 之前那套（手工流水 + 交割单读图 + 分红送转）已经删掉：它在跟券商 APP
 * 抢同一份活，而券商那边永远比这里准、比这里新、还不用你动手。
 *
 * **改一只票就存一只票**，不做"全表保存"：一次存全部的话，
 * 改错一格会把整页退回去，而你根本不知道是哪一格。 */
function HoldingsEditor({ portfolioId, positions, companies, onChanged, onOpenCompany }: {
  portfolioId: number;
  positions: PositionRecord[];
  companies: CompanyRecord[];
  onChanged: () => Promise<void> | void;
  onOpenCompany: (id: number) => void;
}) {
  // 每行编辑中的值。**只放"改过的那几行"**——没动过的行直接显示库里的数，
  // 全量灌进 state 会让别处刷新出的新数据被旧的编辑态盖住。
  const [draft, setDraft] = useState<Record<number, { shares: string; cost: string }>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);

  function valueOf(position: PositionRecord) {
    return draft[position.company_id] ?? {
      shares: String(position.shares ?? ""),
      cost: position.average_cost === null ? "" : String(position.average_cost),
    };
  }
  function edit(companyId: number, patch: Partial<{ shares: string; cost: string }>,
                position: PositionRecord) {
    setDraft((previous) => ({
      ...previous,
      [companyId]: { ...valueOf(position), ...patch },
    }));
  }
  const dirty = (position: PositionRecord) => {
    const value = draft[position.company_id];
    if (!value) return false;
    return Number(value.shares) !== position.shares
      || Number(value.cost) !== position.average_cost;
  };

  async function save(position: PositionRecord) {
    const value = valueOf(position);
    const shares = Number(value.shares);
    const cost = Number(value.cost);
    // **两个数都要有，而且都要大于 0。** 成本价填 0 的话浮盈会显示成无穷大。
    if (!Number.isFinite(shares) || shares <= 0) { setError("股数要填一个大于 0 的数。"); return; }
    if (!Number.isFinite(cost) || cost <= 0) { setError("成本价要填一个大于 0 的数。"); return; }
    setBusy(position.company_id); setError("");
    try {
      await setHolding(portfolioId, position.company_id, shares, cost);
      setDraft((previous) => {
        const next = { ...previous };
        delete next[position.company_id];
        return next;
      });
      await onChanged();
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(null); }
  }

  async function remove(position: PositionRecord) {
    // 确认框走纯文本（见 lib/confirm 的 window.confirm 兜底），不要写 **。
    if (!(await confirmAction({
      title: `把「${position.company_name}」从持仓里去掉？`,
      detail: "这一行连同它的历史一起删掉，回不来了。",
      confirmText: "删掉这一只", danger: true,
    }))) return;
    setBusy(position.company_id); setError("");
    try {
      const result = await deleteHolding(portfolioId, position.company_id);
      // 删 0 条和删 1 条在界面上长得一样，所以 0 要明说。
      if (result.deleted === 0) setError("一条都没删掉——这一只在这个组合里本来就没有记录。");
      await onChanged();
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(null); }
  }

  const held = new Set(positions.map((item) => item.company_id));

  return <div className="holdings-editor">
    <table className="holdings-table">
      <thead><tr>
        <th>公司</th><th>股数</th><th>成本价</th><th>现价</th><th>市值</th><th>盈亏</th><th />
      </tr></thead>
      <tbody>
        {positions.map((position) => {
          const value = valueOf(position);
          const changed = dirty(position);
          return <tr key={position.company_id}>
            <td>
              <button className="text-button" type="button"
                onClick={() => onOpenCompany(position.company_id)}>{position.company_name}</button>
              <em>{position.symbol}</em>
            </td>
            <td><input type="number" min="0" step="1" value={value.shares}
              onChange={(event) => edit(position.company_id, { shares: event.target.value }, position)} /></td>
            <td><input type="number" min="0" step="0.001" value={value.cost}
              onChange={(event) => edit(position.company_id, { cost: event.target.value }, position)} /></td>
            <td className="holdings-num">{position.latest_price === null ? "—" : formatMoney(position.latest_price)}</td>
            <td className="holdings-num">{position.market_value === null ? "—" : formatMoney(position.market_value)}</td>
            <td className={`holdings-num ${pnlClass(position.unrealized_pnl)}`}>
              {signedPercentText(position.unrealized_percent)}
            </td>
            <td className="holdings-actions">
              {/* 只有真改过才亮「存」——一个永远可点的保存键会让人不确定存没存过。 */}
              {changed && <button className="page-action" type="button"
                disabled={busy === position.company_id}
                onClick={() => void save(position)}>
                {busy === position.company_id ? "…" : "存"}</button>}
              <button className="text-button text-button--danger" type="button"
                disabled={busy === position.company_id}
                onClick={() => void remove(position)}>删</button>
            </td>
          </tr>;
        })}
      </tbody>
    </table>
    {error && <p className="form-error">{error}</p>}
    {adding
      ? <HoldingAddRow portfolioId={portfolioId}
          companies={companies.filter((item) => !held.has(item.id))}
          onDone={async () => { setAdding(false); await onChanged(); }}
          onCancel={() => setAdding(false)} />
      : <button className="text-button" type="button" onClick={() => setAdding(true)}>＋ 添加一只</button>}
    <p className="holdings-note">
      打开券商 APP，把股数和成本价抄过来就行。<strong>改完点「存」，它就是现在的持仓</strong>——
      不用记买入卖出，也不用补历史。精确到分的成本与收益券商那边永远比这里准。
    </p>
  </div>;
}

/** 添加一只。跟编辑行分开写：新增要选公司，编辑不用。 */
function HoldingAddRow({ portfolioId, companies, onDone, onCancel }: {
  portfolioId: number; companies: CompanyRecord[];
  onDone: () => Promise<void>; onCancel: () => void;
}) {
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [shares, setShares] = useState("");
  const [cost, setCost] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (companyId === null) { setError("先选一家公司。"); return; }
    const n = Number(shares), c = Number(cost);
    if (!Number.isFinite(n) || n <= 0) { setError("股数要填一个大于 0 的数。"); return; }
    if (!Number.isFinite(c) || c <= 0) { setError("成本价要填一个大于 0 的数。"); return; }
    setBusy(true); setError("");
    try {
      await setHolding(portfolioId, companyId, n, c);
      await onDone();
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  }

  return <form className="holdings-add" onSubmit={submit}>
    <select value={companyId ?? ""} required
      onChange={(event) => setCompanyId(event.target.value ? Number(event.target.value) : null)}>
      <option value="">选一家已建档的公司</option>
      {companies.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.symbol}</option>)}
    </select>
    <input type="number" min="0" step="1" placeholder="股数" value={shares}
      onChange={(event) => setShares(event.target.value)} required />
    <input type="number" min="0" step="0.001" placeholder="成本价" value={cost}
      onChange={(event) => setCost(event.target.value)} required />
    <button className="page-action" type="submit" disabled={busy}>{busy ? "…" : "添加"}</button>
    <button className="text-button" type="button" onClick={onCancel}>取消</button>
    {error && <p className="form-error">{error}</p>}
  </form>;
}


function PositionTable({ positions, onOpenCompany, ratioMode = false }: { positions: PositionRecord[]; onOpenCompany: (id: number) => void; ratioMode?: boolean }) {
  if (ratioMode) {
    return <div className="holding-overview" role="table" aria-label="仓位结构">
      <div className="holding-overview-head" role="row"><span>公司</span><span>仓位</span><span>成本</span><span>判断</span></div>
      {positions.map((position) => {
        const weight = position.weight_percent ?? position.weight;
        return <div className="holding-overview-row" role="row" key={position.company_id}>
          <span className="holding-overview-company"><button className="text-button" onClick={() => onOpenCompany(position.company_id)}>{position.company_name}</button><em>{position.symbol} · {position.industry}</em></span>
          <span className="holding-overview-weight"><strong>{weight === null ? "—" : `${weight.toFixed(1)}%`}</strong><i aria-hidden="true"><b style={{ width: `${Math.min(100, weight ?? 0)}%` }} /></i></span>
          <span className="holding-overview-cost">{formatMoney(position.average_cost) === "—" ? "未记录" : formatMoney(position.average_cost)}</span>
          <span className="holding-overview-status">{position.thesis_status ? <StatusBadge status={position.thesis_status} /> : <em>未写判断</em>}<em>{position.next_review_due ? `复核 ${position.next_review_due}` : "未设复核"}</em></span>
        </div>;
      })}
    </div>;
  }
  return <div className="position-table" role="table" aria-label="当前持仓">
    <div className="position-row position-row--head" role="row"><span>公司</span><span>股数</span><span>成本价</span><span>现价</span><span>市值</span><span>浮动盈亏</span><span>权重</span><span>逻辑 / 复核</span></div>
    {positions.map((position) => <div className="position-row" role="row" key={position.company_id}>
      <span><button className="text-button" onClick={() => onOpenCompany(position.company_id)}>{position.company_name}</button><em>{position.symbol} · {position.industry}</em></span>
      <span data-label="股数">{ratioMode ? "未记录" : position.shares.toLocaleString("zh-CN")}</span>
      <span data-label="成本价">{formatMoney(position.average_cost)}</span>
      <span data-label="现价">{position.latest_price === null ? "行情未同步" : formatMoney(position.latest_price)}</span>
      <span data-label="市值">{formatMoney(position.market_value)}</span>
      <span data-label="浮动盈亏" className={pnlClass(position.unrealized_pnl)}>{formatSigned(position.unrealized_pnl)}{position.unrealized_percent === null ? "" : ` (${position.unrealized_percent > 0 ? "+" : ""}${position.unrealized_percent.toFixed(2)}%)`}</span>
      <span data-label="权重">{position.weight === null ? "—" : `${position.weight.toFixed(1)}%`}<i className="position-bar" aria-hidden="true"><b style={{ width: `${Math.min(100, position.weight ?? 0)}%` }} /></i></span>
      <span>{position.thesis_status ? <StatusBadge status={position.thesis_status} /> : <em>未写逻辑</em>}<em className={position.next_review_due && position.next_review_due <= todayIso() ? "quote-up" : ""}>{position.next_review_due ? `复核 ${position.next_review_due}` : "未设复核"}</em></span>
    </div>)}
  </div>;
}

function PortfolioPage({ onOpenCompany, onLedgerChanged }: { onOpenCompany: (id: number) => void; onLedgerChanged: () => Promise<void> }) {
  const [portfolios, setPortfolios] = useState<PortfolioSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PortfolioDetail | null>(null);
  const [companies, setCompanies] = useState<CompanyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [composer, setComposer] = useState<"portfolio" | null>(null);

  useEffect(() => {
    let current = true;
    (async () => {
      try {
        const [items, companyList] = await Promise.all([getPortfolios(), getCompanies()]);
        if (!current) return;
        setPortfolios(items);
        setCompanies(companyList);
        setActiveId((previous) => previous ?? items[0]?.id ?? null);
        setError("");
      } catch (caught) { if (current) setError(errorMessage(caught)); }
      finally { if (current) setLoading(false); }
    })();
    return () => { current = false; };
  }, []);

  useEffect(() => {
    if (activeId === null) return;
    let current = true;
    getPortfolio(activeId).then((item) => { if (current) setDetail(item); }).catch((caught) => { if (current) setError(errorMessage(caught)); });
    return () => { current = false; };
  }, [activeId]);

  async function removePortfolio() {
    const target = portfolios.find((item) => item.id === activeId);
    if (!target) return;
    // 确认框只认纯文本（见 lib/confirm 的 window.confirm 兜底），不要写 **。
    if (!(await confirmAction({
      title: `删掉组合「${target.name}」？`,
      detail: target.position_count > 0
        ? `里面还有 ${target.position_count} 只持仓，会一起删掉，回不来了。`
        : "这个组合是空的，删掉不影响任何持仓。",
      confirmText: "删掉这个组合", danger: true,
    }))) return;
    try {
      const result = await deletePortfolio(target.id);
      // 带走了多少只一定要说：删空组合和删掉装满记录的组合，界面上长得一样。
      setError(result.holdings > 0
        ? `已删掉「${result.name}」，连同里面 ${result.holdings} 只持仓。`
        : `已删掉空组合「${result.name}」。`);
      const rest = portfolios.filter((item) => item.id !== target.id);
      await reload(rest[0]?.id);
    } catch (caught) { setError(errorMessage(caught)); }
  }

  async function reload(portfolioId?: number) {
    const next = portfolioId ?? activeId;
    try {
      const items = await getPortfolios();
      setPortfolios(items);
      if (next !== null && next !== undefined) { setActiveId(next); setDetail(await getPortfolio(next)); }
      await onLedgerChanged();
      setError("");
    } catch (caught) { setError(errorMessage(caught)); }
  }

  const ratioMode = detail?.amount_mode === "ratio";
  // 指标格分两层：**一个格子要靠"有话说"挣来**。
  //
  // 原来七格无条件铺开，在「1 只持仓 · 5 笔交易」下量出来是这样的：
  // 持仓市值与浮动盈亏跟下面表格那一行一字不差、已实现盈亏/已收分红/待复核全是 0、
  // 最大单一权重在只有一只时恒等于 100% —— 七个数里只有「持仓成本」是别处看不到的。
  // 七格排三列除不尽，最后一行还剩两个空格子。
  // **用 330 像素换一条新信息**，这就是那种"精装修的空房子"感的来源。
  //
  // 现在：常驻三格（市值·成本·浮动盈亏，正好一行），其余四项**只在不为零时**才占格；
  // 为零的收进下面一条小字——不是删掉，是降级。为零本身也是事实，只是不值一格。
  const alwaysTiles = detail ? ratioMode ? [
    { label: "已记录持仓", value: `${detail.position_count} 只`, detail: "只记录仓位占比，不计算总金额" },
    { label: "最大仓位", value: detail.largest_weight === null ? "—" : `${detail.largest_weight.toFixed(1)}%`, detail: "只描述当前快照，不是买卖建议" },
  ] : [
    { label: "持仓市值", value: formatMoney(detail.market_value), detail: detail.priced_positions === detail.position_count ? `${detail.position_count} 只持仓` : `${detail.priced_positions}/${detail.position_count} 只有实时行情` },
    { label: "持仓成本", value: formatMoney(detail.cost_value), detail: "含买入费用的移动加权成本" },
    { label: "浮动盈亏", value: formatSigned(detail.unrealized_pnl), detail: detail.unrealized_percent === null ? "等待行情同步" : `${detail.unrealized_percent > 0 ? "+" : ""}${detail.unrealized_percent.toFixed(2)}%`, tone: pnlClass(detail.unrealized_pnl) },
  ] : [];
  // 有条件的四项。`shown` 为假时不占格，改成下面那条小字里的一段。
  const maybeTiles = detail && !ratioMode ? [
    { shown: detail.realized_pnl !== 0, label: "已实现盈亏", value: formatSigned(detail.realized_pnl), detail: "卖出结转，已扣费用", tone: pnlClass(detail.realized_pnl), quiet: "还没卖出过" },
    // 分红单独一格：它与买卖差价是两种性质不同的钱，合在一起就看不出
    // 这个组合到底是靠差价还是靠现金流回报的——而那是长期投资要回答的问题。
    { shown: detail.dividend_income > 0, label: "已收分红", value: formatMoney(detail.dividend_income), detail: "现金分红，不含买卖差价", quiet: "还没记过分红" },
    // **只有一只持仓时它恒等于 100%**，那不是信息，是算术。两只起才谈得上集中度。
    { shown: detail.position_count >= 2 && detail.largest_weight !== null, label: "最大单一权重", value: detail.largest_weight === null ? "—" : `${detail.largest_weight.toFixed(1)}%`, detail: detail.top3_weight === null ? "尚无可计价持仓" : `前三合计 ${detail.top3_weight.toFixed(1)}%`, quiet: "只有一只持仓，谈不上集中度" },
    { shown: detail.reviews_due > 0, label: "待复核交易", value: `${detail.reviews_due} 笔`, detail: "买入时你给自己定的复核日到了", quiet: "没有到期要复核的交易" },
  ] : [];
  const tiles = [...alwaysTiles, ...maybeTiles.filter((item) => item.shown)];
  const quiet = maybeTiles.filter((item) => !item.shown);
  // 组合概要那句「1 只 · 5 笔」在有多个组合时已经写在标签上了，别说第二遍。
  const showTitleMeta = portfolios.length <= 1 && detail !== null;
  const titleMeta = detail
    ? detail.amount_mode === "ratio"
      ? `${detail.name} · ${detail.position_count} 只`
      : `${detail.name} · ${detail.position_count} 只 · ${detail.trade_count} 笔`
    : "";

  return <>
    <section className="page-intro archive-intro">
      <div><span className="section-kicker">POSITION LEDGER</span>
        <h1>持仓账本{showTitleMeta && <em className="page-title-meta">{titleMeta}</em>}</h1>
        {/* **这句说明只在空账本时出现。** 它回答的是"这一页是干什么的"——
            一旦你已经记了交易，它每次都占着 40 像素却再也不会被读一遍。 */}
        {(!detail || detail.trade_count === 0) &&
          <p>一只票一行，两个数：股数和成本价。打开券商 APP 抄过来就行，不用记买卖、不用补历史。</p>}
      </div>
      <div className="intro-actions">
        {/* **「完整交易流水」那个入口删掉了。**
            持仓改成「只记股数和成本价」之后，手工记一笔 buy 不再影响持仓，
            留着它等于摆一个点了没有任何效果的按钮。
            它原来唯一的用处是喂「计划内 / 计划外」那个指标，
            而那件事挪到了决策卡上的「登记成交」——在你真动手的那一刻记一次，
            不是事后补账。 */}
        <button className="text-button" onClick={() => setComposer(composer === "portfolio" ? null : "portfolio")}>新建组合</button>
        {/* **组合此前根本删不掉**（接口只有 GET 和 PATCH），
            于是一个手滑建出来的空组合会永远杵在页签上。 */}
        {activeId !== null && portfolios.length > 1 && <button className="text-button text-button--danger"
          onClick={() => void removePortfolio()}>删掉这个组合</button>}
      </div>
    </section>
    {error && <p className="form-error">{error}</p>}
    {composer === "portfolio" && <section className="panel"><PortfolioForm onSaved={(portfolioId) => reload(portfolioId)} onCancel={() => setComposer(null)} /></section>}
    {loading && <div className="empty-state page-loading">正在读取持仓账本…</div>}
    {!loading && portfolios.length > 1 && <div className="portfolio-tabs" role="tablist" aria-label="选择组合">{portfolios.map((item) => <button key={item.id} role="tab" aria-selected={item.id === activeId} className={`portfolio-tab${item.id === activeId ? " portfolio-tab--on" : ""}`} onClick={() => setActiveId(item.id)}>{item.name}{/* **不再显示"N 笔"**：持仓现在是"现在持有什么"，没有流水这个概念了。
            改一次持仓底下确实会多一行历史，但那是实现细节，不该摆到页签上
            让人以为自己交易了 N 次。 */}
          <em>{item.position_count} 只</em></button>)}</div>}
    {!loading && detail && <>
      {detail.objective && <p className="portfolio-objective">{detail.objective}</p>}
      <section className="metric-strip portfolio-metrics" aria-label="组合概要">{tiles.map((tile) => <article className="metric metric--plain" key={tile.label}><span>{tile.label}</span><strong className={tile.tone}>{tile.value}</strong><small>{tile.detail}</small></article>)}</section>
      {/* 降级的那几项。**为零也是事实，只是不值一个格子。**
          行尾接动作入口：这一条恰恰出现在账本还很薄的时候，
          而那时最该被看见的就是"填一只持仓"——
          原来这两个入口只在右上角最小的一行字里。 */}
      {/* **这里原来还挂着第二个「＋ 添加持仓」。**
          当时的理由写在上面那段注释里：「这两个入口只在右上角最小的一行字里」——
          而现在右上角是一颗醒目的绿底按钮，那个前提已经不成立了。
          前提被推翻不等于结论自动失效，但这一行本来就已经有四组「标签 + 说明」，
          再挂一个跟右上角重复的动作，只是把一行本来就密的字挤得更密。 */}
      {quiet.length > 0 && <p className="metric-quiet">
        {quiet.map((item) => <span key={item.label}><b>{item.label}</b>{item.quiet}</span>)}
      </p>}
      <section className="panel">
        <div className="panel-heading"><div><span className="eyebrow">{ratioMode ? "可选个人视角" : "现在持有什么"}</span><PanelTitle hint={ratioMode ? "只记录你是否持有、仓位占比和可选成本；不填也不影响判断复核。" : "一只票一行，两个数：股数和成本价。改完点「存」就是现在的持仓，不用记买卖、不用补历史。"}>当前持仓</PanelTitle></div><span className="muted-label">{detail.name}</span></div>
        {/* **仓位口径的组合还是只读那张老表**：它按设计不记股数，
            而这个编辑器的两个数里有一个就是股数。 */}
        {ratioMode
          ? (detail.positions.length === 0
              ? <div className="market-history-empty">还没有记录持仓。你可以只维护判断，不填写任何持仓信息。</div>
              : <PositionTable positions={detail.positions} onOpenCompany={onOpenCompany} ratioMode />)
          : activeId !== null && <HoldingsEditor portfolioId={activeId}
              positions={detail.positions} companies={companies}
              onChanged={() => reload()} onOpenCompany={onOpenCompany} />}
      </section>
      {/* **分散不是由只数决定的，是由它们会不会同时出事决定的。**
          紧跟在持仓表后面：上面那张表让你看见「我有几只」，
          这一块回答「这几只是不是同一个赌注」。 */}
      {detail.positions.length > 0 && <section className="panel">
        <div className="panel-heading"><div><span className="eyebrow">风险结构</span><PanelTitle hint="把持仓按共同的行业、估值、位置与认错条件归组；点开一组查看构成。">共同风险</PanelTitle></div></div>
        <Suspense fallback={<div className="empty-state">正在加载…</div>}><CommonRisk portfolioId={activeId} onOpenCompany={onOpenCompany} /></Suspense>
      </section>}
      {!ratioMode && detail.closed_positions.length > 0 && <section className="panel">
        <div className="panel-heading compact"><div><span className="eyebrow">已清仓</span><h2>结束的持仓</h2></div></div>
        <div className="closed-list">{detail.closed_positions.map((position) => <div className="closed-row" key={position.company_id}><button className="text-button" onClick={() => onOpenCompany(position.company_id)}>{position.company_name} · {position.symbol}</button><span>{position.first_trade_date} → {position.last_trade_date} · {position.trade_count} 笔</span><strong className={pnlClass(position.realized_pnl)}>已实现 {formatSigned(position.realized_pnl)}</strong></div>)}</div>
      </section>}
      {!ratioMode && <section className="panel">
        <div className="panel-heading compact"><div><span className="eyebrow">决策留痕</span><PanelTitle hint="每一笔都保留当时的理由、预期和逻辑原文，便于日后复盘。">交易流水</PanelTitle></div></div>
        <TradeGroups trades={detail.trades} onOpenCompany={onOpenCompany} onRevised={() => reload()} />
      </section>}
    </>}
  </>;
}

function LedgerFactsPanel({ company, onSaved }: { company: CompanyDetail; onSaved: () => Promise<void> }) {
  const [portfolios, setPortfolios] = useState<PortfolioSummary[]>([]);
  useEffect(() => { let current = true; getPortfolios().then((items) => { if (current) setPortfolios(items); }).catch(() => undefined); return () => { current = false; }; }, []);
  const ledger = company.ledger;
  // 这家公司记的是"占多少仓位"还是"多少股"。两种口径能显示的东西不一样：
  // 仓位口径没有股数，也就没有市值和浮动盈亏。
  const ratioLedger = ledger?.amount_mode === "ratio" && ledger.weight_percent !== null;
  const [closing, setClosing] = useState(false);
  const [ledgerError, setLedgerError] = useState("");

  /** 记一条「仓位 0%」——**这才叫清仓**，而不是系统看 shares=0 猜出来的。 */
  async function markCleared() {
    const target = portfolios.find((item) => ledger?.portfolio_names.includes(item.name)) ?? portfolios[0];
    if (!target) return;
    if (!(await confirmAction({
      title: `把「${company.name}」标记为已清仓？`,
      detail: "会记一条「仓位调整到 0%」的快照。之前的记录都保留，随时可以再记一次仓位。",
      confirmText: "标记已清仓", danger: true,
    }))) return;
    setClosing(true); setLedgerError("");
    try {
      await createTrade(target.id, {
        company_id: company.id, side: "sell", trade_date: todayIso(),
        weight_percent: 0, rationale: "标记已清仓（持仓快照）",
      });
      await onSaved();
    } catch (caught) { setLedgerError(errorMessage(caught)); } finally { setClosing(false); }
  }

  return <section className="panel ledger-facts-panel">
    <div className="panel-heading">
      <div><span className="eyebrow">你的持仓</span><PanelTitle hint="股数与成本价由你自己填；这里只是把它跟这家公司的研究摆在一起，不构成买卖建议。">持仓与决策账本</PanelTitle></div>
      <div className="ledger-head-actions">
        {/* **清仓要由你说了算。** 仓位口径下没有股数，系统无从判断你是不是还拿着；
            原来它拿 shares=0 当"已清仓"，等于替你做了这个决定。现在只有你点这里才算。 */}
        {ratioLedger && (ledger!.weight_percent ?? 0) > 0 && <button className="text-button" type="button" disabled={closing}
          onClick={() => void markCleared()}>{closing ? "正在记…" : "标记已清仓"}</button>}
        {/* **「记录交易」删掉了。** 持仓改成「只记股数和成本价」之后，
            手工记一笔 buy 不再影响持仓——点了没有任何效果的按钮比没有按钮更糟。
            改持仓去持仓账本，登记成交去决策卡。 */}
      </div>
    </div>
    {ledgerError && <p className="form-error">{ledgerError}</p>}
    {!ledger ? <div className="market-history-empty">
      还没有这家公司的持仓。去<strong>持仓账本</strong>填股数和成本价，一分钟的事。
    </div> : <>
      <div className="financial-facts-grid">
        {/* **仓位口径下 shares 永远是 0。** 只看 shares 的话，一笔刚记完的
            50% 持仓会被写成「已清仓」——使用者真撞上了这一幕。这里按口径分开显示：
            记了仓位就说仓位，记了股数才说股数；两种都没有才是真的清仓。 */}
        {ratioLedger
          ? <article><span>当前仓位</span><strong>{ledger.weight_percent! > 0 ? `${ledger.weight_percent}%` : "已清仓"}</strong><em>{ledger.portfolio_names.join(" / ")}　·　只记占比，不记股数</em></article>
          : <article><span>当前持股</span><strong>{ledger.shares > 0 ? `${ledger.shares.toLocaleString("zh-CN")} 股` : "已清仓"}</strong><em>{ledger.portfolio_names.join(" / ")}</em></article>}
        <article><span>{ratioLedger ? "记下的成本价" : "持仓成本"}</span><strong>{ledger.average_cost === null ? "—" : formatMoney(ledger.average_cost)}</strong><em>{ratioLedger ? "仓位口径不换算金额" : `合计 ${formatMoney(ledger.cost_value)}`}</em></article>
        {/* 仓位口径下没有股数，也就算不出市值与浮动盈亏。**说清是"算不出"，
            不是"没赚没亏"**——摆一个 0.00 在那里会被读成后者。 */}
        <article><span>浮动盈亏</span><strong className={ratioLedger ? "" : pnlClass(ledger.unrealized_pnl)}>{ratioLedger ? "—" : formatSigned(ledger.unrealized_pnl)}</strong><em>{ratioLedger ? "要算盈亏得记股数（下面可以补）" : ledger.unrealized_percent === null ? "等待行情同步" : `${ledger.unrealized_percent > 0 ? "+" : ""}${ledger.unrealized_percent.toFixed(2)}% · 市值 ${formatMoney(ledger.market_value)}`}</em></article>
        <article><span>已实现盈亏</span><strong className={pnlClass(ledger.realized_pnl)}>{formatSigned(ledger.realized_pnl)}</strong><em>{ledger.next_review_due ? `下次复核 ${ledger.next_review_due}` : "未设复核日期"}</em></article>
      </div>
      <TradeGroups trades={ledger.trades} onRevised={onSaved} />
    </>}
  </section>;
}

const REVISION_FIELD_LABELS: Record<string, string> = {
  claim: "主张",
  counter_condition: "反证条件",
  status: "状态",
  next_review_trigger: "复核触发条件",
  rationale: "交易理由",
  expectation: "预期与证伪条件",
  review_due: "复核日期",
  thesis_id: "关联逻辑",
};

function revisionValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "（空）";
  if (field === "status") return statusCopy[value as ThesisStatus]?.label ?? String(value);
  return String(value);
}

function RevisionHistory({ entity, entityId, count }: { entity: "theses" | "trades"; entityId: number; count: number }) {
  const [open, setOpen] = useState(false);
  const [revisions, setRevisions] = useState<RecordRevision[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    let current = true;
    getRevisions(entity, entityId)
      .then((items) => { if (current) { setRevisions(items); setError(""); } })
      .catch((caught) => { if (current) setError(errorMessage(caught)); });
    return () => { current = false; };
  }, [open, entity, entityId, count]);
  if (count <= 0) return null;
  return <div className="revision-block">
    <button className="text-button" onClick={() => setOpen((value) => !value)}><History size={12} />{open ? "收起修订历史" : `修订历史（${count} 版）`}</button>
    {open && (error ? <p className="form-error">{error}</p> : <ol className="revision-list">
      {revisions.map((revision) => <li key={revision.id}>
        <div className="revision-head"><strong>v{revision.version}</strong><span>{revision.changed_fields || "建立"}</span><time>{formatDateTime(revision.created_at)}</time></div>
        {revision.change_note && <p className="revision-note">{revision.change_note}</p>}
        <dl>{Object.entries(revision.snapshot).map(([field, value]) => <div key={field}><dt>{REVISION_FIELD_LABELS[field] ?? field}</dt><dd>{revisionValue(field, value)}</dd></div>)}</dl>
      </li>)}
    </ol>)}
  </div>;
}

function ThesisReviseForm({ thesis, onSaved, onCancel, suggestedCounter }: { thesis: ThesisRecord; onSaved: () => Promise<void>; onCancel: () => void; suggestedCounter?: string }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError("");
    const form = new FormData(event.currentTarget);
    try {
      await reviseThesis(thesis.id, {
        claim: String(form.get("claim") ?? ""),
        counter_condition: String(form.get("counter_condition") ?? ""),
        status: String(form.get("status") ?? thesis.status) as ThesisStatus,
        next_review_trigger: String(form.get("next_review_trigger") ?? ""),
        change_note: String(form.get("change_note") ?? ""),
      });
      await onSaved();
      onCancel();
    } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); }
  }
  return <form className="inline-form" onSubmit={submit}>
    <label>主张<textarea name="claim" rows={2} defaultValue={thesis.claim} required /></label>
    {/* 反方给的建议只作为**初值**填进来，改不改、留不留是你的事。
        直接写库的话，这个功能就从"提议"变成"替你决定"了。 */}
    <label>反证条件<textarea name="counter_condition" rows={suggestedCounter ? 4 : 2}
      defaultValue={suggestedCounter || thesis.counter_condition} /></label>
    {suggestedCounter && <p className="form-note">下面这条是反方建议加的，已经填进上面的框里——<strong>改成你自己的话再存</strong>。</p>}
    <div className="form-grid compact-grid">
      <label>状态<select name="status" defaultValue={thesis.status}><option value="intact">成立</option><option value="watching">待观察</option><option value="challenged">受挑战</option><option value="broken">已破坏</option></select></label>
      <label>下次复核触发<input name="next_review_trigger" defaultValue={thesis.next_review_trigger} /></label>
    </div>
    <label>这次改了什么、为什么<input name="change_note" placeholder="例如：中报确认现金流改善，主张收窄到主业" /></label>
    {error && <p className="form-error">{error}</p>}
    <div className="form-actions"><button className="page-action" type="submit" disabled={saving}>{saving ? "正在保存…" : "保存为新版本"}</button><button className="text-button" type="button" onClick={onCancel}>取消</button></div>
    <p className="form-note">保存会追加一个新版本，旧版本原文仍可在修订历史中回看，不会被覆盖。</p>
  </form>;
}

function TradeReviseForm({ trade, onSaved, onCancel }: { trade: TradeRecord; onSaved: () => Promise<void>; onCancel: () => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError("");
    const form = new FormData(event.currentTarget);
    const reviewDue = String(form.get("review_due") ?? "");
    try {
      await reviseTrade(trade.id, {
        rationale: String(form.get("rationale") ?? ""),
        expectation: String(form.get("expectation") ?? ""),
        review_due: reviewDue || null,
        change_note: String(form.get("change_note") ?? ""),
      });
      await onSaved();
      onCancel();
    } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); }
  }
  return <form className="inline-form" onSubmit={submit}>
    <label>交易理由<textarea name="rationale" rows={3} defaultValue={trade.rationale} required /></label>
    <label>预期与证伪条件<textarea name="expectation" rows={2} defaultValue={trade.expectation} /></label>
    <div className="form-grid compact-grid">
      <label>下次复核<input type="date" name="review_due" defaultValue={trade.review_due ?? ""} /></label>
      <label>这次改了什么、为什么<input name="change_note" placeholder="例如：补记当时遗漏的渠道数据" /></label>
    </div>
    {error && <p className="form-error">{error}</p>}
    <div className="form-actions"><button className="page-action" type="submit" disabled={saving}>{saving ? "正在保存…" : "保存为新版本"}</button><button className="text-button" type="button" onClick={onCancel}>取消</button></div>
    <p className="form-note">交易金额、方向和日期不可修改；理由与预期的每次改动都会留下版本，原始记录不会消失。</p>
  </form>;
}

// 表名 → 人话。**取不到就原样显示表名**，不要漏一行——
// 这一页数的是"你手写了多少东西"，少一行等于少报了一份他的记录。
const COUNT_LABELS: Record<string, string> = {
  companies: "公司档案",
  theses: "投资逻辑",
  evidences: "证据",
  research_events: "事件记录",
  portfolios: "组合",
  trades: "交易流水",
  record_revisions: "版本记录",
  thesis_reviews: "复核记录",
  valuations: "我的估值",
  management_promises: "承诺台账",
  counter_hits: "反证命中",
  supply_chain_links: "产业链条目",
  research_reports: "研究报告",
  research_tasks: "研究任务",
  research_task_items: "任务候选",
  industry_chain_themes: "产业链主题",
  industry_chain_stages: "产业链环节",
  industry_chain_nodes: "产业链节点",
  industry_chain_edges: "产业链关系",
  industry_chain_company_positions: "公司在链上的位置",
  method_assessments: "方法论自评",
  screen_strategies: "自建选股策略",
  rule_terms: "分级词表",
  inbox_corrections: "分级纠正",
  news_feeds: "订阅源",
  user_settings: "偏好设置",
  market_snapshots: "行情快照",
  price_bars: "日线",
  financial_periods: "财务报告期",
  company_profiles: "公司简况",
  company_calendar_events: "公司大事",
  provider_syncs: "数据源状态",
};

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function BackupPage() {
  // 直接输入网址进来的非站主，此前会撞一屏 403。**给一句话，不给一堆错误。**
  const ownerHere = useIsOwner();
  const [summary, setSummary] = useState<LocalDataSummary | null>(null);
  const [backups, setBackups] = useState<BackupManifest[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [note, setNote] = useState("");

  async function reload() {
    const [nextSummary, nextBackups] = await Promise.all([getLocalData(), getBackups()]);
    setSummary(nextSummary);
    setBackups(nextBackups);
  }

  useEffect(() => {
    // 不是站主就别去问那几个接口了 —— 问了也只会拿回三个 403。
    if (ownerHere !== true) { if (ownerHere === false) setLoading(false); return; }
    let current = true;
    reload().catch((caught) => { if (current) setError(errorMessage(caught)); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [ownerHere]);

  async function backupNow() {
    setBusy("backup"); setError(""); setMessage("");
    try {
      const created = await createBackup(note);
      setNote("");
      await reload();
      setMessage(`已备份为 ${created.name}，共 ${Object.values(created.counts).reduce((total, value) => total + value, 0)} 条记录。`);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }

  async function restore(name: string) {
    const confirmed = await confirmAction({
      title: `将用备份 ${name} 覆盖当前本地数据库`,
      detail: "当前所有公司、判断、证据、持仓都会被这份快照替换。恢复前会自动为当前数据再存一份备份，可以再退回来。",
      confirmText: "覆盖并恢复", danger: true,
    });
    if (!confirmed) return;
    setBusy(name); setError(""); setMessage("");
    try {
      const result = await restoreBackup(name);
      await reload();
      const restoredTotal = Object.values(result.restored_counts).reduce((total, value) => total + value, 0);
      setMessage(result.verified
        ? `已恢复 ${name}：条目数校验通过，共 ${restoredTotal} 条；恢复前的数据已存为 ${result.safety_backup}。`
        : `已恢复 ${name}，但条目数与备份不一致：${Object.entries(result.mismatched).map(([table, item]) => `${COUNT_LABELS[table] ?? table} 备份 ${item.backup} / 恢复后 ${item.restored}`).join("；")}。`);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }

  const authored = summary ? Object.entries(summary.authored_counts) : [];
  const sourced = summary ? Object.entries(summary.source_counts) : [];
  const authoredTotal = authored.reduce((total, [, value]) => total + value, 0);

  if (ownerHere === false) {
    return <section className="page-intro archive-intro">
      <div><span className="section-kicker">LOCAL DATA</span><h1>备份与恢复</h1>
        <p>备份和恢复作用于整个数据库 —— 恢复会用一份快照覆盖所有人的记录，
           所以只有站主能做。你自己的研究记录不受影响。</p></div>
    </section>;
  }

  return <>
    <section className="page-intro archive-intro">
      <div><span className="section-kicker">LOCAL DATA</span><h1>备份与恢复</h1><p>研究记录写在本机，不会自动上传。备份、导出和恢复都由你手动触发。</p></div>
      <div className="local-stamp"><span>BACKUPS</span><strong>{summary?.backup_count ?? 0} 份备份</strong></div>
    </section>
    {error && <p className="form-error">{error}</p>}
    {message && <p className="restore-message">{message}</p>}
    {loading && <div className="empty-state page-loading">正在读取本地数据状态…</div>}
    {!loading && summary?.freshness?.stale && <section className="panel stale-panel">
      {/* 缺列不会报错，只会让下游判断悄悄失去依据——然后表现成「模型说数据不足」
          或「策略筛不出东西」，把人引向完全错误的方向。所以要主动报，
          而且要跟条目数并排：表里 5535 只股票看着很齐全，缺的是列。 */}
      <div className="panel-heading compact">
        <div><span className="eyebrow">数据比代码旧</span><h2>有几列代码在写，库里却基本没有</h2>
          <p>{summary.freshness.note}</p></div>
      </div>
      <table className="assess-evidence">
        <tbody>
          {summary.freshness.findings.map((f) => <tr key={`${f.table}.${f.column}`}>
            <th scope="row">{f.table}.{f.column}</th>
            <td>{f.filled} / {f.total}</td>
            <td><em>{f.ratio}%</em></td>
          </tr>)}
        </tbody>
      </table>
      <ul className="assess-steps">
        {summary.freshness.actions.map((a) => <li key={a.table}>
          <strong>{a.columns.join("、")}</strong>：{a.how}
        </li>)}
      </ul>
    </section>}

    <SyncStripPanel />

    {!loading && summary && <>
      <section className="metric-strip portfolio-metrics" aria-label="本地数据概要">
        <article className="metric metric--plain"><span>手写研究记录</span><strong>{authoredTotal} 条</strong><small>逻辑、证据、事件、交易与版本</small></article>
        <article className="metric metric--plain"><span>数据库体积</span><strong>{formatBytes(summary.database_size)}</strong><small>{summary.database_path}</small></article>
        <article className="metric metric--plain"><span>结构版本</span><strong>v{summary.schema_version}</strong><small>{summary.schema_version === summary.expected_schema_version ? "与当前程序一致" : `程序期望 v${summary.expected_schema_version}，重启 API 会自动迁移`}</small></article>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div><span className="eyebrow">不可再生的部分</span><PanelTitle hint="行情、日线、财务和公司简况可以随时重新同步；手写记录一旦丢失无法重建。">本地记录明细</PanelTitle></div>
          <a className="page-action" href={apiUrl("/api/v1/export")}>导出 JSON</a>
        </div>
        <div className="count-grid">
          {authored.map(([table, value]) => <article key={table} className="count-cell count-cell--authored"><span>{COUNT_LABELS[table] ?? table}</span><strong>{value}</strong></article>)}
          {sourced.map(([table, value]) => <article key={table} className="count-cell"><span>{COUNT_LABELS[table] ?? table}</span><strong>{value}</strong></article>)}
        </div>
        {/* **这句话必须跟 backup.AUTHORED_TABLES 说的是同一件事。**
            它以前写的是「只包含你手写的记录与版本历史」，读起来是"少的只有
            能重新同步的东西"——而当时产业链、承诺台账、复核记录、我的估值
            一条都不在里面。一句读着像保证的话，不成立比不说更糟。 */}
        <p className="market-history-note">
          导出的 JSON 是上面标出来的那些「你写的」——公司、判断、证据、交易、复核、估值、
          承诺、产业链、词表与偏好，连同版本历史。行情、日线、财报、公告这类能重新同步的
          来源数据不在其中，任务流水与简报也不在（重跑就有）。备份文件则是整库快照，什么都有。
        </p>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div><span className="eyebrow">整库快照</span><h2>备份</h2><p>备份保存在 {summary.backup_directory}，可下载后另存到别处。</p></div>
          <div className="intro-actions">
            <input className="backup-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="给这次备份写个说明（可选）" aria-label="备份说明" />
            <button className="page-action" onClick={() => void backupNow()} disabled={busy !== ""}>{busy === "backup" ? "正在备份…" : "立即备份"}</button>
          </div>
        </div>
        {backups.length === 0 ? <div className="market-history-empty">还没有备份。建议在每次大改研究记录前先备份一次。</div> : <div className="backup-list">
          {backups.map((backup) => <article className="backup-row" key={backup.name}>
            <div>
              <strong>{backup.name}</strong>
              <span>{formatDateTime(backup.created_at)} · {formatBytes(backup.size)} · 结构 v{backup.schema_version} · {backup.reason}</span>
              {backup.note && <em>{backup.note}</em>}
            </div>
            <span className="backup-counts">{Object.entries(backup.counts).filter(([table]) => COUNT_LABELS[table] && ["companies", "theses", "evidences", "research_events", "trades"].includes(table)).map(([table, value]) => `${COUNT_LABELS[table]} ${value}`).join(" · ")}</span>
            <div className="backup-actions">
              <a className="text-button" href={apiUrl(`/api/v1/backups/${encodeURIComponent(backup.name)}/download`)}>下载</a>
              <button className="text-button" onClick={() => void restore(backup.name)} disabled={busy !== ""}>{busy === backup.name ? "正在恢复…" : "恢复到此备份"}</button>
            </div>
          </article>)}
        </div>}
        <p className="market-history-note">恢复会用备份覆盖当前数据库；系统会先把当前数据自动备份一份，并在恢复后逐表校验条目数。</p>
      </section>
    </>}
  </>;
}

const VERDICT_OPTIONS: Array<{ value: ReviewVerdict; label: string; detail: string }> = [
  { value: "supported", label: "仍然成立", detail: "新事实继续支持当初的判断" },
  { value: "challenged", label: "受到挑战", detail: "出现了与判断相反的重要事实" },
  { value: "broken", label: "已被推翻", detail: "当初写下的反证条件已经发生" },
  { value: "watching", label: "维持观察", detail: "证据还不足以下结论" },
];

function ReviewConclusionForm({ context, onSaved }: { context: ThesisReviewContext; onSaved: () => Promise<void> }) {
  const [verdict, setVerdict] = useState<ReviewVerdict>("watching");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const thesis = context.thesis;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError("");
    const form = new FormData(event.currentTarget);
    const nextDate = String(form.get("next_review_date") ?? "");
    try {
      await createThesisReview(Number(thesis.id), {
        verdict,
        note: String(form.get("note") ?? ""),
        next_review_date: nextDate || null,
        next_review_trigger: String(form.get("next_review_trigger") ?? ""),
      });
      await onSaved();
    } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); }
  }
  return <form className="inline-form review-form" onSubmit={submit}>
    <div className="verdict-group" role="radiogroup" aria-label="复核结论">
      {VERDICT_OPTIONS.map((option) => <button
        key={option.value}
        type="button"
        role="radio"
        aria-checked={verdict === option.value}
        className={`verdict-option${verdict === option.value ? " verdict-option--on" : ""}`}
        onClick={() => setVerdict(option.value)}
      ><strong>{option.label}</strong><em>{option.detail}</em></button>)}
    </div>
    <label>结论依据（这次看到了什么，为什么得出这个结论）
      <textarea name="note" rows={3} required placeholder="用事实写：哪条证据或事件支持/挑战了当初的判断。不要写目标价或操作计划。" />
    </label>
    <div className="form-grid compact-grid">
      <label>下次复核日期<input type="date" name="next_review_date" defaultValue={String(thesis.next_review_date ?? "")} /></label>
      <label>下次复核触发条件<input name="next_review_trigger" defaultValue={String(thesis.next_review_trigger ?? "")} placeholder="例如：2026 年三季报" /></label>
    </div>
    {error && <p className="form-error">{error}</p>}
    <div className="form-actions"><button className="page-action" type="submit" disabled={saving}>{saving ? "正在保存…" : "保存复核结论"}</button></div>
    <p className="form-note">结论会作为逻辑的新版本追加，并记录当时的价格、估值分位与持仓盈亏；旧判断不会被覆盖。</p>
  </form>;
}

function ReviewWorkbench({ thesisId, onSaved, onOpenCompany }: { thesisId: number; onSaved: () => Promise<void>; onOpenCompany: (id: number) => void }) {
  const [context, setContext] = useState<ThesisReviewContext | null>(null);
  const [error, setError] = useState("");
  async function load() {
    try { setContext(await getReviewContext(thesisId)); setError(""); }
    catch (caught) { setError(errorMessage(caught)); }
  }
  useEffect(() => { void load(); }, [thesisId]);
  if (error) return <p className="form-error">{error}</p>;
  if (!context) return <div className="empty-state">正在打开复核材料…</div>;

  const thesis = context.thesis;
  const original = context.revisions[0];
  const newEvidences = context.evidences.filter((item) => item.since_last_review);
  const newEvents = context.events.filter((item) => item.since_last_review);
  const position = context.position;
  return <div className="review-workbench">
    <div className="review-head">
      <div className="review-head-main">
        <span className="review-kicker">正在复核</span>
        <button className="text-button" onClick={() => onOpenCompany(Number(thesis.company_id))}>{String(thesis.company_name)} · {String(thesis.symbol)}</button>
        <h3>这条判断还成立吗？</h3>
        <p className="review-counter-condition"><strong>反证条件：</strong>{String(thesis.counter_condition) || "当初没有写下反证条件"}</p>
      </div>
      <div className="review-head-status"><StatusBadge status={thesis.status as ThesisStatus} /><span>{context.reviews.length > 0 ? `已复核 ${context.reviews.length} 次` : "从未复核"}</span></div>
    </div>

    <div className="review-columns">
      <section className="review-block review-block--judgment">
        <h4>当初的判断</h4>
        {original ? <>
          <details className="review-original-details">
            <summary><span>{String(original.snapshot.claim ?? "")}</span><em>展开全文</em></summary>
            <p className="review-quote">{String(original.snapshot.claim ?? "")}</p>
          </details>
          <p className="review-meta">建立于 {formatDateTime(original.created_at)} · 当时状态 {statusCopy[(original.snapshot.status as ThesisStatus) ?? "watching"]?.label ?? "—"}</p>
          {context.revisions.length > 1 && <p className="review-meta">此后修订 {context.revisions.length - 1} 次，最近一次：{context.revisions[context.revisions.length - 1].change_note || "未写说明"}</p>}
        </> : <p className="review-meta">没有留下版本记录。</p>}
        {context.trades.length > 0 && <div className="review-trades">
          {context.trades.map((trade) => <div key={trade.id}>
            <span className={`trade-side trade-side--${trade.side}`}>{TRADE_SIDE_LABEL[trade.side]}</span>
            <b>{trade.trade_date} · {tradeFigures(trade)}</b>
            <p>{trade.rationale}</p>
            {trade.expectation && <em>当时预期：{trade.expectation}</em>}
          </div>)}
        </div>}
      </section>

      <section className="review-block review-block--facts">
        <h4>上次复核之后的新事实</h4>
        <div className="review-facts-summary"><strong>{newEvidences.length + newEvents.length}</strong><span>条新事实</span><em>{context.evidences.length + context.events.length} 条档案记录</em></div>
        {newEvidences.length === 0 && newEvents.length === 0 && <p className="review-meta">这段时间没有归档新的证据或事件。</p>}
        {newEvidences.map((item) => <div className={`review-fact review-fact--${item.polarity}`} key={`e${item.id}`}>
          <span>{item.polarity === "support" ? "支持" : item.polarity === "counter" ? "反证" : "中性"} · {item.source_name} · {item.occurred_at.slice(0, 10)}</span>
          <p>{item.excerpt}</p>
          {item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">打开来源</a>}
        </div>)}
        {newEvents.map((item) => <div className="review-fact" key={`v${item.id}`}>
          <span>{item.category} · {item.importance === "high" ? "高" : item.importance === "medium" ? "中" : "低"} · {item.occurred_at.slice(0, 10)}</span>
          <p>{item.title}</p>
        </div>)}
        {(context.evidences.length > newEvidences.length || context.events.length > newEvents.length) &&
          <p className="review-meta">另有 {context.evidences.length - newEvidences.length} 条更早的证据、{context.events.length - newEvents.length} 条更早的事件。</p>}
      </section>

      <section className="review-block review-block--figures">
        <h4>期间的价格与估值</h4>
        <dl className="review-figures">
          <div><dt>最新价</dt><dd>{context.price.latest === null ? "行情未同步" : formatMoney(context.price.latest)}</dd></div>
          <div><dt>近 20 日</dt><dd className={pnlClass(context.price.price_20d_change)}>{signedPercentText(context.price.price_20d_change)}</dd></div>
          <div><dt>年初至今</dt><dd className={pnlClass(context.price.ytd_change)}>{signedPercentText(context.price.ytd_change)}</dd></div>
          <div><dt>近一年</dt><dd className={pnlClass(context.price.one_year_change)}>{signedPercentText(context.price.one_year_change)}</dd></div>
          {context.valuation.map((item) => <div key={item.label}>
            <dt>{item.label}</dt>
            <dd>{item.current === null ? "未同步" : item.current.toFixed(2)}{item.percentile === null ? "" : ` · 5 年分位 ${item.percentile.toFixed(1)}%`}</dd>
          </div>)}
          {position && <>
            <div><dt>持仓</dt><dd>{position.weight_percent !== null || position.weight !== null
              ? `${(position.weight_percent ?? position.weight ?? 0).toFixed(1)}% 仓位${position.average_cost === null ? "" : ` · 成本 ${formatMoney(position.average_cost)}`}`
              : position.shares > 0
                ? `${position.shares.toLocaleString("zh-CN")} 股 · 成本 ${formatMoney(position.average_cost)}`
                : "已清仓"}</dd></div>
            <div><dt>盈亏</dt><dd className={pnlClass(position.unrealized_pnl)}>浮动 {formatSigned(position.unrealized_pnl)} · 已实现 {formatSigned(position.realized_pnl)}</dd></div>
          </>}
        </dl>
        <p className="review-meta">分位只说明当前值在历史样本中的位置，不代表贵或便宜。</p>
      </section>
    </div>

    <ReviewConclusionForm context={context} onSaved={async () => { await load(); await onSaved(); }} />

    {context.reviews.length > 0 && <section className="review-history">
      <h4>历次复核</h4>
      {context.reviews.map((review) => <article key={review.id}>
        <div><span className={`verdict-chip verdict-chip--${review.verdict}`}>{review.verdict_label ?? review.verdict}</span><time>{formatDateTime(review.created_at)}</time></div>
        <p>{review.note}</p>
        <em>
          {review.previous_status !== review.new_status ? `状态 ${statusCopy[review.previous_status as ThesisStatus]?.label} → ${statusCopy[review.new_status as ThesisStatus]?.label} · ` : ""}
          当时价格 {review.price_at_review === null ? "—" : formatMoney(review.price_at_review)}
          {review.pe_percentile_at_review === null ? "" : ` · PE 分位 ${review.pe_percentile_at_review.toFixed(1)}%`}
          {review.counter_evidence ? ` · 期间反证 ${review.counter_evidence} 条` : ""}
          {review.next_review_date ? ` · 下次复核 ${review.next_review_date}` : ""}
        </em>
      </article>)}
    </section>}
  </div>;
}

/** 分级引擎从你的纠错里学到了什么。
 *
 * 纠错信号本来就在日常动作里：把判成「程序性」的归档为证据，或把判成「高」的
 * 直接忽略——这两件事你每天都在做，只是以前没人记下来。
 *
 * **但学到的词不自动生效。** 规则词表直接决定几百条公告的去向，一个学歪的词会
 * 静悄悄地把一整类实质公告扔进程序性堆里，页面上看不出来，只会觉得「最近公告怎么变少了」。
 * 所以这里只摆出证据，加不加是你的事。 */

const ACTION_TONE: Record<string, string> = {
  // 「命中」用最重的色：别的待办是「该去看看」，它是「你自己写下的卖出条件被触发了」
  // ——这一条不处理就等于假装没看见。
  命中: "hit", 反证: "bad", 复核: "warn", 公告: "info", 补全: "soft", 体检: "soft", 无: "calm",
};

/** 决策看板：每只票一行，回答「这一只现在卡在哪一步」。
 *
 * 与今日简报的分工：简报是模型写的一段叙述，适合早上通读；看板是结构化状态表，
 * 适合逐只处理。两者读同一批事实。
 *
 * **不给买卖信号，这是刻意的。** 同类项目会给评分与买卖建议，那需要一个
 * 「什么价位算贵、什么形态算买点」的模型——而这个产品从第一行代码起就不做那件事。
 * 所以每一格都是已经发生的事实或已经到期的约定，没有一格是对未来的预测。 */
/** 看板本身。**board 由上层传入**：一页纸和这里读的是同一份数据，
 *  各取一次的话，用户点了「检查反证」之后同一个数字会在同一屏上出现两个值。 */
function DecisionBoardPanel({ board, error, onReload, onOpenCompany, uncompared }: {
  board: DecisionBoard | null; error: string; onReload: () => void;
  onOpenCompany: (id: number) => void;
  /** 还有多少条公告没跟认错条件比对过。0 与「比过了没事」是两回事，见下面那段。 */
  uncompared: number;
}) {
  const [onlyTodo, setOnlyTodo] = useState(true);
  const [checking, setChecking] = useState(false);
  const [checkNote, setCheckNote] = useState("");

  async function runCheck() {
    setChecking(true); setCheckNote("");
    try {
      const result = await checkCounterHits();
      setCheckNote(result.note);
      onReload();                 // 命中会改「今天该做什么」，两处一起重新读
    } catch (caught) { setCheckNote(errorMessage(caught)); } finally { setChecking(false); }
  }

  if (error) return null;         // 错误已经由上层报过一次，这里不重复
  if (!board) return null;

  const rows = onlyTodo ? board.rows.filter((row) => row.action_kind !== "无") : board.rows;
  const blankCount = board.rows.filter((row) => row.action_kind === "补全").length;
  return <section className="panel">
    <div className="panel-heading compact">
      <div><span className="eyebrow">决策看板</span><h2>每只票现在卡在哪一步</h2>
        <p>{board.todo_count} 只有待办 · {board.held_count} 只有持仓 · 共 {board.rows.length} 只{blankCount > 0 ? ` · 待写判断 ${blankCount}` : ""}</p></div>
      <div className="chart-range-group" role="group" aria-label="筛选">
        <button type="button" className={`chart-range${onlyTodo ? " chart-range--on" : ""}`}
          onClick={() => setOnlyTodo(true)}>只看待办<em>{board.todo_count}</em></button>
        <button type="button" className={`chart-range${!onlyTodo ? " chart-range--on" : ""}`}
          onClick={() => setOnlyTodo(false)}>全部<em>{board.rows.length}</em></button>
      </div>
    </div>

    {/* 反证比对：把还没核验的公告拿去和你写下的反证条件逐条比。
        判定从严——误报一次，下次真命中你就不信它了。 */}
    {/* **「还没比对过 N 条」要写出来。** 只给「命中 0」的话，
        "比过了、你的认错条件一条都没被撞上"和"压根没比过"在页面上一模一样，
        而后者才是常态——比对要手动点，而且要过模型、默认不会自动跑。 */}
    <div className="board-check">
      <button className="text-button" disabled={checking} onClick={() => void runCheck()}>
        {checking ? "正在比对…" : "拿新公告比对我写的反证条件"}
      </button>
      {uncompared > 0 && !checkNote &&
        <span className="muted-label">还有 {uncompared} 条公告没比对过</span>}
      {checkNote && <span className="muted-label">{checkNote}</span>}
    </div>

    {rows.length === 0 && <div className="empty-state">全部处理完了，今天没有需要动手的。</div>}
    <div className="board-rows">
      {rows.map((row) => <button className="board-row" key={row.company_id}
        onClick={() => onOpenCompany(row.company_id)}>
        <span className={`board-flag board-flag--${ACTION_TONE[row.action_kind] ?? "calm"}`}>{row.action_kind}</span>
        <span className="board-name">
          <b>{row.name}</b><em>{row.symbol} · {row.industry || "行业未标注"}</em>
        </span>
        <span className="board-price">
          {row.latest_price === null ? <em>无行情</em> : <>
            <b>{row.latest_price.toFixed(2)}</b>
            <em className={pnlClass(row.change_percent)}>{signedPct(row.change_percent)}</em>
          </>}
        </span>
        <span className="board-facts">
          {row.held && <i>持仓 {row.weight === null ? "—" : `${row.weight.toFixed(1)}%`}
            {row.unrealized_percent !== null && `　浮动 ${signedPct(row.unrealized_percent)}`}</i>}
          {row.thesis_count > 0 && <i>逻辑 {row.thesis_count} 条{row.method_name ? `（${row.method_name}）` : ""}</i>}
          {row.counter_evidence > 0 && <i>反证 {row.counter_evidence}</i>}
          {row.pending_events > 0 && <i>待核验 {row.pending_events}</i>}
          {row.next_review_date && <i>复核 {row.next_review_date}</i>}
        </span>
        <span className="board-action">{row.action}</span>
      </button>)}
    </div>
    <p className="form-note">{board.boundary}</p>
  </section>;
}

function signedPct(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function InboxLearningPanel() {
  const [data, setData] = useState<InboxLearning | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function reload() {
    try { setData(await getInboxLearning()); setError(""); }
    catch (caught) { setError(errorMessage(caught)); }
  }
  useEffect(() => { void reload(); }, []);

  async function confirm(term: string, relevance: string) {
    setBusy(term);
    try { await saveRuleTerm(term, relevance); await reload(); }
    catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(""); }
  }
  async function remove(term: string) {
    setBusy(term);
    try { await deleteRuleTerm(term); await reload(); }
    catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(""); }
  }

  if (!data) return null;
  if (data.total === 0 && data.terms.length === 0) {
    return <section className="panel">
      <div className="panel-heading compact"><div><span className="eyebrow">分级学习</span><PanelTitle hint="你纠正过的分级会被记下来，攒够几条就提议加进规则——加不加由你定。">从你的纠错里学</PanelTitle></div></div>
    </section>;
  }

  return <section className="panel">
    <div className="panel-heading compact">
      <div><span className="eyebrow">分级学习</span><h2>从你的纠错里学</h2>
        <p>已经记下 {data.total} 次纠错。下面是从中挖出来的候选词，
           **确认之后才会生效**——规则词表直接决定几百条公告的去向，学歪一个词是看不出来的。</p></div>
    </div>
    {error && <p className="form-error">{error}</p>}
    {data.suggestions.length > 0 && <div className="learn-rows">
      {data.suggestions.map((item) => <div className="learn-row" key={`${item.term}-${item.relevance}`}>
        <b>「{item.term}」</b>
        <span className={`grade-chip grade-chip--${item.relevance}`}>{item.relevance}</span>
        <em>在你改过的 {item.corrections} 条标题里出现{item.also_in_agreed > 0 ? `；没改过的标题里也出现 ${item.also_in_agreed} 条` : "；没改过的标题里一条都没有"}</em>
        <button className="text-button" disabled={busy !== ""} onClick={() => void confirm(item.term, item.relevance)}>
          {busy === item.term ? "…" : "加进规则"}
        </button>
      </div>
)}
    </div>}
    {data.suggestions.length === 0 && data.total > 0 &&
      <p className="form-note">纠错记下了，但还挖不出有区分力的词——同一个词要在几条纠错里都出现，且在你没改过的标题里少见，才值得提议。</p>}
    {data.terms.length > 0 && <>
      <h4 className="learn-title">已生效的词（{data.terms.length}）</h4>
      <div className="learn-rows">
        {data.terms.map((term) => <div className="learn-row" key={term.term}>
          <b>「{term.term}」</b>
          <span className={`grade-chip grade-chip--${term.relevance}`}>{term.relevance}</span>
          <em>{term.topic}{term.note ? ` ｜ ${term.note}` : ""}</em>
          <button className="text-button" disabled={busy !== ""} onClick={() => void remove(term.term)}>移除</button>
        </div>)}
      </div>
    </>}
  </section>;
}

function ReviewsPage({ onOpenCompany, onChanged }: { onOpenCompany: (id: number) => void; onChanged: () => Promise<void> }) {
  const [queue, setQueue] = useState<ReviewQueueItem[]>([]);
  const [allTheses, setAllTheses] = useState<ThesisListItem[]>([]);
  const [activeThesis, setActiveThesis] = useState<number | null>(null);
  const [activeLibraryThesis, setActiveLibraryThesis] = useState<number | null>(null);
  const [libraryExpanded, setLibraryExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function reload() {
    const [nextQueue, nextAll] = await Promise.all([getReviewQueue(), getAllTheses()]);
    setQueue(nextQueue);
    setAllTheses(nextAll);
  }
  useEffect(() => {
    let current = true;
    reload().catch((caught) => { if (current) setError(errorMessage(caught)); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, []);

  return <>
    <section className="page-intro archive-intro review-intro">
      <div><span className="section-kicker">REVIEW DESK · 长期判断</span><h1>复核工作台</h1></div>
      <div className={`review-due-stamp${queue.length > 0 ? " review-due-stamp--active" : ""}`}><span>待复核</span><strong>{queue.length}</strong><em>{queue.length > 0 ? "先看这些" : "暂无到期"}</em></div>
    </section>
    {error && <p className="form-error">{error}</p>}
    {loading && <div className="empty-state page-loading">正在读取复核队列…</div>}
    {!loading && <>
      <section className="panel">
        <div className="panel-heading compact"><div><span className="eyebrow">到期或出现新事实</span><PanelTitle hint="触发条件：复核日期到期、关联交易到期、出现新的反证或高重要度事件、或距上次复核超过 90 天。">先处理这些</PanelTitle></div></div>
        <div className="review-queue">
          {queue.length === 0 && <div className="empty-state">
            <div className="review-empty-mark" aria-hidden="true">✓</div>
            <div><strong>现在没有需要复核的判断</strong><p>到期或出现新反证时，会自动排到这里。</p></div>
            <a className="review-empty-link" href="#all-theses" onClick={(event) => {
              event.preventDefault();
              setLibraryExpanded(true);
              window.setTimeout(() => document.getElementById("all-theses")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
            }}>查看全部判断 <span aria-hidden="true">→</span></a>
          </div>}
          {queue.map((item) => <article className={`review-queue-card${activeThesis === item.thesis_id ? " review-queue-card--open" : ""}`} key={item.thesis_id}>
            <div className="review-queue-head">
              <StatusBadge status={item.status} />
              <button className="text-button" onClick={() => onOpenCompany(item.company_id)}>{item.company_name} · {item.symbol}</button>
              <span className="review-queue-meta">{item.last_reviewed_at ? `上次复核 ${item.last_reviewed_at.slice(0, 10)}` : "从未复核"} · 已复核 {item.review_count} 次{item.has_position ? " · 有持仓" : ""}</span>
              <button className="page-action" onClick={() => setActiveThesis(activeThesis === item.thesis_id ? null : item.thesis_id)}>{activeThesis === item.thesis_id ? "收起" : "开始复核"}</button>
            </div>
            <h3>{item.claim}</h3>
            <div className="review-reasons">{item.reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>
            {activeThesis === item.thesis_id && <ReviewWorkbench thesisId={item.thesis_id} onOpenCompany={onOpenCompany} onSaved={async () => { await reload(); await onChanged(); }} />}
          </article>)}
        </div>
      </section>

      {/* **「投资逻辑 5 条」必须能点到这里。**
          原来那张卡片指向本页，而本页只放"该重看的"——不到复核期时是空的，
          于是使用者看到的是：我有 5 条判断，点一下，什么都没有。
          判断是这个产品唯一的核心产出，却没有一处能整体看到它。 */}
      <details className="panel review-library" id="all-theses" open={libraryExpanded} onToggle={(event) => setLibraryExpanded(event.currentTarget.open)}>
        <summary className="review-library-summary">
          <span className="review-library-title" role="heading" aria-level={2}>
            <strong>全部判断</strong>
            <em>{allTheses.length} 条 · 按状态查看</em>
          </span>
          <span className="review-library-toggle">{libraryExpanded ? "收起" : "展开"}</span>
        </summary>
        {allTheses.length === 0
          ? <div className="empty-state">还没有长期判断。从公司档案写下第一条可验证的主张。</div>
          : <ul className="thesis-list">
            {allTheses.map((item) => {
              const libraryOpen = activeLibraryThesis === item.id;
              return <li key={item.id} className={`thesis-list-row${libraryOpen ? " thesis-list-row--open" : ""}`}>
                <div className="thesis-list-main">
                  <div className="thesis-card-top">
                    <button className="text-button thesis-company" onClick={() => onOpenCompany(item.company_id)}>
                      <strong>{item.company_name}</strong> <span className="cr-symbol">{item.symbol}</span>
                    </button>
                    <StatusBadge status={item.status} />
                  </div>
                  <details className="thesis-claim-details">
                    <summary>
                      <span className="thesis-claim-preview">{item.claim}</span>
                      <span className="thesis-expand-label">展开全文</span>
                    </summary>
                    <div className="thesis-claim-body">
                      <p>{item.claim}</p>
                      <div className="thesis-condition"><span>反证条件</span><p>{item.counter_condition || "还没有写下反证条件"}</p></div>
                    </div>
                  </details>
                  <div className="thesis-signal-row">
                    {item.no_counter_condition && <em className="thesis-flag">缺少反证条件</em>}
                    {item.never_reviewed && <em className="thesis-flag">从未复核</em>}
                    <span className="thesis-counts">反证 {item.counter_evidence} · 支持 {item.support_evidence} · 复核 {item.review_count} 次</span>
                  </div>
                </div>
                <div className="thesis-list-actions">
                  <button className="text-button" onClick={() => setActiveLibraryThesis(libraryOpen ? null : item.id)}>{libraryOpen ? "收起复核" : "开始复核"}</button>
                  <button className="text-button thesis-company-link" onClick={() => onOpenCompany(item.company_id)}>公司档案</button>
                </div>
                {libraryOpen && <div className="thesis-inline-workbench"><ReviewWorkbench thesisId={item.id} onOpenCompany={onOpenCompany} onSaved={async () => { await reload(); await onChanged(); }} /></div>}
              </li>;
            })}
          </ul>}
      </details>
    </>}
  </>;
}

function peerCell(value: number | null, unit: "%" | "x" = "%"): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return unit === "x" ? value.toFixed(2) : `${value.toFixed(1)}%`;
}

function PeerAggregateRow({ label, aggregate, tone }: { label: string; aggregate: IndustryAggregate; tone: "average" | "median" }) {
  const coverage = (key: string) => `${aggregate.coverage[key] ?? 0}/${aggregate.sample_count} 家有值`;
  return <div className={`peer-row peer-row--aggregate peer-row--${tone}`} role="row">
    <span data-label="公司"><strong>{label}</strong><em>全 A {aggregate.sample_count} 家 · 按可用值</em></span>
    <span data-label="最新价" title={coverage("latest_price")}>{aggregate.latest_price === null ? "—" : formatMoney(aggregate.latest_price)}</span>
    <span data-label="PE(TTM)" title={coverage("pe_ttm")}>{peerCell(aggregate.pe_ttm, "x")}</span>
    <span data-label="PE 5 年分位" title={coverage("pe_ttm_percentile")}>{peerCell(aggregate.pe_ttm_percentile)}</span>
    <span data-label="PB" title={coverage("pb")}>{peerCell(aggregate.pb, "x")}</span>
    <span data-label="PB 5 年分位" title={coverage("pb_percentile")}>{peerCell(aggregate.pb_percentile)}</span>
    <span data-label="年报 ROE" title={coverage("roe_estimate")}>{peerCell(aggregate.roe_estimate)}</span>
    <span data-label="毛利率" title={coverage("gross_margin")}>{peerCell(aggregate.gross_margin)}</span>
    <span data-label="净利率" title={coverage("net_margin")}>{peerCell(aggregate.net_margin)}</span>
    <span data-label="现金含量" title={coverage("cash_conversion")}>{peerCell(aggregate.cash_conversion)}</span>
    <span data-label="资产负债率" title={coverage("debt_ratio")}>{peerCell(aggregate.debt_ratio)}</span>
    <span data-label="营收同比" title={coverage("revenue_growth")}>{peerCell(aggregate.revenue_growth)}</span>
  </div>;
}

function PeerTable({ comparison, activeCompanyId, onOpenCompany }: { comparison: IndustryComparison; activeCompanyId?: number; onOpenCompany: (id: number) => void }) {
  return <div className="peer-table" role="table" aria-label="同业对照">
    <div className="peer-row peer-row--head" role="row">
      <span>公司</span><span>最新价</span><span>PE(TTM)</span><span>PE 5 年分位</span><span>PB</span><span>PB 5 年分位</span>
      <span>年报 ROE</span><span>毛利率</span><span>净利率</span><span>现金含量</span><span>资产负债率</span><span>营收同比</span>
    </div>
    <PeerAggregateRow label="行业平均" aggregate={comparison.average} tone="average" />
    <PeerAggregateRow label="行业中位" aggregate={comparison.median} tone="median" />
    <div className="peer-row peer-row--section" role="row"><span>研究池公司 <em>{comparison.company_count} 家</em></span></div>
    {comparison.companies.map((company) => {
      const pe = company.valuation.pe_ttm;
      const pb = company.valuation.pb;
      const finance = company.financials;
      return <div className={`peer-row${company.id === activeCompanyId ? " peer-row--active" : ""}`} role="row" key={company.id}>
        <span data-label="公司">
          <button className="text-button" onClick={() => onOpenCompany(company.id)}>{company.name}</button>
          <em>{company.symbol}{company.is_watched ? "" : " · 已移出"}</em>
        </span>
        <span data-label="最新价">{company.latest_price === null ? "未同步" : formatMoney(company.latest_price)}</span>
        <span data-label="PE(TTM)" title={pe.note ?? ""}>{peerCell(pe.current, "x")}</span>
        <span data-label="PE 5 年分位" title={pe.note ?? ""}>{peerCell(pe.percentile)}</span>
        <span data-label="PB" title={pb.note ?? ""}>{peerCell(pb.current, "x")}</span>
        <span data-label="PB 5 年分位" title={pb.note ?? ""}>{peerCell(pb.percentile)}</span>
        <span data-label="年报 ROE" title={finance.roe_report_date ? `报告期 ${finance.roe_report_date}` : ""}>{peerCell(finance.roe_estimate)}</span>
        <span data-label="毛利率">{peerCell(finance.gross_margin)}</span>
        <span data-label="净利率">{peerCell(finance.net_margin)}</span>
        <span data-label="现金含量">{peerCell(finance.cash_conversion)}</span>
        <span data-label="资产负债率">{peerCell(finance.debt_ratio)}</span>
        <span data-label="营收同比" title={finance.revenue_growth_basis ?? ""}>{peerCell(finance.revenue_growth)}</span>
      </div>;
    })}
    {comparison.companies.length === 0 && <div className="empty-state">这个行业下还没有公司。</div>}
  </div>;
}

function PeerComparisonPanel({ company }: { company: CompanyDetail }) {
  const [data, setData] = useState<PeerTableView | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    setData(null);
    getPeerTable(company.id)
      .then((next) => { if (current) { setData(next); setError(""); } })
      .catch((caught) => { if (current) setError(errorMessage(caught)); });
    return () => { current = false; };
  }, [company.id]);

  return <section className="panel peer-panel">
    <div className="panel-heading">
      <div>
        <span className="eyebrow">申万二级 · 全市场样本</span><h2>同业对照</h2>
      </div>
    </div>
    {error && <p className="form-error">{error}</p>}
    {!data && !error && <div className="trend-loading">正在读取同行数据…</div>}
    {data && <Suspense fallback={<div className="trend-loading">正在排表…</div>}>
      <MarketPeerTable data={data} />
    </Suspense>}
  </section>;
}

function IndustriesPage({ onOpenCompany }: { onOpenCompany: (id: number) => void }) {
  const [industries, setIndustries] = useState<IndustrySummary[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [comparison, setComparison] = useState<IndustryComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    getIndustries()
      .then((items) => {
        if (!current) return;
        setIndustries(items);
        const first = items.find((item) => item.name !== "待补充" && item.company_count > 1) ?? items[0];
        setActive(first?.name ?? null);
        setError("");
      })
      .catch((caught) => { if (current) setError(errorMessage(caught)); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, []);

  useEffect(() => {
    if (!active) return;
    let current = true;
    getIndustryComparison(active)
      .then((next) => { if (current) setComparison(next); })
      .catch((caught) => { if (current) setError(errorMessage(caught)); });
    return () => { current = false; };
  }, [active]);

  const pending = industries.find((item) => item.name === "待补充");
  // 这一页跟市场云图同类：一张对照图，扫的是「我的公司站在同行里哪个位置」。
  // 所以穿同一套深海舱。下面那张完整数据表留在纸面——那是要一行行读的东西。
  return <>
    {error && <p className="form-error">{error}</p>}
    {pending && pending.company_count > 0 && <p className="restore-message">还有 {pending.company_count} 家公司没有行业归属。在它们的档案里同步一次“公司简况”，行业会用巨潮的证监会分类自动回填。</p>}
    <section className="deck peer-deck" aria-labelledby="peer-title">
      <header className="deck-head">
        <div>
          <span className="deck-kicker">PEER VIEW · {industries.length} 个行业分类</span>
          <h1 id="peer-title">行业与同业对照</h1>
          <p>你建了档的公司，站在这个行业的哪个位置。刻度是全 A 同行，不是估值高低的结论。</p>
        </div>
      </header>
      {loading && <div className="peer-deck-empty">正在读取行业分类…</div>}
      {!loading && <div className="deck-rule peer-deck-picker">
        <div className="deck-pills" role="tablist" aria-label="选择行业">
          {industries.map((item) => <button
            key={item.name}
            role="tab"
            aria-selected={item.name === active}
            className={item.name === active ? "is-on" : ""}
            onClick={() => setActive(item.name)}
          >{item.name}<small>{item.company_count}</small></button>)}
        </div>
      </div>}
      {!loading && comparison && <div className="deck-rule peer-deck-base">
        <div className="screen-outcome-say">
          <span className="deck-kicker">全 A 行业基准</span>
          <strong>{comparison.industry || "全部行业"}</strong>
        </div>
        <dl className="screen-outcome-nums">
          <div><dt>A 股同行</dt><dd className="is-lit">{comparison.benchmark_company_count} 家</dd></div>
          <div><dt>已建档</dt><dd>{comparison.company_count} 家</dd></div>
          <div><dt>PE 中位</dt><dd>{peerCell(comparison.median.pe_ttm, "x")}</dd></div>
          <div><dt>ROE 中位</dt><dd>{peerCell(comparison.median.roe_estimate)}</dd></div>
        </dl>
      </div>}
      {!loading && comparison && <IndustryPositionMap comparison={comparison} />}
    </section>
    {!loading && comparison && <>
        <details className="panel industry-comparison-panel">
          <summary className="industry-table-summary">
            <span><strong>完整行业数据</strong><em>行业平均、中位与 {comparison.company_count} 家研究池公司</em></span>
            <b>展开 / 收起</b>
          </summary>
          <PeerTable comparison={comparison} onOpenCompany={onOpenCompany} />
          <details className="result-boundary"><summary>样本与行业口径</summary><p>{comparison.coverage}。{comparison.industry_basis}。数据：{comparison.benchmark_source || "全市场底座"}{comparison.benchmark_as_of ? ` · 截至 ${comparison.benchmark_as_of}` : ""}。空白表示尚未同步，不是 0。</p></details>
        </details>
      </>}
  </>;
}

function checkValue(check: ScreenCheck): string {
  if (check.actual === null) return "缺数据";
  if (check.field === "total_market_cap") return formatBillion(check.actual);
  if (check.field === "net_profit") return formatBillion(check.actual);
  if (["roe", "gross_margin", "revenue_growth", "net_profit_growth", "cash_ratio"].includes(check.field)) return `${check.actual.toFixed(1)}%`;
  return check.actual.toFixed(2);
}

function ScreenCandidateCard({ candidate, onAdopt, busy }: { candidate: ScreenCandidate; onAdopt: (symbol: string) => Promise<void>; busy: boolean }) {
  const [open, setOpen] = useState(false);
  return <article className="candidate-card">
    <div className="candidate-head">
      <div>
        <strong>{candidate.name}</strong>
        <span className="candidate-symbol">{candidate.symbol} · {candidate.board}{candidate.industry ? ` · ${candidate.industry}` : ""}</span>
      </div>
      <div className="candidate-tags">
        {candidate.in_indexes.map((name) => <span className="candidate-tag" key={name}>{name}</span>)}
        {candidate.also_matched.length > 0 && <span className="candidate-tag candidate-tag--cross">另有 {candidate.also_matched.length} 套策略也选中：{candidate.also_matched.join("、")}</span>}
      </div>
      <div className="candidate-actions">
        <span>{candidate.price === null ? "行情未同步" : formatMoney(candidate.price)}</span>
        {candidate.in_research_pool
          ? <span className="candidate-pooled">已在研究池</span>
          : <button className="text-button" disabled={busy} onClick={() => void onAdopt(candidate.symbol)}>{busy ? "正在建档…" : "建档进研究池"}</button>}
        <button className="text-button" onClick={() => setOpen((value) => !value)}>{open ? "收起依据" : "看入选依据"}</button>
      </div>
    </div>
    {open && <div className="candidate-checks">
      {candidate.checks.map((check) => <div key={check.rule}>
        <span>{check.rule}</span>
        <b className={check.passed ? "quote-down" : "quote-up"}>实际 {checkValue(check)}</b>
      </div>)}
      <p className="candidate-note">以上是这家公司入选的全部依据，取自最新报告期与同步到的行情；是否值得买入不在这份清单的判断范围内。</p>
    </div>}
  </article>;
}

const OP_LABELS: Array<{ value: string; label: string }> = [
  { value: "gte", label: "≥" },
  { value: "lte", label: "≤" },
  { value: "gt", label: ">" },
  { value: "lt", label: "<" },
];

interface DraftRule {
  field: string;
  op: string;
  value: number;
  unit: string;
}

function StrategyEditor({ strategy, fields, onPreview, onSaved, onDeleted, onCancel }: {
  strategy: ScreenStrategy;
  fields: ScreenField[];
  onPreview: (draft: { rules: DraftRule[]; sort_field: string; sort_desc: boolean; name: string; forked_from: string | null }) => Promise<void>;
  onSaved: (key: string) => Promise<void>;
  onDeleted: () => Promise<void>;
  onCancel: () => void;
}) {
  const [rules, setRules] = useState<DraftRule[]>(strategy.rules.map((rule) => ({ field: rule.field, op: rule.op, value: rule.value, unit: rule.unit })));
  const [sortField, setSortField] = useState(strategy.sort_field);
  const [sortDesc, setSortDesc] = useState(strategy.sort_desc);
  const [name, setName] = useState(strategy.preset ? `${strategy.name}（我的）` : strategy.name);
  const [key, setKey] = useState(strategy.preset ? "" : strategy.key);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const fieldMap = new Map(fields.map((item) => [item.field, item]));
  function updateRule(index: number, patch: Partial<DraftRule>) {
    setRules((current) => current.map((rule, position) => {
      if (position !== index) return rule;
      const next = { ...rule, ...patch };
      if (patch.field) next.unit = fieldMap.get(patch.field)?.unit ?? "";
      return next;
    }));
  }

  const draft = { rules, sort_field: sortField, sort_desc: sortDesc, name, forked_from: strategy.preset ? strategy.key : strategy.forked_from };
  const unusable = rules.filter((rule) => fieldMap.get(rule.field) && !fieldMap.get(rule.field)!.usable).map((rule) => fieldMap.get(rule.field)!.label);

  async function preview() {
    setBusy("preview"); setError("");
    try { await onPreview(draft); } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }
  async function save() {
    const slug = (key || `my_${strategy.key}`).toLowerCase().replace(/[^a-z0-9_]/g, "_");
    setBusy("save"); setError("");
    try {
      await saveScreenStrategy({
        key: slug,
        name,
        summary: strategy.summary,
        rules,
        sort_field: sortField,
        sort_desc: sortDesc,
        sort_label: `${fieldMap.get(sortField)?.label ?? sortField}${sortDesc ? "由高到低" : "由低到高"}`,
        forked_from: strategy.preset ? strategy.key : strategy.forked_from,
      });
      setKey(slug);
      await onSaved(slug);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }
  async function remove() {
    if (!(await confirmAction({
                  title: `删除策略「${strategy.name}」？`,
                  detail: "已经跑过的记录会保留。", confirmText: "删除策略", danger: true,
                }))) return;
    setBusy("delete"); setError("");
    try { await deleteScreenStrategy(strategy.key); await onDeleted(); }
    catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  }

  return <div className="strategy-editor">
    <div className="editor-head">
      <h3>调整条件</h3>
      <span>{strategy.preset ? "预置策略不会被改动；调好后存成你自己的一套" : "这是你自己的策略，保存会直接覆盖"}</span>
    </div>
    <div className="rule-rows">
      {rules.map((rule, index) => {
        const meta = fieldMap.get(rule.field);
        return <div className="rule-row" key={`${rule.field}-${index}`}>
          <select value={rule.field} onChange={(event) => updateRule(index, { field: event.target.value })} aria-label="条件字段">
            {fields.map((item) => <option value={item.field} key={item.field}>{item.label}{item.usable ? "" : "（数据不足）"}</option>)}
          </select>
          <select value={rule.op} onChange={(event) => updateRule(index, { op: event.target.value })} aria-label="比较方式">
            {OP_LABELS.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}
          </select>
          <input type="number" step="any" value={rule.value} onChange={(event) => updateRule(index, { value: Number(event.target.value) })} aria-label="阈值" />
          <span className="rule-unit">{rule.unit || meta?.unit || ""}</span>
          <span className="rule-hint">{meta?.hint}{meta ? ` · 底座完整度 ${meta.coverage}%` : ""}</span>
          <button className="text-button" type="button" onClick={() => setRules((current) => current.filter((_, position) => position !== index))} disabled={rules.length <= 1}>删除</button>
        </div>;
      })}
    </div>
    <div className="editor-actions">
      <button className="text-button" type="button" onClick={() => setRules((current) => [...current, { field: "roe", op: "gte", value: 15, unit: "%" }])}>加一条条件</button>
      <label className="sync-interval">排序
        <select value={sortField} onChange={(event) => setSortField(event.target.value)}>
          {fields.map((item) => <option value={item.field} key={item.field}>{item.label}</option>)}
        </select>
      </label>
      <label className="sync-toggle"><input type="checkbox" checked={sortDesc} onChange={(event) => setSortDesc(event.target.checked)} />由高到低</label>
      <label className="sync-interval">名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
    </div>
    {unusable.length > 0 && <p className="form-error">这些字段在底座里数据不足，用它们做条件会跑不动：{unusable.join("、")}</p>}
    {error && <p className="form-error">{error}</p>}
    <div className="form-actions">
      <button className="page-action" type="button" onClick={() => void preview()} disabled={busy !== ""}>{busy === "preview" ? "正在试跑…" : "试跑（不保存）"}</button>
      <button className="text-button" type="button" onClick={() => void save()} disabled={busy !== ""}>{busy === "save" ? "正在保存…" : strategy.preset ? "存为我的策略" : "保存修改"}</button>
      {!strategy.preset && <button className="text-button" type="button" onClick={() => void remove()} disabled={busy !== ""}>删除这套</button>}
      <button className="text-button" type="button" onClick={onCancel}>收起</button>
    </div>
    <p className="form-note">
      试跑只在这次会话里生效，不写进运行记录；保存后才会成为一套可以反复复现的策略。
      {strategy.preset && "预置策略的已知偏差会跟着复制过去——改了门槛不等于改掉了它的盲区。"}
    </p>
  </div>;
}

const CANDIDATE_TONE: Record<string, string> = {
  值得深入: "good", 值得细看: "good", 先放着: "calm", 直接排除: "muted", 未评: "muted",
};

const SCREEN_RULE_SHORT_LABELS: Record<string, string> = {
  pe_ttm: "PE",
  pb: "PB",
  graham_number: "PE×PB",
  annual_roe: "ROE（年）",
  annual_gross_margin: "毛利率（年）",
  net_profit_growth: "净利增速",
  revenue_growth: "营收增速",
  net_profit: "净利润",
  ocf_per_share: "每股经营现金流",
  total_market_cap: "市值",
  cash_ratio: "现金/利润",
  peg: "PEG",
  dividend_yield: "股息率",
  above_ma60: "站上60日线",
  rising_days: "量价齐升天数",
  stage_gain: "阶段涨幅",
  stage_turnover: "阶段换手",
  new_high_level: "新高档位",
  volume_days: "持续放量天数",
  turnover_rate: "换手率",
};

const SCREEN_RULE_OPERATORS: Record<string, string> = { gte: "≥", lte: "≤", gt: ">", lt: "<" };

function shortScreenRule(rule: ScreenRule): string {
  const operator = SCREEN_RULE_OPERATORS[rule.op] ?? rule.op;
  if (rule.field === "above_ma60") return rule.value >= 1 ? "站上60日线" : "未站上60日线";
  if (rule.field === "new_high_level") {
    const level = rule.value >= 4 ? "历史" : rule.value >= 3 ? "一年" : rule.value >= 2 ? "半年" : "一月";
    return `新高 ≥ ${level}`;
  }
  if (rule.field === "total_market_cap") return `市值 ${operator} ${(rule.value / 100_000_000).toLocaleString("zh-CN", { maximumFractionDigits: 1 })}亿`;
  const value = Number.isInteger(rule.value) ? rule.value.toString() : rule.value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  const unit = (rule.unit ?? "").trim();
  return `${SCREEN_RULE_SHORT_LABELS[rule.field] ?? rule.field} ${operator} ${value}${unit}`;
}

/**
 * 价值候选的模型初筛。
 *
 * **规则在前，模型在后。** 五千多只全交给模型既慢又贵，而规则筛是免费的——
 * ROE、PE、增速算一遍不花钱。模型只用在最后一步：规则挑不出来的那种
 * 「指标都合格，但组合起来像不像一门好生意」。
 *
 * 宽度让用户定，旁边实时标着要花几分。默认 20 是折中：再窄容易漏，再宽人也看不完。
 */
/**
 * 花模型钱跑出来的结果，全站长一个样。**这是母版，不是又一套。**
 *
 * 找票页上现在有两块这样的东西（模型复核、用一句话选股），它们的外壳
 * 本来就该一模一样：一个 panel-heading（眉标 + 标题 + 右侧控件）、
 * 整块能收起、收起时留一句话说明里面还有什么、结果上方一条摘要栏
 * 带「折叠结果 / 清掉」。
 *
 * **而我给 AI 选股另写了一套**：自己的头部、自己的展开方式，
 * 还只能展开、收不回去。使用者的原话是「我恨的牙痒痒，为什么不是同一套
 * 抽成母版」——这条批评是对的，同一页上两块功能长两个样，
 * 不是风格问题，是这一页看起来像两个人各做各的。
 *
 * 所以把外壳抽到这里，两边都用它。以后第三块也用它。
 */
function ResultPanel({ kicker, title, controls, className = "", collapsed, onCollapsedChange,
                       collapsedNote, children }: {
  kicker: string;
  title: React.ReactNode;
  /** 右侧的控件（跑一次、参数…）。收起按钮由母版自己加，各处不要再造一个。 */
  controls?: React.ReactNode;
  className?: string;
  collapsed: boolean;
  onCollapsedChange: (next: boolean) => void;
  /** 收起时显示的那一句：**里面还有什么**。收起后一片空白等于让人忘掉它。 */
  collapsedNote: string;
  children: React.ReactNode;
}) {
  return <section className={`panel result-panel ${className}`.trim()}>
    <div className="panel-heading result-panel-head">
      <div>
        <span className="eyebrow">{kicker}</span>
        <h2>{title}</h2>
      </div>
      <div className="result-panel-controls">
        {controls}
        <button className="text-button" type="button" onClick={() => onCollapsedChange(!collapsed)}>
          {collapsed ? "展开" : "收起"}
        </button>
      </div>
    </div>
    {collapsed ? <p className="result-panel-folded">{collapsedNote}</p> : children}
  </section>;
}

/**
 * 结果本体上方那一条：一句话说这次跑出了什么，右边是对这份结果的动作。
 *
 * **「折叠结果」和「清掉」必须都在。** 一份看完了的结果继续挂在页面上，
 * 说的是上一次的事——摆着一份过期的结论比不摆更糟。
 */
function ResultBar({ note, extra, folded, onFoldedChange, onClear }: {
  note: string;
  extra?: React.ReactNode;
  folded: boolean;
  onFoldedChange: (next: boolean) => void;
  onClear: () => void;
}) {
  return <div className="result-bar">
    <span className="result-bar-note">{note}</span>
    {extra}
    <div className="result-bar-actions">
      <button className="text-button" type="button" onClick={() => onFoldedChange(!folded)}>
        {folded ? "展开结果" : "折叠结果"}
      </button>
      <button className="text-button" type="button" onClick={onClear}>清掉</button>
    </div>
  </div>;
}

/**
 * AI 选股：一句话 → 条件 → 全 A 筛 → 模型挑。
 *
 * ## 跟旁边那八张策略卡的分工
 *
 * 规则能表达的东西有硬边界：「PE ≤ 15」写得出来，
 * 「现金流扎实、不靠一次性收益、别在热门赛道里」写不出来。
 * 前者八套预置策略已经覆盖了，后者是这个功能存在的全部理由。
 *
 * ## 版面上最重要的一块不是结果，是**它把你的话翻成了什么**
 *
 * 所以「它这么理解你」和翻出来的条件排在挑中的公司**前面**，
 * 而且条件可以当场存成你自己的策略。
 * 一个说不出自己凭什么筛的荐股结果，跟股吧里的贴子没有区别——
 * 把中间那一步摊开，是这个功能跟「AI 给你五只票」的分界线。
 */
function AiPickPanel({ onWrite, onSaved }: {
  onWrite: (symbol: string) => Promise<void>;
  onSaved: (key: string) => Promise<void>;
}) {
  const [options, setOptions] = useState<AiPickOptions | null>(null);
  const [question, setQuestion] = useState("");
  const [web, setWeb] = useState(true);
  const [job, setJob] = useState<BackgroundJob | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AiPickResult | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [savingTask, setSavingTask] = useState(false);
  const [savedNote, setSavedNote] = useState("");
  /** 结果本体折起来了。恢复回来的默认是折的（「我还没跑怎么就有结果」），
   *  但**必须能来回**——第一版只能展开、收不回去。 */
  const [folded, setFolded] = useState(false);
  /** 整块收起。跟模型复核用同一个母版（ResultPanel）。 */
  const [panelFolded, setPanelFolded] = useState(false);
  /** 这份结果是上次跑的，不是这一次的。用来决定摘要那句话怎么写。 */
  const [restored, setRestored] = useState(false);
  const confirmSpend = useSpendGuard();

  useEffect(() => {
    let live = true;
    void getAiPickOptions().then((data) => { if (live) setOptions(data); }).catch(() => undefined);
    // 上一次的结果要找回来。**花过钱的东西不能因为切了页面就没了。**
    void getAiPickStatus().then((latest) => {
      if (!live || !latest) return;
      setJob(latest);
      if (latest.status === "已完成" && latest.result) {
        const done = latest.result as unknown as AiPickResult;
        setResult(done);
        // **恢复回来的结果默认折起来。**
        //
        // 第一版是直接铺开的，理由是「花过钱的东西不能因为切页面就没了」——
        // 那个理由没错，错的是表现形式：一进来就看见一整屏结果，
        // 使用者的第一句话是「我还没有跑，怎么就有结果了？」。
        // 而它可能是上周跑的，页面上没有任何东西说明这一点。
        //
        // 结果留着，但收成一行「上次你问过……」，你点了才展开。
        setRestored(true);
        setFolded(true);
      }
      if (latest.status === "排队中" || latest.status === "运行中") {
        setRunning(true);
        // **不能吞掉。** 吞掉之后 poll 里的 setRunning(false) 也执行不到，
        // 按钮就永远停在「正在…」，而人不知道发生了什么。
        // 点按钮那条路径（下面）本来就是这么写的，只有"打开页面时接上一个还在跑的任务"
        // 这条路径漏了——而那恰恰是刷新页面之后必走的一条。
        void poll().catch((caught) => { setError(errorMessage(caught)); setRunning(false); });
      }
    }).catch(() => undefined);
    return () => { live = false; };
  }, []);

  async function poll() {
    for (let attempt = 0; attempt < 240; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 2500));
      const latest = await getAiPickStatus();
      if (!latest) break;
      setJob(latest);
      if (latest.status === "已完成") {
        if (latest.result) setResult(latest.result as unknown as AiPickResult);
        break;
      }
      if (latest.status === "失败" || latest.status === "已中断") {
        setError(latest.error || latest.note || "这次选股没有跑完");
        break;
      }
    }
    setRunning(false);
  }

  async function run() {
    const asked = question.trim();
    if (!asked) { setError("先说一句你想找什么样的公司。"); return; }
    const willSearch = web && options?.web_available;
    // 联网那一次的价钱是**算得准的**（搜索次数和系数都写死在代码里），
    // 所以按开关取不同的报价，而不是在确认框里补一句「另计几分搜索费用」——
    // 那句话既含糊，用词也错：这个产品的单位是积分，不是钱。
    if (!(await confirmSpend(willSearch ? "ai-pick-web" : "ai-pick",
      `按「${asked.slice(0, 24)}${asked.length > 24 ? "…" : ""}」在全 A 里选一次`))) return;
    setRunning(true); setError(""); setResult(null); setSavedNote(""); setRestored(false); setFolded(false); setPanelFolded(false);
    try {
      const started = await startAiPick(asked, Boolean(willSearch));
      setJob(started);
      void poll().catch((caught) => { setError(errorMessage(caught)); setRunning(false); });
    } catch (caught) { setError(errorMessage(caught)); setRunning(false); }
  }

  /**
   * 把这次挑出来的几家存成研究任务。
   *
   * **这一条以前是漏的。** 综合榜和九套策略跑完都能「存成研究任务」，
   * 只有这里不能——而这里恰恰最需要：模型挑的这几家哪怕规则一样也不保证重现，
   * 关掉页面就只剩一句「上次你问过……」。
   *
   * 存成策略和存成研究任务**不是一回事**，所以两个按钮都要有：
   * 前者留下的是"条件"（下次还能再跑一遍），后者留下的是"这几家公司"
   * （逐家推进到建档或排除）。
   */
  async function saveTaskFromPicks() {
    if (!result || result.picks.length === 0) return;
    setSavingTask(true); setError("");
    try {
      const task = await createResearchTask({
        title: `一句话选股 · ${result.question.slice(0, 20)}`,
        strategy_key: AI_PICK_KEY,
        symbols: result.picks.map((pick) => pick.symbol),
        limit: result.picks.length,
      });
      setSavedNote(`已存成研究任务「${task.title}」，共 ${task.total} 家，可在“研究任务”页逐家推进。`);
    } catch (caught) { setError(errorMessage(caught)); } finally { setSavingTask(false); }
  }

  async function saveAsStrategy() {
    if (!result) return;
    setSaving(true); setError("");
    try {
      const key = `ai_${Date.now().toString(36)}`;
      await saveScreenStrategy({
        key,
        name: result.savable.name,
        summary: result.plan.summary || result.question.slice(0, 60),
        rules: result.savable.rules,
        sort_field: result.savable.sort_field,
        sort_desc: result.savable.sort_desc,
        sort_label: result.savable.sort_label,
        forked_from: null,
      });
      await onSaved(key);
      setSavedNote(`已存成「${result.savable.name}」，之后可以直接选它，跑起来不花钱。`);
    } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); }
  }

  const asks = options?.asks ?? [];

  return <ResultPanel
    className="ai-pick"
    kicker="用一句话选股"
    title="说说你想找什么样的公司"
    collapsed={panelFolded}
    onCollapsedChange={setPanelFolded}
    collapsedNote={running ? "正在后台跑，展开可以看进度。"
      : result ? `上次问的是「${result.question}」，挑出 ${result.picks.length} 家。`
      : "展开写一句你想找什么样的公司。"}
  >

    <div className="ai-pick-ask">
      <textarea
        value={question}
        onChange={(event) => setQuestion(event.target.value.slice(0, 200))}
        placeholder="例如：赚到的是真钱，利润能变成现金流，不是靠应收账款堆出来的"
        rows={2}
        maxLength={200}
        disabled={running}
      />
      <div className="ai-pick-go">
        {/* 联网这一句原来在开关下面单独占一行解释它只干什么。收进 title 里——
            该知道的时候（鼠标停上去、或者用了带概念的问法）才出现。 */}
        <label className={`ai-pick-web${options && !options.web_available ? " is-off" : ""}`}
          title={options && !options.web_available ? options.web_reason
            : "只用来把「固态电池」这类概念变成一串公司名；数字一律用库里的"}>
          <input type="checkbox" checked={web && Boolean(options?.web_available)}
            disabled={running || !options?.web_available}
            onChange={(event) => setWeb(event.target.checked)} />
          允许联网
        </label>
        <button className="page-action" disabled={running || !question.trim()} onClick={() => void run()}>
          {running ? "正在选…" : "开始选"}
        </button>
      </div>
      {asks.length > 0 && <div className="ai-pick-presets">
        {asks.map((ask) => <button
          key={ask.text}
          className="ai-pick-preset"
          disabled={running || !ask.usable}
          title={ask.usable ? ask.text + (ask.web ? "（这条要联网）" : "") : ask.unavailable_reason}
          onClick={() => { setQuestion(ask.text); if (ask.web) setWeb(true); }}
        >{ask.short}{ask.web && <em>要联网</em>}
          {/* 门槛没到不要沉默地灰掉：说清是缺哪个字段，他才知道去同步什么 */}
          {!ask.usable && <em className="is-off">{ask.unavailable_reason}</em>}
        </button>)}
      </div>}
    </div>

    {error && <p className="form-error">{error}</p>}
    {savedNote && <p className="restore-message">{savedNote}</p>}
    {running && <p className="candidate-job-state"><span className="candidate-job-dot" />
      {job?.label || "正在选"} · 这项任务在服务端运行，切换页面后会继续。</p>}

    {/* 结果上方那一条：跟模型复核用同一个 ResultBar。
        恢复回来的结果默认是折的——「我还没有跑，怎么就有结果了？」——
        但**折和展开必须能来回**，第一版只能展开。 */}
    {result && <ResultBar
      note={restored
        ? `上次问的是「${result.question}」${job?.finished_at ? "　" + job.finished_at.slice(0, 16).replace("T", " ") : ""}`
        : result.note}
      extra={<>
        <span className="result-bar-scale">挑出 {result.picks.length} 家</span>
        {/* 跟其它清单一样能存成研究任务。放在这条结果带子上，因为它管的是
            「这几家公司」整份清单，而不是下面某一家。 */}
        <button className="text-button" disabled={result.picks.length === 0 || savingTask}
          onClick={() => void saveTaskFromPicks()}>{savingTask ? "正在保存…" : "存成研究任务"}</button>
      </>}
      folded={folded}
      onFoldedChange={setFolded}
      onClear={() => { setResult(null); setRestored(false); }}
    />}

    {result && !folded && <div className="ai-pick-result">
      {/* ① 它把你的话理解成了什么。**排在结果前面**——理解错了，后面全都不用看。 */}
      {result.plan.reading && <div className="ai-pick-reading">
        <span className="section-kicker">它这么理解你这句话</span>
        <p>{result.plan.reading}</p>
      </div>}

      {/* ② 翻出来的条件。可以当场存成你自己的策略。 */}
      <div className="ai-pick-plan">
        <div className="ai-pick-plan-head">
          <strong>{result.plan.name}</strong>
          <span>{result.plan.summary}</span>
          <button className="page-action page-action--row" disabled={saving || result.savable.rules.length === 0}
            onClick={() => void saveAsStrategy()}>{saving ? "正在保存…" : "存成我的策略"}</button>
        </div>
        <div className="ai-pick-rules">
          {result.savable.rules.map((rule, index) => <span key={`${rule.field}-${index}`}>{shortScreenRule(rule)}</span>)}
          {result.plan.industries.length > 0 && <span className="is-scope">限 {result.plan.industries.join("、")}</span>}
          {result.plan.theme && <span className="is-scope">概念 {result.plan.theme}</span>}
        </div>
        <p className="ai-pick-sort">按 {result.plan.sort_label}</p>
        {/* ③ 丢掉了什么。**丢了不说，他会以为那条生效了。** */}
        {result.plan.dropped.length > 0 && <ul className="ai-pick-dropped">
          {result.plan.dropped.map((note) => <li key={note}>{note}</li>)}
        </ul>}
      </div>

      {/* ④ 这次是在多大范围里筛的。三个数摆在一起，截断和收窄都藏不住。 */}
      <dl className="ai-pick-funnel">
        <div><dt>全 A</dt><dd>{result.screened.universe_total}</dd></div>
        <div><dt>{result.screened.searched_in < result.screened.universe_total ? "收窄到" : "筛的范围"}</dt>
          <dd>{result.screened.searched_in}</dd></div>
        <div><dt>命中</dt><dd className="is-lit">{result.screened.matched}</dd></div>
        <div><dt>交给模型看</dt><dd>{result.screened.returned}</dd></div>
        <div><dt>它挑了</dt><dd className="is-lit">{result.picks.length}</dd></div>
      </dl>

      {result.web.note && <p className="ai-pick-web-note">{result.web.note}</p>}

      {result.picks.length === 0
        ? <p className="empty-state">{result.note}</p>
        : <ol className="ai-pick-picks">
          {result.picks.map((pick) => <li key={pick.symbol}>
            <div className="ai-pick-pick-head">
              <strong>{pick.name}</strong>
              <span className="ai-pick-code">{pick.symbol}</span>
              {pick.industry && <span className="ai-pick-industry">{pick.industry}</span>}
              {pick.in_research_pool
                ? <span className="ai-pick-have">已在研究池</span>
                : <button className="page-action page-action--row" onClick={() => void onWrite(pick.symbol)}>建档</button>}
            </div>
            <p className="ai-pick-why">{pick.why}</p>
            {pick.reasons.length > 0 && <ul className="ai-pick-reasons">
              {pick.reasons.map((reason) => <li key={reason}>{reason}</li>)}
            </ul>}
            {pick.concerns.length > 0 && <ul className="ai-pick-concerns">
              {pick.concerns.map((concern) => <li key={concern}>{concern}</li>)}
            </ul>}
            {/* 概念名单是**逐字匹配**出来的，程序只会认字不会判断，所以它会错：
                实测「eVTOL、机器人等细分场景」匹配出了公司「机器人」(300024)。
                因此这里给的不只是链接，而是**原文那一句**——只给链接等于要求你
                点进去才能判断，而一句话摆在这里，误伤一眼就看得出来。 */}
            {pick.theme_sources.length > 0 && <div className="ai-pick-source">
              {pick.theme_sources[0].quote && <q>{pick.theme_sources[0].quote}</q>}
              <span>概念名单出处：{pick.theme_sources.map((source) => <a key={source.url} href={source.url}
                target="_blank" rel="noreferrer">{source.title || source.url}</a>)}</span>
            </div>}
          </li>)}
        </ol>}

      {/* ⑤ 特意没挑的那几家。只说选了谁、不说放过了谁，读的人无法判断取舍。 */}
      {result.passed.length > 0 && <div className="ai-pick-passed">
        <span className="section-kicker">它特意放过的</span>
        <ul>{result.passed.map((item) => <li key={item.symbol}>
          <b>{item.name}</b><span>{item.why}</span>
        </li>)}</ul>
      </div>}

      {/* 分工那三行解释从头部搬到这里：跑完了、看得见条件了，
          再解释它做了什么才有意义。 */}
      <details className="result-boundary"><summary>它做了什么、没做什么</summary>
        <p>模型只做两件事：把你这句话翻成一套条件、从代码筛出来的公司里挑几家写理由。
          五千多只里挑哪几只，是代码按条件跑出来的。</p>
        <p>{result.boundary}</p>
        {result.model && <p>模型：{result.model}</p>}
      </details>
    </div>}
  </ResultPanel>;
}

function CandidateAssessPanel({ strategyKey, listName, fixedWidth }: {
  strategyKey: string | null;
  /** 非空时表示「这份清单有几家」由上面那一块决定，这里不再单独设。
   *
   *  **两个数各管各的会骗人**：综合榜取前 5 家，而这里默认 20，
   *  按钮写着「让模型看前 20 名」——读起来像会看 20 家，实际只有 5 家。
   *  它们本来就不该独立：没有人想「榜单看前 5，但让模型看前 20」。 */
  fixedWidth: number | null;
  /** 当前选中的那份清单叫什么。**按钮上要写出来**——
   *  不写的话「让模型看」看的是哪一份全靠猜。 */
  listName: string;
}) {
  const [ownWidth, setOwnWidth] = useState(20);
  const width = fixedWidth ?? ownWidth;
  const setWidth = setOwnWidth;
  const [result, setResult] = useState<ValueCandidates | null>(null);
  const [running, setRunning] = useState(false);
  const [job, setJob] = useState<BackgroundJob | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const [error, setError] = useState("");
  const [savedId, setSavedId] = useState<number | null>(null);
  const [savedAt, setSavedAt] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState("");

  // 跟后端 estimate_candidate_credits 同一个口径：1500 固定开销 + 每家约 320 token，
  // 5000 token 一分。两边算法要一致，否则页面说 2 分、实际扣 3 分。
  const estimate = Math.max(1, Math.ceil((1500 + width * 200 + Math.min(width * 120, 3000)) / 5000));

  useEffect(() => {
    let current = true;
    setResult(null);
    setCollapsed(false);
    setPanelCollapsed(false);
    setError("");
    setRunning(false);
    setJob(null);
    setSavedId(null);
    setSavedAt("");
    setSavedNotice("");
    if (!strategyKey) return () => { current = false; };

    const restore = async () => {
      try {
        const [saved, latest] = await Promise.all([
          getSavedCandidateReview(strategyKey, width),
          getCandidateReviewJob(strategyKey, width),
        ]);
        if (!current) return;
        if (saved) {
          setResult({
            strategy: { key: saved.strategy_key, name: saved.strategy_name },
            width: saved.width,
            rows: saved.rows,
            assessed: true,
            estimated_credits: saved.estimated_credits,
            note: saved.note,
            boundary: saved.boundary,
          });
          setSavedId(saved.id);
          setSavedAt(saved.created_at);
          setCollapsed(true);
        }
        if (latest) {
          setJob(latest);
          setRunning(latest.status === "排队中" || latest.status === "运行中");
          if (latest.status === "已完成" && latest.result) {
            setResult(latest.result as unknown as ValueCandidates);
            setCollapsed(true);
          }
          if (latest.status === "排队中" || latest.status === "运行中") {
            // 同上：接上一个还在跑的任务时也要能报错，否则刷新页面就卡住。
            void pollCandidateJob(latest).catch((caught) => { setError(errorMessage(caught)); setRunning(false); });
          }
        }
      } catch { /* 结果恢复失败不影响规则筛选 */ }
    };
    void restore();
    return () => { current = false; };
  }, [strategyKey, listName, width]);

  async function pollCandidateJob(started: BackgroundJob) {
    if (!strategyKey) return;
    let latest = started;
    if (latest.status === "已完成" && latest.result) {
      setResult(latest.result as unknown as ValueCandidates);
      setCollapsed(false);
      const saved = await getSavedCandidateReview(strategyKey, width);
      if (saved) { setSavedId(saved.id); setSavedAt(saved.created_at); }
      setRunning(false);
      return;
    }
    for (let attempt = 0; attempt < 240; attempt += 1) {
      if (latest.status !== "排队中" && latest.status !== "运行中") break;
      await new Promise((resolve) => window.setTimeout(resolve, 2500));
      latest = await getCandidateReviewJob(strategyKey, width) ?? latest;
      setJob(latest);
      if (latest.status === "已完成" && latest.result) {
        setResult(latest.result as unknown as ValueCandidates);
        setCollapsed(false);
        const saved = await getSavedCandidateReview(strategyKey, width);
        if (saved) { setSavedId(saved.id); setSavedAt(saved.created_at); }
      }
      if (latest.status === "失败" || latest.status === "已中断") {
        setError(latest.error || latest.note || "模型复核没有完成");
      }
    }
    setRunning(false);
  }

  async function run() {
    if (!strategyKey) return;
    setRunning(true); setError(""); setCollapsed(false); setPanelCollapsed(false); setSavedId(null); setSavedAt(""); setSavedNotice(""); setResult(null);
    try {
      const started = await startCandidateReview(strategyKey, width);
      setJob(started);
      void pollCandidateJob(started).catch((caught) => { setError(errorMessage(caught)); setRunning(false); });
    } catch (caught) { setError(errorMessage(caught)); setRunning(false); }
  }

  async function saveResult() {
    if (!strategyKey || !result || !result.assessed || saving) return;
    setSaving(true); setError(""); setSavedNotice("");
    try {
      const saved = await saveCandidateReview({
        strategy_key: strategyKey,
        strategy_name: typeof result.strategy === "string" ? listName : result.strategy.name,
        width: result.width,
        rows: result.rows,
        note: result.note,
        boundary: result.boundary,
        estimated_credits: result.estimated_credits,
      });
      setSavedId(saved.id);
      setSavedAt(saved.created_at);
      setSavedNotice("已保存");
    } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); }
  }

  const savedLabel = savedAt ? savedAt.slice(0, 16).replace("T", " ") : "";

  return <ResultPanel
    className="candidate-assess-panel"
    kicker="第二步 · 模型复核"
    title={`模型复核「${listName}」`}
    collapsed={panelCollapsed}
    onCollapsedChange={setPanelCollapsed}
    collapsedNote={running ? "正在后台跑，展开可以看进度。"
      : result ? `上次复核留下了 ${result.rows.length} 家。` : "展开让模型把这份清单看一遍。"}
    controls={<>
      {fixedWidth === null
        ? <label>复核前
            <input type="number" min={1} max={60} value={width}
                   onChange={(e) => setWidth(Math.max(1, Math.min(60, Number(e.target.value) || 1)))} />
            名
          </label>
        : <span className="muted-label">复核这份榜单的 {fixedWidth} 家</span>}
      <span className="candidate-credit">约 {estimate} 积分</span>
      <button className="page-action" disabled={running || !strategyKey}
              onClick={() => void run()}>{running ? "模型复核中…" : (fixedWidth === null ? `模型复核前 ${width} 家` : `模型复核这 ${width} 家`)}</button>
    </>}
  >
    <>
    {error && <p className="form-error">{error}</p>}
    {job && running && <p className="candidate-job-state"><span className="candidate-job-dot" />{job.label || "模型复核进行中"} · 这项任务在服务端运行，切换页面后会继续。{job.total > 0 ? `（${job.progress}/${job.total}）` : ""}</p>}
    {/* **看完要能收起来。** 结果原来只能一直挂在那里：换一套策略、翻别的清单，
        它都还在上面占着一屏，而它说的是上一次那份清单的事——
        摆着一份过期的结论比不摆更糟。 */}
    {result && <ResultBar
      note={result.note}
      extra={<>
        <span className={`candidate-save-state${savedId ? " candidate-save-state--saved" : ""}`}>
          {savedId ? `已保存${savedLabel ? ` · ${savedLabel}` : ""}` : savedNotice || "尚未保存"}
        </span>
        <button className="text-button" type="button" disabled={Boolean(savedId) || saving} onClick={() => void saveResult()}>
          {saving ? "保存中…" : savedId ? "自动保存" : "补存结果"}
        </button>
      </>}
      folded={collapsed}
      onFoldedChange={setCollapsed}
      onClear={() => setResult(null)}
    />}

    {!collapsed && result && result.rows.length > 0 && <div className="assess-list">
      {result.rows.map((row, index) => {
        const tone = CANDIDATE_TONE[row.verdict] ?? "calm";
        return <article className={`assess-row assess-row--${tone}`} key={row.symbol}>
          <div className="assess-row-head assess-row-head--static">
            <span className="assess-rank" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
            <span className={`assess-chip assess-chip--${tone}`}>
              <span className="assess-chip-mark" aria-hidden="true">{tone === "good" ? "✓" : tone === "bad" ? "!" : "·"}</span>
              {row.verdict}
            </span>
            <span className="assess-name">
              <strong>{row.name}</strong>
              <em>{row.symbol} · {row.industry || "行业未标注"}</em>
            </span>
            <span className="assess-summary-wrap">
              <span className="assess-summary-label">模型评语</span>
              <span className="assess-summary">
                {row.conclusion || row.reason || `PE ${row.pe_ttm ?? "—"} · PB ${row.pb ?? "—"} · ROE ${row.roe ?? "—"}`}
              </span>
            </span>
          </div>
          {((row.reasons && row.reasons.length > 0) || (row.concerns && row.concerns.length > 0)) && <div className="assess-body">
            {row.reasons && row.reasons.length > 0 && <div className="assess-block assess-block--support">
              <h4><span className="assess-support-mark" aria-hidden="true">✓</span>支持这条评语 <em>{row.reasons.length} 条</em></h4>
              <ul className="assess-gaps">{row.reasons.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </div>}
            {row.concerns && row.concerns.length > 0 && <div className="assess-block assess-block--risk">
              <h4><span className="assess-risk-mark" aria-hidden="true">!</span>要留意的 <em>{row.concerns.length} 条</em></h4>
              <ul className="assess-gaps">{row.concerns.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </div>}
          </div>}
        </article>;
      })}
    </div>}

    {result?.boundary && <Boundary text={result.boundary} />}
    </>
  </ResultPanel>;
}

function ScreenerPage({ onWrite }: { onWrite?: (symbol: string) => void }) {
  const [strategies, setStrategies] = useState<ScreenStrategy[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [result, setResult] = useState<ScreenResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [adopting, setAdopting] = useState("");
  const [fields, setFields] = useState<ScreenField[]>([]);
  const [editing, setEditing] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [savingTask, setSavingTask] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [rederiving, setRederiving] = useState(false);
  const [rulesCollapsed, setRulesCollapsed] = useState(false);
  // 「看的方式」跟策略分开：换排序、换条数只影响这一次查看，不写回策略。
  const [view, setView] = useState<{ sort?: string; desc?: boolean; limit: number }>({ limit: 30 });

  async function rederive() {
    setRederiving(true); setError(""); setMessage("");
    try {
      const outcome = await rederiveUniverse();
      setMessage(outcome.note);
      setStrategies(await getScreenStrategies());
      if (active) setResult(await runScreen(active, 30));
    } catch (caught) { setError(errorMessage(caught)); } finally { setRederiving(false); }
  }

  useEffect(() => {
    let current = true;
    void getScreenFields().then((items) => { if (current) setFields(items); }).catch(() => undefined);
    getScreenStrategies()
      .then((items) => {
        if (!current) return;
        setStrategies(items);
        setActive(items.find((item) => item.available)?.key ?? null);
        setError("");
      })
      .catch((caught) => { if (current) setError(errorMessage(caught)); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, []);

  useEffect(() => {
    // 荐股池和 AI 选股都自己管自己的运行（而且**不自动跑**：点了才跑）。
    // 不挡住的话切到它们会白白跑一遍规则筛，结果还没地方显示。
    //
    // **而且它们的 key 是哨兵值，不在策略库里。** 漏掉一个的表现是页面顶上
    // 出现一条英文红字「strategy not found」——一个内部标识符漏到了用户面前。
    // 综合榜为此踩过一次（见 value_candidates 里那段），AI 选股上线时又踩了一次，
    // 所以这里改成显式列出所有哨兵值，加第三个的时候不容易再漏。
    if (!active || previewing || SENTINEL_KEYS.has(active)) return;
    let current = true;
    setRulesCollapsed(false);
    setRunning(true); setError(""); setMessage("");
    runScreen(active, view.limit, { field: view.sort, desc: view.desc })
      .then((next) => { if (current) setResult(next); })
      .catch((caught) => { if (current) { setResult(null); setError(errorMessage(caught)); } })
      .finally(() => { if (current) setRunning(false); });
    return () => { current = false; };
  }, [active, view]);

  async function adopt(symbol: string) {
    setAdopting(symbol); setError(""); setMessage("");
    try {
      const outcome = await importWatchlist({ symbols: [symbol], watch_group: "候选池" });
      const detail = outcome.results[0];
      setMessage(`${symbol}：${detail?.status ?? "已处理"}${detail?.detail ? ` · ${detail.detail}` : ""}`);
      if (active) setResult(await runScreen(active, 30));
    } catch (caught) { setError(errorMessage(caught)); } finally { setAdopting(""); }
  }

  async function saveTask() {
    if (!active || !result) return;
    setSavingTask(true); setError(""); setMessage("");
    try {
      const task = await createResearchTask({
        title: `${result.strategy.name} · ${new Date().toISOString().slice(0, 10)}`,
        strategy_key: previewing ? active : active,
        limit: result.candidates.length,
      });
      setMessage(`已存成研究任务「${task.title}」，共 ${task.total} 家，可在“研究任务”页逐家推进。`);
    } catch (caught) { setError(errorMessage(caught)); } finally { setSavingTask(false); }
  }

  async function savePoolTask(symbols: string[]) {
    if (active !== AGENT_POOL_KEY || symbols.length === 0) return;
    setSavingTask(true); setError(""); setMessage("");
    try {
      const task = await createResearchTask({
        title: `综合榜 · ${new Date().toISOString().slice(0, 10)}`,
        strategy_key: AGENT_POOL_KEY,
        symbols,
        limit: symbols.length,
      });
      setMessage(`已存成研究任务「${task.title}」，共 ${task.total} 家，可在“研究任务”页逐家推进。`);
    } catch (caught) { setError(errorMessage(caught)); } finally { setSavingTask(false); }
  }

  // 榜单取前几只。**跟下面「让模型看」共用同一个数**——见 CandidateAssessPanel。
  const [poolLimit, setPoolLimit] = useState(5);
  const onPool = active === AGENT_POOL_KEY;
  const onAiPick = active === AI_PICK_KEY;
  const current = (onPool || onAiPick) ? null : strategies.find((item) => item.key === active) ?? null;
  // 策略不是九个并排的选项，它们分两种口味——而这个分组是**后端算出来的**
  // （Strategy.kind 从规则用的字段推导），不是我在前端另编一份名单。
  const shelves = [
    { kind: "value", label: "便宜且稳", hint: "看财务", items: strategies.filter((item) => item.kind !== "trend") },
    { kind: "trend", label: "市场在追", hint: "看价量", items: strategies.filter((item) => item.kind === "trend") },
  ].filter((shelf) => shelf.items.length > 0);

  return <>
    {error && <p className="form-error">{error}</p>}
    {message && <p className="restore-message">{message}</p>}
    <section className="deck screen-deck" aria-labelledby="screener-title">
      <header className="deck-head">
        <div>
          <span className="deck-kicker">CANDIDATES · 全 A {result ? `${result.universe_total} 只` : "等待底座"}</span>
          <h1 id="screener-title">价值候选清单</h1>
          <p>先用一套规则把五千只压到几十只，然后一家一家看。规则只负责缩小范围，不负责下结论。</p>
        </div>
        <div className="deck-controls">
          <button className="text-button" disabled={rederiving} onClick={() => void rederive()}>{rederiving ? "正在重算…" : "重算估值字段"}</button>
        </div>
      </header>

      {loading && <div className="deck-rule screen-shelf-empty">正在读取策略库…</div>}
      {!loading && shelves.map((shelf) => <div className="deck-rule screen-shelf" key={shelf.kind}>
        <div className="screen-shelf-head">
          <strong>{shelf.label}</strong><span>{shelf.hint}</span>
          {/* 趋势那一组的立场要在**选之前**说，不是选完折在「已知偏差」里。
              后端的 biases 里写得很直白：「榜单是事后的，筛出来的永远是已经涨过的」，
              而且「跟本站长期研究的定位是拧着的」。那句话是这个产品的立场，
              把它藏起来等于默认推荐。 */}
          {shelf.kind === "trend" && <em>筛出来的是「已经涨过的」，不是「要涨的」</em>}
        </div>
        <div className="screen-shelf-list">
          {shelf.items.map((strategy) => <div className="screen-strategy-slot" key={strategy.key}>
            {/* **自定义策略的删除放在卡片上。**
              * 原来它只在「调整条件」编辑器的最底下——要先选中这张卡、再点
              * 「调整条件」、再翻到底。删除藏在一个叫「调整条件」的东西里，
              * 没人会去那儿找：实测使用者试过之后，线上六小时内浏览器**一次
              * DELETE 请求都没发出去**——不是接口坏了，是够不着。 */}
            {!strategy.preset && <button
              className="screen-strategy-drop"
              title={`删除「${strategy.name}」`}
              aria-label={`删除策略 ${strategy.name}`}
              onClick={async (event) => {
                event.stopPropagation();
                if (!(await confirmAction({
                  title: `删除策略「${strategy.name}」？`,
                  detail: "已经跑过的记录会保留。", confirmText: "删除策略", danger: true,
                }))) return;
                setError("");
                try {
                  await deleteScreenStrategy(strategy.key);
                  const items = await getScreenStrategies();
                  setStrategies(items);
                  if (active === strategy.key) setActive(items.find((item) => item.available)?.key ?? null);
                  setMessage(`已删除「${strategy.name}」，运行记录保留。`);
                } catch (caught) { setError(errorMessage(caught)); }
              }}
            >×</button>}
            <button
            className={`screen-strategy${strategy.key === active ? " is-on" : ""}${strategy.available ? "" : " is-off"}`}
            onClick={() => setActive(strategy.key)}
            aria-pressed={strategy.key === active}
          >
            <span className="screen-strategy-name">
              {strategy.name}{strategy.preset ? "" : <em>自定义</em>}
            </span>
            {/* 先说这套规则**在说什么**，再说它是怎么写的。
                原来卡片上只有规则，没有这句话——等于把实现细节当成了主角。 */}
            {strategy.summary && <span className="screen-strategy-say">{strategy.summary}</span>}
            {strategy.available
              ? <span className="screen-strategy-rules">
                  {/* **不编号。** 这些条件是同时成立的（AND），不是 01→02→03 的步骤；
                      编号会让人以为有先后或轻重，而实际上没有。用「·」串起来，
                      读作「而且」。顺带：卡片高度跟着条数走，不再被撑成等高留白。 */}
                  {strategy.rules.map((rule, index) => <span key={`${rule.field}-${index}`}>{shortScreenRule(rule)}</span>)}
                </span>
              : <span className="screen-strategy-off">暂不可用 · {strategy.unavailable_reason}</span>}
            {strategy.available && strategy.sort_label && <span className="screen-strategy-sort">按 {strategy.sort_label}</span>}
            </button>
          </div>)}
        </div>
      </div>)}

      {/* 综合榜不是第九个策略，是对前面所有策略的**汇总**——所以它不该长成
          第九张一样的卡。做成一条横贯的带子，形状本身就说明了它的层级。 */}
      {!loading && <button
        className={`deck-rule screen-union${onPool ? " is-on" : ""}`}
        onClick={() => setActive(AGENT_POOL_KEY)}
        aria-pressed={onPool}
      >
        <span className="screen-union-mark" aria-hidden="true">◈</span>
        <span className="screen-union-copy">
          <strong>综合榜</strong>
          <em>把上面每一套规则的结果取并集，按一只票命中了几套来排。</em>
        </span>
        <span className="screen-union-go">{onPool ? "正在看" : "打开 →"}</span>
      </button>}

      {/* AI 选股也不是第十张卡：它跟规则卡不是一类东西——**它花钱，而且同样一句话
          两次跑出来的结果可以不一样**。所以同样做成带子，但跟综合榜再分开一层：
          综合榜是把上面的结果汇总（往回看），这一条是你提一个上面表达不了的要求
          （往外走）。带子上不挂价签——花钱的确认在点下去那一刻弹（见 credits.ts）。 */}
      {!loading && <button
        className={`deck-rule screen-union screen-ai${onAiPick ? " is-on" : ""}`}
        onClick={() => setActive(AI_PICK_KEY)}
        aria-pressed={onAiPick}
      >
        <span className="screen-union-mark" aria-hidden="true">✦</span>
        <span className="screen-union-copy">
          <strong>用一句话选股</strong>
          <em>上面这些条件写不出来的要求，说给模型听。</em>
        </span>
        <span className="screen-union-go">{onAiPick ? "正在用" : "打开 →"}</span>
      </button>}

      {/* **舱的收口。**
        *
        * 「命中 254 家」是对你刚才那次选择的回应，属于「选」这一步——
        * 原来它在下面白色面板的第一行，于是深浅的分界正好切在
        * 「选策略」和「看结果」中间，而它俩是同一件事。
        * 材质变化该标记**活动**的变化：舱里选完并给出结果规模，
        * 纸面上才开始逐家决定建不建档。 */}
      {current && result && <div className="deck-rule screen-outcome">
        <div className="screen-outcome-say">
          <span className="deck-kicker">第一步 · 规则打底</span>
          <strong>{previewing ? `${result.strategy.name}（试跑）` : current.name}</strong>
        </div>
        <dl className="screen-outcome-nums">
          <div><dt>命中</dt><dd className="is-lit">{result.matched} 家</dd></div>
          <div><dt>全 A 样本</dt><dd>{result.universe_total} 只</dd></div>
          <div><dt>财务截止</dt><dd>{result.report_date ?? "未同步"}</dd></div>
        </dl>
        <div className="screen-outcome-do">
          <button className="text-button" onClick={() => setRulesCollapsed((value) => !value)}>{rulesCollapsed ? "展开清单" : "折叠清单"}</button>
          <button className="text-button" disabled={result.candidates.length === 0 || savingTask} onClick={() => void saveTask()}>{savingTask ? "正在保存…" : "存成研究任务"}</button>
          <button className="page-action" onClick={() => { setEditing((value) => !value); setRulesCollapsed(false); }}>{editing ? "收起条件" : "调整条件"}</button>
        </div>
      </div>}
    </section>
    {!loading && <>
      {onPool && <Suspense fallback={<div className="empty-state">正在加载…</div>}>
        <AgentPool onWrite={onWrite} onSaveTask={savePoolTask} savingTask={savingTask}
          limit={poolLimit} onLimitChange={setPoolLimit} />
      </Suspense>}
      {onAiPick && <AiPickPanel onWrite={adopt} onSaved={async (key) => {
        const items = await getScreenStrategies();
        setStrategies(items);
        setActive(key);
      }} />}
      {current && <section className="panel screen-result-panel">
        {!rulesCollapsed && <>
        {editing && <StrategyEditor
          strategy={current}
          fields={fields}
          onCancel={() => { setEditing(false); if (previewing) { setPreviewing(false); setActive(current.key); } }}
          onPreview={async (draft) => {
            const next = await previewScreen({ ...draft, name: draft.name }, 30);
            setPreviewing(true);
            setResult(next);
            setMessage("这是试跑结果，还没有保存成策略。");
          }}
          onSaved={async (key) => {
            const items = await getScreenStrategies();
            setStrategies(items);
            setPreviewing(false);
            setEditing(false);
            setActive(key);
            setMessage(`已保存为「${items.find((item) => item.key === key)?.name ?? key}」，之后可以直接选它。`);
          }}
          onDeleted={async () => {
            const items = await getScreenStrategies();
            setStrategies(items);
            setEditing(false);
            setPreviewing(false);
            setActive(items.find((item) => item.available)?.key ?? null);
            setMessage("策略已删除，运行记录保留。");
          }}
        />}
        {current.biases.length > 0 && <details className="strategy-biases strategy-biases--folded">
          <summary>已知偏差 <span>{current.biases.length} 条</span></summary>
          <ul>{current.biases.map((bias) => <li key={bias}>{bias}</li>)}</ul>
        </details>}
        {/* **说清楚这几家凭什么是这几家，并给出口。**
          * 原来页面只在底部写「命中 157 家」，清单直接铺 8 条（ShowMore 折叠），
          * 中间还夹着一层后端的 limit=30 —— 两层截断一层也没说，
          * 而「按什么排的」只在上面策略卡的第四行小字里出现过一次。 */}
        {result && <div className="screen-view">
          <span className="screen-view-say">
            <b>{result.matched}</b> 家命中 · {result.sort_explain} · 列出前 <b>{result.returned}</b> 家
          </span>
          <label className="deck-select screen-view-pick">换个排法
            <select value={view.sort ?? ""} onChange={(event) => setView((v) => ({ ...v, sort: event.target.value || undefined }))}>
              <option value="">按这套策略自己的排法</option>
              {fields.map((item) => <option value={item.field} key={item.field}>{item.label}</option>)}
            </select>
          </label>
          <label className="deck-select screen-view-pick">列出
            <select value={String(view.limit)} onChange={(event) => setView((v) => ({ ...v, limit: Number(event.target.value) }))}>
              <option value="30">前 30 家</option>
              <option value="100">前 100 家</option>
              <option value="200">全部（上限 200）</option>
            </select>
          </label>
          {(view.sort || view.limit !== 30) && <button className="text-button" onClick={() => setView({ limit: 30 })}>还原</button>}
        </div>}
        <div className="candidate-list">
          {running && <div className="empty-state">正在跑全市场…</div>}
          {!running && result && result.candidates.length === 0 && <div className="empty-state">这套条件在当前数据下没有命中任何公司。可以换一套策略，或复制这套后放宽条件。</div>}
          {!running && result && <ShowMore items={result.candidates} step={8} noun="家" render={(candidate) =>
            <ScreenCandidateCard candidate={candidate} onAdopt={adopt} busy={adopting === candidate.symbol} key={candidate.symbol} />
          } />}
        </div>
        {result && <details className="result-boundary"><summary>数据口径与边界</summary><p>{result.boundary}</p></details>}
        </>}
      </section>}
      {/* AI 选股自己就带模型这一步，不该再套一层「模型复核」——
          那会变成对同一批公司连着花两次钱做同一件事。 */}
      {!onAiPick && <CandidateAssessPanel strategyKey={active}
        listName={onPool ? "综合榜" : (current?.name ?? "这份清单")}
        fixedWidth={onPool ? poolLimit : null} />}
    </>}
  </>;
}

const HEATMAP_METRICS = [
  { key: "roe", label: "净资产收益率" },
  { key: "gross_margin", label: "销售毛利率" },
  { key: "revenue_growth", label: "营收同比" },
  { key: "net_profit_growth", label: "净利润同比" },
  { key: "pe_ttm", label: "市盈率 TTM" },
  { key: "pb", label: "市净率" },
  { key: "ytd_change", label: "年初至今涨跌" },
  { key: "change_60d", label: "近 60 日涨跌" },
  { key: "change_percent", label: "当日涨跌" },
  { key: "turnover_rate", label: "交易热度（换手率）" },
  { key: "abs_change", label: "当日波动幅度" },
  { key: "attention_index", label: "市场关注度" },
];

function HeatmapPage({ onOpenCompany }: { onOpenCompany: (id: number) => void }) {
  const [view, setView] = useState<HeatmapView | null>(null);
  const [scope, setScope] = useState("all");
  const [metric, setMetric] = useState("roe");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [adopting, setAdopting] = useState(false);

  useEffect(() => {
    let current = true;
    setLoading(true);
    getHeatmap(scope, metric)
      .then((next) => { if (current) { setView(next); setError(""); } })
      .catch((caught) => { if (current) { setView(null); setError(errorMessage(caught)); } })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [scope, metric]);

  async function drill(tile: { name: string; symbol: string | null }) {
    setMessage("");
    if (!tile.symbol) { setScope(`industry:${tile.name}`); return; }
    setAdopting(true);
    try {
      const outcome = await importWatchlist({ symbols: [tile.symbol], watch_group: "候选池" });
      const detail = outcome.results[0];
      if (detail?.status === "已存在") {
        const companies = await getCompanies(tile.symbol);
        const match = companies.find((item) => item.symbol === tile.symbol);
        if (match) { onOpenCompany(match.id); return; }
      }
      setMessage(`${tile.name}（${tile.symbol}）：${detail?.status ?? "已处理"}${detail?.detail ? ` · ${detail.detail}` : ""}`);
    } catch (caught) { setError(errorMessage(caught)); } finally { setAdopting(false); }
  }

  // 范围直接用接口给的：没有成分数据的指数不该出现在选项里
  const scopes = view?.scopes ?? [{ key: "all", label: "全 A", group: "全市场", count: null }];
  const scopeGroups = Array.from(new Set(scopes.map((item) => item.group)));
  const drillingIndustry = scope.startsWith("industry:");

  const beacons = view?.tiles.flatMap((tile) => tile.watched ?? []) ?? [];

  // 这一页跟首页驾驶舱是**同一张图的两种范围**，所以穿同一套语言（.deck）：
  // 深海舱体、金色灯塔、等宽数字。原来它是白卡片 + 浅蓝灰，从首页点
  // 「打开完整市场云图」进来像换了个网站——而更实质的差距是**它没有灯塔**：
  // 同一份数据里首页标出了你的公司，这一页把它们扔了。
  return <>
    {error && <p className="form-error">{error}</p>}
    {message && <p className="restore-message">{message}</p>}
    <section className="deck market-deck" aria-labelledby="market-map-title">
      <header className="deck-head">
        <div>
          <span className="deck-kicker">MARKET MAP · {view?.scope_label ?? "全 A"}</span>
          <h1 id="market-map-title">市场云图</h1>
          <p>面积是规模，颜色是你选的指标。只看结构，不排名次。</p>
        </div>
        <div className="deck-controls">
          <label className="deck-select">指标
            <select value={metric} onChange={(event) => setMetric(event.target.value)}>
              {HEATMAP_METRICS.map((item) => <option value={item.key} key={item.key}>{item.label}</option>)}
            </select>
          </label>
        </div>
      </header>

      <div className="deck-rule deck-scopes">
        {scopeGroups.map((group) => <div className="deck-pills" role="group" aria-label={`选择${group}`} key={group}>
          {scopes.filter((item) => item.group === group).map((item) => <button
            key={item.key}
            className={scope === item.key ? "is-on" : ""}
            onClick={() => setScope(item.key)}
          >{item.label}{item.count ? <small>{item.count}</small> : null}</button>)}
        </div>)}
        {drillingIndustry && <div className="deck-pills">
          <button className="is-on" onClick={() => setScope("all")}>{view?.scope_label} ×</button>
        </div>}
      </div>

      <div className="deck-rule market-deck-body">
        <div className="market-deck-meta">
          <div>
            <strong>{view ? `${view.scope_label} · ${view.metric_label}` : "正在读取市场"}</strong>
            <span>{view ? `${view.universe_total} 只 · ${view.with_metric} 只有数 · 面积为${view.size_basis}` : ""}</span>
          </div>
          <span>{view?.level === "company" ? (adopting ? "正在处理…" : "点公司建档或打开档案") : "点行业下钻"}</span>
        </div>
        {loading && <div className="market-deck-empty">正在铺开真实市场数据…</div>}
        {!loading && view && view.tiles.length === 0 && <div className="market-deck-empty">
          这个范围里没有「{view.metric_label}」的数据。换一个指标，或者先在数据状态页跑一次全市场底座。
        </div>}
        {!loading && view && view.tiles.length > 0 &&
          <Suspense fallback={<div className="market-deck-empty">正在绘制云图…</div>}>
            <HeatmapChart view={view} onDrill={drill} />
          </Suspense>}
        {view && <p className="deck-note market-deck-note">
          {view.aggregation}。{view.metric_note}。颜色深浅只表示数值高低，不表示好坏——行业之间的口径差异要你自己判断。
        </p>}
      </div>

      {/* 金色灯塔：这一页跟行情软件的唯一区别。数据本来就在（tiles[].watched），
          原来只是没画出来。 */}
      {beacons.length > 0 && <div className="deck-rule market-deck-beacons">
        <div className="market-deck-beacons-head">
          <strong>这张图里有你的 {beacons.length} 家公司</strong>
          <span>金边的格子就是它们所在的行业</span>
        </div>
        <div className="market-deck-beacon-list">
          {beacons.slice(0, 12).map((item) => <button key={item.company_id} onClick={() => onOpenCompany(item.company_id)}>
            <i aria-hidden="true">◆</i><strong>{item.name}</strong><small>{item.symbol}</small>
          </button>)}
        </div>
      </div>}
    </section>
  </>;
}

const ITEM_STATUSES = ["待看", "已建档", "已排除"];
// 初筛三档结论对应的色调，跟站内 grade-chip 的高/中/低复用同一套。
// 名字带 SCREEN_ 前缀：方法体检那边另有一套 VERDICT_TONE（有利/不利/中性），
// 两套结论词表不一样，不能共用。
const SCREEN_VERDICT_TONE: Record<string, string> = { 值得深入: "高", 先放着: "中", 直接排除: "低" };

function TaskCard({ task, onChanged, onOpenCompany }: { task: ResearchTaskRecord; onChanged: () => Promise<void>; onOpenCompany: (id: number) => void }) {
  // 任务页先看整体进度，不把几十家公司一次性铺成字墙；需要逐家推进时再展开。
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(0);
  const [error, setError] = useState("");
  const progress = task.total === 0 ? 0 : Math.round(((task.adopted + task.dropped) / task.total) * 100);

  async function setItem(itemId: number, patch: { status?: string; note?: string }) {
    setBusy(itemId); setError("");
    try { await updateTaskItem(itemId, patch); await onChanged(); }
    catch (caught) { setError(errorMessage(caught)); } finally { setBusy(0); }
  }
  const [job, setJob] = useState<BackgroundJob | null>(null);
  // 任务跑在服务里，不在浏览器里：切页面、刷新、关掉标签都不影响它，这里只是轮询进度
  useEffect(() => {
    let live = true;
    const poll = async () => {
      try {
        const next = await getJob("task_auto_review", task.id);
        if (!live) return;
        setJob(next);
        if (next && (next.status === "运行中" || next.status === "排队中")) window.setTimeout(() => void poll(), 3000);
        else if (next && next.status === "已完成" && next.finished_at) await onChanged();
      } catch { /* 轮询失败不打断页面 */ }
    };
    void poll();
    return () => { live = false; };
  }, [task.id]);

  async function autoReview() {
    setError("");
    try {
      const started = await autoReviewTask(task.id, 30);
      setJob(started);
      const poll = async () => {
        const next = await getJob("task_auto_review", task.id);
        setJob(next);
        if (next && (next.status === "运行中" || next.status === "排队中")) window.setTimeout(() => void poll(), 3000);
        else await onChanged();
      };
      window.setTimeout(() => void poll(), 2500);
    } catch (caught) { setError(errorMessage(caught)); }
  }
  const running = job !== null && (job.status === "运行中" || job.status === "排队中");
  async function close(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(-1); setError("");
    try { await updateResearchTask(task.id, { status: "已完成", conclusion: String(form.get("conclusion") ?? "") }); await onChanged(); }
    catch (caught) { setError(errorMessage(caught)); } finally { setBusy(0); }
  }

  async function removeTask() {
    if (!(await confirmAction({
      title: `删除研究任务「${task.title}」？`,
      detail: "任务里的候选记录和复核结果会一起删除，公司档案不会受影响。",
      confirmText: "删除任务", danger: true,
    }))) return;
    setBusy(-2); setError("");
    try { await deleteResearchTask(task.id); await onChanged(); }
    catch (caught) { setError(errorMessage(caught)); } finally { setBusy(0); }
  }

  return <article className="task-card task-card--research">
    {job && <p className={`task-job-strip${job.status === "失败" || job.status === "已中断" ? " task-job-strip--error" : ""}`}>
      <span className="task-job-dot" />
      {running
        ? `${job.label} · 服务端运行中${job.total > 0 ? ` · ${job.progress}/${job.total}` : ""}`
        : job.status === "已完成" ? `已完成 · ${job.note}`
        : `${job.status} · ${job.error || job.note}`}
    </p>}
    <header className="task-head task-head--research">
      <div className="task-title-block">
        <span className="task-kicker">RESEARCH TASK · {task.strategy_name ?? task.source}</span>
        <strong>{task.title}</strong>
        <span>建立于 {task.created_at.slice(0, 10)}{task.due_date ? ` · 期望 ${task.due_date} 前看完` : ""}</span>
      </div>
      <div className="task-progress task-progress--research">
        <div className="task-progress-count"><strong>{task.adopted + task.dropped}</strong><span>/ {task.total} 已处理</span></div>
        <i><b style={{ width: `${progress}%` }} /></i>
        <span>已建档 {task.adopted} · 已排除 {task.dropped} · 待看 {task.pending}</span>
      </div>
      <div className="task-head-actions">
        <span className={`task-status task-status--${task.status === "进行中" ? "open" : "done"}`}>{task.status}</span>
        <button className="page-action task-auto" disabled={running} onClick={() => void autoReview()}>{running ? "后台复核中…" : "模型复核"}</button>
        <button className="text-button task-toggle" onClick={() => setOpen((value) => !value)}>{open ? "收起任务" : "展开任务"}</button>
        <button className="text-button task-delete" disabled={busy !== 0 || running} onClick={() => void removeTask()}>删除任务</button>
      </div>
    </header>
    <div className="task-summary-strip">
      <details>
        <summary>筛选口径</summary>
        <p>{task.data_note || "沿用保存时的筛选条件"}</p>
      </details>
      {task.conclusion && <span><b>你的结论</b>{task.conclusion}</span>}
    </div>
    {error && <p className="form-error">{error}</p>}
    {open && <>
      <div className="task-items">
        <ShowMore items={task.items} step={12} noun="家" render={(item) => <TaskItemRow key={item.id} item={item} busy={busy === item.id} onOpenCompany={onOpenCompany} onSet={setItem} onRefresh={onChanged} />} />
      </div>
      {task.status === "进行中" && <form className="task-close" onSubmit={close}>
        <input name="conclusion" placeholder="这轮筛下来的整体结论（可留空）" />
        <button className="text-button" type="submit" disabled={busy === -1}>{busy === -1 ? "正在结束…" : "结束这次任务"}</button>
      </form>}
    </>}
  </article>;
}

function TaskItemRow({ item, busy, onOpenCompany, onSet, onRefresh }: {
  item: ResearchTaskItem;
  busy: boolean;
  onOpenCompany: (id: number) => void;
  onSet: (itemId: number, patch: { status?: string; note?: string }) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const [assessing, setAssessing] = useState(false);
  const [assessNote, setAssessNote] = useState("");

  async function runAssess() {
    setAssessing(true); setAssessNote("");
    try {
      await assessTaskItem(item.id);
      // 后台任务：轮询到完成再刷新，否则页面上还是旧结果
      const poll = async () => {
        const job = await getJob("item_assessment", item.id);
        if (job && (job.status === "运行中" || job.status === "排队中")) {
          window.setTimeout(() => void poll(), 3000);
          return;
        }
        setAssessing(false);
        setAssessNote(job?.status === "已完成" ? job.note : (job?.error || ""));
        await onRefresh();
      };
      window.setTimeout(() => void poll(), 3000);
    } catch (caught) { setAssessNote(errorMessage(caught)); setAssessing(false); }
  }

  // 从 note 的开头猜结论是猜不准的（模型第一句写的是"这家公司做什么"，
  // 从来不以"值得"开头），现在它有自己的字段。
  const verdict = SCREEN_VERDICT_TONE[item.verdict] ?? "中";
  const reviewed = item.verdict !== "" || item.conclusion !== ""
    || item.reasons.length > 0 || item.concerns.length > 0;
  return <div className="task-row task-row--research">
    <div className="task-item task-item--research">
      <div className="task-item-identity">
        <span className="task-item-rank">{String(item.id).padStart(2, "0")}</span>
        <div>
          {item.company_id ? <button className="text-button" onClick={() => onOpenCompany(item.company_id!)}>{item.name}</button> : <strong>{item.name}</strong>}
          <em>{item.symbol}{item.industry ? ` · ${item.industry}` : ""}</em>
        </div>
      </div>
      <div className="task-item-evidence">
        <span className="task-item-label">规则命中</span>
        <span>{item.evidence.length > 0 ? item.evidence.map((check) => `${check.label} ${check.actual ?? "—"}`).join(" · ") : "暂无可展示指标"}</span>
      </div>
      <div className="task-item-controls">
        <select value={item.status} disabled={busy} onChange={(event) => void onSet(item.id, { status: event.target.value })} aria-label={`${item.name} 处理状态`}>
          {ITEM_STATUSES.map((status) => <option value={status} key={status}>{status}</option>)}
        </select>
        <input
          defaultValue={item.note}
          placeholder="写一句你的结论"
          onBlur={(event) => { if (event.target.value !== item.note) void onSet(item.id, { note: event.target.value }); }}
          aria-label={`${item.name} 我的结论`}
        />
      </div>
    </div>
    {/* 方法体检是辅助资料，不应和股票身份、待看状态争夺首屏注意力。默认收起，
        但保留“还未运行”的入口，让它仍然是一个可发现、可操作的能力。 */}
    <details className="task-details task-details--methods">
      <summary>
        <span>方法体检</span>
        <strong>{item.assessment.length > 0 ? `${item.assessment.length} 项结果` : "尚未运行"}</strong>
        {item.assessed_at && <em>{item.assessed_at.slice(0, 16).replace("T", " ")}</em>}
      </summary>
      <div className="task-details-body">
        <div className="task-assess">
          <button className="text-button" disabled={assessing} onClick={() => void runAssess()}>
            {assessing ? "模型正在逐条打分…" : item.assessment.length > 0 ? "重跑方法体检" : "跑一次方法体检"}
          </button>
          {assessNote && <em className="task-assess-note">{assessNote}</em>}
        </div>
        {item.assessment.length > 0 && <div className="task-methods">
          {item.assessment.map((row) => (
            <details key={row.method_key} className={`tmethod tmethod--${VERDICT_TONE[row.verdict] ?? "muted"}`}>
              <summary>
                <span className="tmethod-verdict">{row.verdict}</span>
                <strong>{row.method_name || row.method_key}</strong>
                <em>{row.summary}</em>
              </summary>
              {/* 缺什么要写出来 —— 「数据不足」如果不说缺什么，人只会当它是个错误 */}
              {row.gaps && row.gaps.length > 0 && <div className="tmethod-gaps">
                <h6>还缺这些才判得准</h6>
                <ul>{row.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
              </div>}
              {row.evidence && row.evidence.length > 0 && <div className="tmethod-facts">
                {row.evidence.map((e, i) => (
                  <span key={i}>{e.fact} <b>{e.value}</b>{e.as_of ? ` · ${e.as_of}` : ""}</span>
                ))}
              </div>}
            </details>
          ))}
        </div>}
      </div>
    </details>
    {/* 模型看法：默认收起，展开在这只股票下面。
        结论 + 支持 + 待核实加起来常常几百字，摊开会把整张清单撑散——
        而这张清单的用处正是"一屏扫过三十家"。 */}
    {reviewed && <details className="task-review" open={item.verdict === "直接排除"}>
      <summary>
        {item.verdict && <span className={`grade-chip grade-chip--${verdict}`}>{item.verdict}</span>}
        <span className="task-review-title">模型看法</span>
        <em>{item.conclusion || item.note}</em>
      </summary>
      <div className="task-review-body">
        {item.conclusion && <p className="task-review-lead">{item.conclusion}</p>}
        {/* 支持与待核实分两列摆：它们是相反方向的两件事，堆成一段就得自己去分辨
            哪句在帮这家公司说话、哪句在拆台。 */}
        <div className="task-review-cols">
          {item.reasons.length > 0 && <div className="task-review-col">
            <h4>支持</h4>
            <ul>{item.reasons.map((line, index) => <li key={index}>{line}</li>)}</ul>
          </div>}
          {item.concerns.length > 0 && <div className="task-review-col task-review-col--against">
            <h4>待核实</h4>
            <ul>{item.concerns.map((line, index) => <li key={index}>{line}</li>)}</ul>
          </div>}
        </div>
      </div>
    </details>}
    {(item.brief || item.links.length > 0 || item.reports.length > 0) && <details className="task-details task-details--sources">
      <summary>
        <span>详细资料</span>
        <strong>{item.brief ? "主营、公告与研报" : "公告与研报"}</strong>
      </summary>
      <div className="task-details-body">
        {item.brief && <p className="task-brief"><span className="grade-chip grade-chip--中">主营</span>{item.brief}{item.brief_source && <em> · 来自{item.brief_source}</em>}</p>}
        {(item.links.length > 0 || item.reports.length > 0) && <div className="task-links">
          {item.links.map((link) => <a href={link.url} target="_blank" rel="noreferrer" key={link.url}>{link.label}</a>)}
          {item.reports.length > 0 && <span className="task-reports-label">券商研报（观点属机构，不代表本站判断）：</span>}
          {item.reports.map((report) => <a className="task-report" href={report.url ?? undefined} target="_blank" rel="noreferrer" key={`${report.org}-${report.date}-${report.title}`}>
            {report.org}{report.rating ? `·${report.rating}` : ""} {report.date} 《{report.title.slice(0, 20)}》
          </a>)}
        </div>}
      </div>
    </details>}
  </div>;
}

function TasksPage({ onOpenCompany }: { onOpenCompany: (id: number) => void }) {
  const [tasks, setTasks] = useState<ResearchTaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  async function reload() { setTasks(await getResearchTasks()); }
  useEffect(() => {
    let current = true;
    reload().catch((caught) => { if (current) setError(errorMessage(caught)); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, []);
  const open = tasks.filter((task) => task.status === "进行中");
  return <>
    <section className="page-intro archive-intro">
      <div><span className="section-kicker">RESEARCH TASKS</span><h1>研究任务</h1><p>逐家推进到建档或排除。</p></div>
      <div className="local-stamp"><span>OPEN</span><strong>{open.length} 个进行中</strong></div>
    </section>
    {error && <p className="form-error">{error}</p>}
    {loading && <div className="empty-state page-loading">正在读取研究任务…</div>}
    {!loading && tasks.length === 0 && <div className="empty-state">还没有研究任务。在“价值候选”页跑出一份清单后，点“存成研究任务”即可。</div>}
    {!loading && tasks.length > 0 && <section className="panel research-task-panel"><div className="task-list">
      {tasks.map((task) => <TaskCard task={task} onChanged={reload} onOpenCompany={onOpenCompany} key={task.id} />)}
    </div></section>}
  </>;
}

function routeFromPathname(rawPathname = window.location.pathname): { page: Page; companyId: number | null } {
  // 挂在 /stocks/ 下时，浏览器给的是 /stocks/review；先剥掉挂载前缀再匹配
  const pathname = ROUTE_BASE && rawPathname.startsWith(ROUTE_BASE) ? rawPathname.slice(ROUTE_BASE.length) || "/" : rawPathname;
  const companyMatch = pathname.match(/^\/companies\/(\d+)\/?$/);
  if (companyMatch) return { page: "company", companyId: Number(companyMatch[1]) };
  if (pathname === "/documents" || pathname === "/documents/") return { page: "docs", companyId: null };
  if (pathname === "/companies" || pathname === "/companies/") return { page: "companies", companyId: null };
  if (pathname === "/review" || pathname === "/review/") return { page: "review", companyId: null };
  if (pathname === "/portfolio" || pathname === "/portfolio/") return { page: "portfolio", companyId: null };
  if (pathname === "/reviews" || pathname === "/reviews/") return { page: "reviews", companyId: null };
  if (pathname === "/methods" || pathname === "/methods/") return { page: "methods", companyId: null };
  if (pathname === "/news" || pathname === "/news/") return { page: "news", companyId: null };
  // 老的 /chain 也送到新的产品/服务底图；研究报告仍属于具体公司。
  if (pathname === "/industry-chains" || pathname === "/industry-chains/"
      || pathname === "/chain" || pathname === "/chain/") return { page: "chain", companyId: null };
  if (pathname.startsWith("/reports")) return { page: "companies", companyId: null };
  if (pathname === "/preferences" || pathname === "/preferences/") return { page: "prefs", companyId: null };
  if (pathname === "/industries" || pathname === "/industries/") return { page: "industries", companyId: null };
  if (pathname === "/screener" || pathname === "/screener/") return { page: "screener", companyId: null };
  if (pathname === "/heatmap" || pathname === "/heatmap/") return { page: "heatmap", companyId: null };
  if (pathname === "/tasks" || pathname === "/tasks/") return { page: "tasks", companyId: null };
  if (pathname === "/decision-loop" || pathname === "/decision-loop/") return { page: "loop", companyId: null };
  if (pathname === "/swing" || pathname === "/swing/") return { page: "swing", companyId: null };
  if (pathname === "/rally" || pathname === "/rally/") return { page: "rally", companyId: null };
  if (pathname === "/data-sources" || pathname === "/data-sources/") return { page: "data", companyId: null };
  if (pathname === "/backups" || pathname === "/backups/") return { page: "backups", companyId: null };
  // 旧版的「决策归因」入口已收回：复核工作台只保留可行动的判断与证据。
  if (pathname === "/attribution" || pathname === "/attribution/") return { page: "reviews", companyId: null };
  return { page: "dashboard", companyId: null };
}

function pathForPage(page: Exclude<Page, "company">): string {
  return ROUTE_BASE + pathOf(page);
}

function pathOf(page: Exclude<Page, "company">): string {
  return page === "companies" ? "/companies" : page === "review" ? "/review" : page === "portfolio" ? "/portfolio" : page === "reviews" ? "/reviews" : page === "industries" ? "/industries" : page === "screener" ? "/screener" : page === "heatmap" ? "/heatmap" : page === "tasks" ? "/tasks" : page === "methods" ? "/methods" : page === "docs" ? "/documents" : page === "news" ? "/news" : page === "chain" ? "/industry-chains" : page === "reports" ? "/reports" : page === "prefs" ? "/preferences" : page === "data" ? "/data-sources" : page === "backups" ? "/backups" : page === "loop" ? "/decision-loop" : page === "swing" ? "/swing" : page === "rally" ? "/rally" : "/";
}

/** 分区页签：一级导航压到五项之后，同一段里的几个页面靠它切换。
 *
 * 只有一页的分区不画（「公司」进到详情页之后就只剩一页，画一条只有一个选项的
 * 页签条是纯噪音）。 */
function SectionTabs({ page, onNavigate }: {
  page: Page; onNavigate: (next: Exclude<Page, "company">) => void;
}) {
  const section = sectionOf(page);
  // **站主专属的页面不进页签。** 身份还没问回来时（null）也先不显示 ——
  // 先显示再收回去，那一闪对使用者就是「刚才那个菜单去哪了」。
  const isOwner = useIsOwner();
  const items = section.items.filter((item) => !item.ownerOnly || isOwner === true);
  if (items.length < 2) return null;
  const key = page === "company" ? "companies" : page;
  return (
    <nav className="section-tabs" role="tablist" aria-label={`${section.label}分区`}>
      {items.map((item) => (
        <button key={item.id} type="button" role="tab" aria-selected={item.id === key}
                className={`section-tab${item.id === key ? " section-tab--on" : ""}`}
                onClick={() => onNavigate(item.id as Exclude<Page, "company">)}>
          {item.label}
        </button>
      ))}
    </nav>
  );
}

/** 亿元。市值是用来区分重名的，精确到分毫没有意义，量级才有。 */
function capText(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "";
  const yi = value / 1e8;
  return yi >= 1000 ? `${Math.round(yi).toLocaleString()} 亿` : `${yi.toFixed(0)} 亿`;
}

/**
 * 顶栏搜索：**全站都能用，搜到就能去。**
 *
 * ## 原来它只在两个页面上有反应
 *
 * 这个框长在顶栏，每一页都看得见，可它的值只喂给了公司页和首页关注列表。
 * 在组合、复盘、行业、选股、热力图、方法、产业链、研究任务……这十几个页面上，
 * 你能往里打字、它也照常显示，但**什么都不会发生**。
 * 一个长在全站的框做着一页的事，那不是功能不全，是它在骗人。
 *
 * ## 而且它只搜已经建过档的公司
 *
 * 搜「宁德时代」什么也搜不到——不是没这家公司，是你还没建它的档。
 * 可"我想看看哪家"这件事**永远发生在建档之前**。所以这里同时问两处：
 * 你的档案，和全市场底座（本地一条 SQL，不联网、不调模型、不花积分）。
 * 档案里有的直接打开，没有的当场建档。
 *
 * ## 一件事，不是两件
 *
 * 顶栏只管"找到并前往"。列表筛选交给各自的页面自己做（公司页有它自己的筛选框）——
 * 同一个框既弹下拉又筛列表，两种反馈会互相打架。
 */
function GlobalSearch({ onOpenCompany, onCreated }: {
  onOpenCompany: (id: number) => void;
  onCreated: (company: CompanyDetail) => void;
}) {
  const [text, setText] = useState("");
  const [rows, setRows] = useState<UniverseMatch[]>([]);
  const [archive, setArchive] = useState<CompanyRecord[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [cursor, setCursor] = useState(-1);
  const [creating, setCreating] = useState("");
  const [error, setError] = useState("");
  const box = useRef<HTMLDivElement>(null);

  const needle = text.trim();

  // 打一个字查一次库没必要，但**等太久会让人以为坏了**。180ms 是"手指还没离开键盘"。
  useEffect(() => {
    if (!needle) { setRows([]); setArchive([]); setLoading(false); return; }
    setLoading(true);
    let live = true;
    const timer = window.setTimeout(() => {
      void Promise.all([lookupUniverse(needle, 8), getCompanies(needle)])
        .then(([market, mine]) => { if (!live) return; setRows(market); setArchive(mine); setError(""); })
        .catch((caught) => { if (live) { setRows([]); setArchive([]); setError(errorMessage(caught)); } })
        .finally(() => { if (live) setLoading(false); });
    }, 180);
    return () => { live = false; window.clearTimeout(timer); };
  }, [needle]);

  useEffect(() => {
    function onDocClick(event: MouseEvent) {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  // 档案里的排在前面。**同一家公司不出现两次**：底座那条把它去掉，
  // 由档案那条代表——档案那条能直接打开，信息更全。
  const mine = archive.slice(0, 6);
  const mineSymbols = new Set(mine.map((company) => company.symbol));
  const market = rows.filter((row) => !mineSymbols.has(row.symbol)).slice(0, 8);
  const items: Array<{ key: string; company_id: number | null; symbol: string; name: string; note: string }> = [
    ...mine.map((company) => ({
      key: `c${company.id}`, company_id: company.id, symbol: company.symbol, name: company.name,
      note: [company.watch_group, company.industry].filter(Boolean).join(" · "),
    })),
    ...market.map((row) => ({
      key: `u${row.symbol}`, company_id: row.company_id, symbol: row.symbol, name: row.name,
      note: [row.industry, capText(row.total_market_cap)].filter(Boolean).join(" · "),
    })),
  ];

  function reset() {
    setOpen(false); setText(""); setRows([]); setArchive([]); setCursor(-1);
  }

  async function choose(item: { company_id: number | null; symbol: string; name: string }) {
    if (item.company_id !== null) { reset(); onOpenCompany(item.company_id); return; }
    setCreating(item.symbol); setError("");
    try {
      // 名字只是入口。**建档仍然只认 StockSDK 校验回来的那份数据**——
      // 底座给的是代码，代码再走一次行情校验，名称与交易所以校验结果为准。
      const company = await createCompanyFromQuote({ symbol: item.symbol, watch_group: "观察池", description: "" });
      reset();
      onCreated(company);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setCreating("");
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") { setOpen(false); return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (items.length === 0) return;
      setOpen(true);
      setCursor((value) => nextCursor(value, event.key === "ArrowDown" ? 1 : -1, items.length));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const item = items[cursor] ?? items[0];
      if (item) void choose(item);
    }
  }

  const showPanel = open && needle.length > 0;

  return <div className="search-box-wrap" ref={box}>
    <label className="search-box">
      <Search size={17} aria-hidden="true" />
      <input type="search" value={text} role="combobox" aria-expanded={showPanel} aria-controls="global-search-results"
             onChange={(event) => { setText(event.target.value); setOpen(true); setCursor(-1); }}
             onFocus={() => setOpen(true)} onKeyDown={onKeyDown}
             placeholder="搜公司名或代码" aria-label="搜公司名或代码" />
    </label>
    {showPanel && <div className="search-results" id="global-search-results" role="listbox">
      {loading && items.length === 0 && <p className="search-results-note">正在找…</p>}
      {!loading && items.length === 0 && !error && <div className="search-results-empty">
        <p>全市场里没有叫「{needle}」的公司。</p>
        <p>换两个字试试，或者直接输入 6 位代码。</p>
      </div>}
      {mine.length > 0 && <p className="search-results-head">我的档案</p>}
      {items.map((item, index) => {
        if (index === mine.length && market.length > 0) {
          return <Fragment key={`${item.key}-head`}>
            <p className="search-results-head">全市场 · 还没建档</p>
            <SearchRow item={item} active={index === cursor} busy={creating === item.symbol} onPick={() => void choose(item)} />
          </Fragment>;
        }
        return <SearchRow key={item.key} item={item} active={index === cursor}
                          busy={creating === item.symbol} onPick={() => void choose(item)} />;
      })}
      {error && <p className="search-results-error">{error}</p>}
    </div>}
  </div>;
}

function SearchRow({ item, active, busy, onPick }: {
  item: { company_id: number | null; symbol: string; name: string; note: string };
  active: boolean; busy: boolean; onPick: () => void;
}) {
  return <button type="button" role="option" aria-selected={active}
                 className={`search-result${active ? " search-result--on" : ""}`}
                 disabled={busy} onClick={onPick}>
    <span className="search-result-name">{item.name}</span>
    <span className="search-result-meta">{item.symbol}{item.note ? ` · ${item.note}` : ""}</span>
    <span className="search-result-do">{busy ? "建档中…" : item.company_id !== null ? "打开档案" : "建档"}</span>
  </button>;
}

applyPrefs(readPrefs());

export default function App() {
  const initialRoute = routeFromPathname();
  const [marketError, setMarketError] = useState("");
  const [dashboard, setDashboard] = useState(emptyDashboard); const [dataSource, setDataSource] = useState<"loading" | "api" | "error">("loading"); const [sidebarOpen, setSidebarOpen] = useState(false); const [sidebarCollapsed, setSidebarCollapsed] = useState(false); const [page, setPage] = useState<Page>(initialRoute.page); const [selectedCompanyId, setSelectedCompanyId] = useState<number | null>(initialRoute.companyId); const [showCreate, setShowCreate] = useState(false); const [marketRefreshing, setMarketRefreshing] = useState(false);
  // 写判断的浮层。**挂在最外层**：从哪一页想起来的都能开，关掉回到原地。
  const [writing, setWriting] = useState<{ open: boolean; symbol?: string } | null>(null);

  async function loadDashboard(): Promise<DashboardSummary | null> {
    try { const next = await getDashboard(); setDashboard(next); setDataSource("api"); return next; }
    catch { setDataSource("error"); return null; }
  }
  async function refreshDashboard(): Promise<void> { await loadDashboard(); }
  // **首屏这一次很可能撞在身份还没就绪的那一瞬。**
  //
  // 2026-08-15 线上实测：站主打开首页，主站 `/v1/me` 在 21:51:48 返回 401，
  // 九秒后同一个人再问就是 200。看股这边把「没登录」按 Cookie 缓存了一会儿，
  // 于是那一批请求全部按游客处理，dashboard 返回 200 + 一份空档案——
  // 首页写着「已建档 0 家」，而他有 6 家公司。
  //
  // 而 dashboard **只在挂载时取这一次**：身份九秒后好了，云图的灯塔、
  // 决策看板的待办都回来了，只有这一块永远停在 0，直到他手动刷新页面。
  //
  // 所以：拿回来的这份如果是以游客身份查的，隔几秒再取一次。
  // 真游客最多多花两次请求，而站主不会再被一个瞬时 401 卡住一整个会话。
  useEffect(() => {
    let live = true;
    let timer = 0;
    void (async () => {
      const first = await loadDashboard();
      if (!live || !first?.viewer_is_guest) return;
      timer = window.setTimeout(() => { if (live) void loadDashboard(); }, 6000);
    })();
    return () => { live = false; window.clearTimeout(timer); };
  }, []);
  useEffect(() => {
    if (window.location.pathname === `${ROUTE_BASE}/attribution` || window.location.pathname === `${ROUTE_BASE}/attribution/`) {
      window.history.replaceState({}, "", pathForPage("reviews"));
    }
  }, []);
  useEffect(() => { const handlePopState = () => { const route = routeFromPathname(); setPage(route.page); setSelectedCompanyId(route.companyId); setShowCreate(false); }; window.addEventListener("popstate", handlePopState); return () => window.removeEventListener("popstate", handlePopState); }, []);
  const asOf = useMemo(() => formatDateTime(dashboard.as_of), [dashboard.as_of]);
  function navigate(next: Exclude<Page, "company">) { window.history.pushState({}, "", pathForPage(next)); setPage(next); setSelectedCompanyId(null); if (next !== "companies") setShowCreate(false); setSidebarOpen(false); }
  // tab：**跳过去要落在能做那件事的地方**，不是公司页的默认标签。
  // 首页那个「驳一驳这条」原来跳到公司简况，而反方在「研究」标签下半屏——
  // 使用者得自己找标签、再往下滚，等于按钮只完成了三分之一。
  // **intent 是"我来这一页要干什么"，不只是"我要看哪一页"。**
  //
  // 首屏那个「让它驳这条」原来只做到 tab=research，人落在页面顶部，
  // 而反方那一块在投资逻辑和证据档案下面、屏幕外——点完像什么都没发生。
  // 带上 intent=advocate，到了那一页自己滚过去、把问题填好。
  function openCompany(companyId: number, tab?: string, intent?: string) {
    const suffix = tab ? `?tab=${tab}${intent ? `&do=${intent}` : ""}` : "";
    window.history.pushState({}, "", `${ROUTE_BASE}/companies/${companyId}${suffix}`);
    setSelectedCompanyId(companyId); setShowCreate(false); setPage("company"); setSidebarOpen(false);
  }
  function openCreate() { window.history.pushState({}, "", `${ROUTE_BASE}/companies`); setPage("companies"); setSelectedCompanyId(null); setShowCreate(true); setSidebarOpen(false); }
  function startFirstJudgment() {
    const firstCompany = dashboard.watchlist[0];
    if (firstCompany) {
      setWriting({ open: true, symbol: firstCompany.symbol });
      return;
    }
    openCreate();
  }
  /**
   * 同步行情。**失败要说出来。**
   *
   * 原来这里只有 try/finally：`refreshMarket()` 抛出之后没人接，
   * 变成一个未捕获的 Promise 拒绝——按钮转完就停，页面上一个字都没有，
   * 用户只知道"点了没反应"。2026-08-19 巡检时撞到的就是这一下
   * （那次是 20 秒超时把一个 25 秒才回来的成功请求掐了）。
   */
  async function syncMarket() {
    setMarketRefreshing(true); setMarketError("");
    try {
      let job = await refreshMarket();
      // 后台任务：起完就返回，进度靠轮。**轮询要有尽头** ——
      // 没有上限的话，任务那头要是没了消息，按钮就永远停在「正在同步…」。
      for (let attempt = 0; attempt < 240 && job
           && (job.status === "排队中" || job.status === "运行中"); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2500));
        job = await getJob("market_refresh", 0) ?? job;
      }
      if (job?.status === "失败" || job?.status === "已中断") {
        setMarketError(job.error || job.note || "这次同步没跑完。");
      } else if (job?.status !== "已完成") {
        setMarketError("同步跑了十分钟还没回来，先按现有的数用，稍后再试。");
      }
      await refreshDashboard();
    }
    catch (caught) { setMarketError(errorMessage(caught)); }
    finally { setMarketRefreshing(false); }
  }
  return <><PlatformHeader /><div className={`app-shell${sidebarCollapsed ? " app-shell--collapsed" : ""}`}><Sidebar open={sidebarOpen} page={page} reviewCount={dashboard.counter_hits} dataSource={dataSource} onClose={() => { setSidebarOpen(false); setSidebarCollapsed(true); }} onNavigate={navigate} /><main className="main-content"><header className="topbar"><button className="icon-button menu-button" aria-label="打开导航" onClick={() => { setSidebarOpen(true); setSidebarCollapsed(false); }}><Menu size={20} /></button><GlobalSearch onOpenCompany={openCompany} onCreated={(company) => { void refreshDashboard(); openCompany(company.id); }} /><div className="topbar-actions">
        {/* **常驻。** 这个按钮要对付的不是"字段多"，是"路太长"——
            一闪而过的念头撑不到"先建档、等同步、走到某个页签"那么远。 */}
        <button className="page-action topbar-write" onClick={() => setWriting({ open: true })}>
          写下一个判断
        </button>
      </div></header><div className="page-frame"><SectionTabs page={page} onNavigate={navigate} />{/* **绕不开的那条提醒。** 反证命中是"你自己写下的那件事真的发生了"，在确认之前它跟着你换页——见 CounterHitBanner 的说明。 */}{/* **首页原来不出这条**，理由是"那一屏的 Headline 已经把同一条命中放大到整屏了"。
            那个理由在 Headline 被挪进折叠区之后就不成立了 —— 折叠时 {open && children}
            连 DOM 都没有，于是**首页成了唯一一个反证命中什么都不显示的页面**，
            而首页恰恰是所有人落地的第一屏。所以这条横幅现在每一页都出。
            展开折叠区时会跟 Headline 那块重复一次 —— 一条细横幅的重复，
            远好过"最要紧的提醒在首页看不见"。
            （原注：Headline 当初就是把这条横幅和反方入口合并成一块放到第一屏的，
          再挂一条细横幅是同一件事说两遍。其余页面照旧跟着换页。 */}
        {<Suspense fallback={null}><CounterHitBanner onOpenCompany={openCompany} /></Suspense>}{page === "dashboard" && <DashboardPage dashboard={dashboard} onOpenCompany={openCompany} onCreate={openCreate} onStartJudgment={startFirstJudgment} onRefreshMarket={() => void syncMarket()} refreshing={marketRefreshing} marketError={marketError} onNavigate={navigate} />}{page === "review" && <ReviewPage dashboard={dashboard} onOpenCompany={openCompany} onChanged={refreshDashboard} />}{page === "companies" && <CompaniesPage showCreate={showCreate} onOpenCompany={openCompany} onCloseCreate={() => setShowCreate((value) => !value)} onCreated={(company) => { void refreshDashboard(); openCompany(company.id); }} />}{page === "company" && selectedCompanyId !== null && <CompanyDetailPage companyId={selectedCompanyId} onBack={() => navigate("companies")} onArchiveChanged={refreshDashboard} />}{page === "portfolio" && <PortfolioPage onOpenCompany={openCompany} onLedgerChanged={refreshDashboard} />}{page === "reviews" && <ReviewsPage onOpenCompany={openCompany} onChanged={refreshDashboard} />}{page === "industries" && <IndustriesPage onOpenCompany={openCompany} />}{page === "screener" && <ScreenerPage onWrite={(symbol) => setWriting({ open: true, symbol })} />}{page === "heatmap" && <HeatmapPage onOpenCompany={openCompany} />}{page === "methods" && <MethodsPage onOpenCompany={openCompany} />}{page === "docs" && <section className="panel"><div className="panel-heading"><div><span className="eyebrow">读文档</span><PanelTitle hint="每个结论都带页码，能翻回原文核。">年报、公告、研报，读进来问它</PanelTitle></div></div><Suspense fallback={<div className="empty-state">正在加载…</div>}><Documents /></Suspense></section>}
      {page === "loop" && <Suspense fallback={<div className="empty-state page-loading">正在打开我的跟踪…</div>}><DecisionLoop onOpenCompany={openCompany} onOpenPortfolio={() => navigate("portfolio")} /></Suspense>}
      {page === "swing" && <Suspense fallback={<div className="empty-state page-loading">正在打开做 T 回测…</div>}><SwingLab onOpenCompany={openCompany} /></Suspense>}
      {page === "rally" && <Suspense fallback={<div className="empty-state page-loading">正在打开涨跌归因…</div>}><RallyType onOpenCompany={openCompany} /></Suspense>}
      {page === "news" && <NewsPageView onOpenCompany={openCompany} />}
      {page === "chain" && <Suspense fallback={<div className="empty-state page-loading">正在打开产业链底图…</div>}><IndustryChainPage onOpenCompany={openCompany} /></Suspense>}
      {page === "reports" && <ReportsPage onOpenCompany={openCompany} />}
      {page === "prefs" && <PreferencesPage />}
      {page === "tasks" && <TasksPage onOpenCompany={openCompany} />}{page === "data" && <DataStatusPage />}{page === "backups" && <BackupPage />}<footer className="page-footer"><span>虾米看股 · 本地研究档案</span><span>{asOf} · 不构成投资建议</span></footer></div></main></div>{writing?.open && <div className="qt-scrim" role="dialog" aria-modal="true" aria-label="写下一个判断"
       onClick={(event) => { if (event.target === event.currentTarget) setWriting(null); }}>
      <Suspense fallback={<div className="qt"><p>正在加载…</p></div>}>
        <QuickThesis symbol={writing.symbol} onClose={() => setWriting(null)}
                     onDone={(companyId) => { setWriting(null); void refreshDashboard(); openCompany(companyId); }} />
      </Suspense>
    </div>}<ConfirmHost /><PlatformFooter /></>;
}
