/**
 * 三情景估值的算术，**前端这一份只为了让你边改边看到结果**。
 *
 * ## 为什么要在前端再算一遍
 *
 * 原来输入框绑的是你敲的草稿，而「每股价值」那一列读的是服务端上次算好的结果——
 * **你改输入框，右边永远不动**，要按「存下这组假设」才会重算。
 * 使用者的原话是「那几个每股价值都不会变化的，是我看不懂、还是 bug」。是 bug。
 *
 * ## 同一个公式写在两处，迟早会漂
 *
 * 这是本仓明确反对的事（见 lib/credits.ts 开头）。这里仍然这么做，是因为
 * 估值是一个**边改边看**的动作：每敲一个数字发一次请求，等回来再显示，
 * 那个页面没法用。
 *
 * 代价用一条守卫抵掉：`valuation.test.ts` 里钉着一组**由 Python 那一份算出来的
 * 标准答案**，两边任何一侧改了公式，那条测试就会红。
 * 真源永远是 `apps/api/stock_decision/scenarios.py`；这一份是它的镜子。
 */

export interface ValuationInputs {
  /** 起点营收（元）。注意是元，不是亿元。 */
  baseRevenue: number;
  /** 总股本（股）。 */
  shares: number;
  years: number;
  /** 折现率，百分数（10 表示 10%）。 */
  discountRate: number;
}

export interface ScenarioInputs {
  /** 收入年增，百分数。 */
  revenueGrowth: number;
  /** 净利率，百分数。 */
  netMargin: number;
  exitPe: number;
}

export interface ScenarioValue {
  /** n 年后的营收（元）。**摆出来它才能被证伪**：
   *  乐观情景算出每股三千多的时候，这一行会写着「五年后营收 3.6 万亿」。 */
  futureRevenue: number | null;
  futureProfit: number | null;
  perShare: number | null;
}

/** 一个情景算出的每股价值。跟 `scenarios.value_of` 逐行对应。 */
export function valueOf(scenario: ScenarioInputs, facts: ValuationInputs): ScenarioValue {
  const { baseRevenue, shares, years, discountRate } = facts;
  if (!(baseRevenue > 0) || !(shares > 0) || !(years > 0)) {
    return { futureRevenue: null, futureProfit: null, perShare: null };
  }
  const futureRevenue = baseRevenue * (1 + scenario.revenueGrowth / 100) ** years;
  const futureProfit = futureRevenue * scenario.netMargin / 100;
  const futureCap = futureProfit * scenario.exitPe;
  const presentCap = futureCap / (1 + discountRate / 100) ** years;
  return {
    // **跟 Python 那边一样取两位小数再比**，否则标准答案对不上最后一位。
    futureRevenue: round2(futureRevenue),
    futureProfit: round2(futureProfit),
    perShare: round2(presentCap / shares),
  };
}

/** 当前价格要求收入年增多少。跟 `scenarios.implied_growth` 逐行对应。 */
export function impliedGrowth(price: number, scenario: ScenarioInputs,
                              facts: ValuationInputs): number | null {
  const { baseRevenue, shares, years, discountRate } = facts;
  if (!(price > 0) || !(baseRevenue > 0) || !(shares > 0) || !(years > 0)
      || !(scenario.netMargin > 0) || !(scenario.exitPe > 0)) return null;
  const neededCap = price * shares * (1 + discountRate / 100) ** years;
  const neededRevenue = neededCap / scenario.exitPe / (scenario.netMargin / 100);
  const ratio = neededRevenue / baseRevenue;
  if (ratio <= 0) return null;
  return round2((ratio ** (1 / years) - 1) * 100);
}

function round2(value: number): number {
  return Number.isFinite(value) ? Math.round(value * 100) / 100 : NaN;
}

/** 把元换成「X 亿」「X 万亿」。**五年后的营收要一眼能跟别的公司比大小。** */
export function inYi(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const yi = value / 1e8;
  if (Math.abs(yi) >= 10000) return `${(yi / 10000).toFixed(2)} 万亿`;
  if (Math.abs(yi) >= 100) return `${yi.toFixed(0)} 亿`;
  return `${yi.toFixed(1)} 亿`;
}
