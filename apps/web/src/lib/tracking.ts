import type { DecisionLoopItem, DecisionLoopView } from "../api";

type Research = DecisionLoopView["research"][number];
export type TrackingRow = Research & { card?: DecisionLoopItem; actionable: boolean };

/** 只合并展示，不为已有公司创建决策卡。保留未在研究池里的持仓/计划。 */
export function trackingRows(board: DecisionLoopView): TrackingRow[] {
  const rows = new Map<number, TrackingRow>((board.research ?? []).map((item) =>
    [item.company_id, { ...item, actionable: false }]));
  for (const group of board.groups) {
    for (const card of group.items) {
      const research = rows.get(card.company_id) ?? {
        company_id: card.company_id, name: card.name, symbol: card.symbol,
        industry: card.industry, is_sample: 0, thesis_count: 0, latest_claim: null,
        thesis_status: null, valuation_count: 0, report_count: 0, report_title: null,
        price: card.price, price_date: card.price_date,
      };
      rows.set(card.company_id, { ...research, card, actionable: group.actionable });
    }
  }
  const rank = (row: TrackingRow) => row.actionable ? 0 : row.card ? 1
    : row.thesis_count + row.valuation_count + row.report_count > 0 ? 2 : 3;
  return [...rows.values()].sort((a, b) => rank(a) - rank(b));
}

export function researchSummary(row: TrackingRow): string {
  return [row.thesis_count > 0 ? `${row.thesis_count} 条判断` : "",
    row.valuation_count > 0 ? "已有估值" : "",
    row.report_count > 0 ? `${row.report_count} 份报告` : ""].filter(Boolean).join(" · ") || "已有公司档案";
}
