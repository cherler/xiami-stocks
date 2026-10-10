/**
 * 估值公式的**两侧一致性**守卫。
 *
 * 真源是 ； 是它在浏览器里的
 * 镜子，存在的理由是让人能边改边看到结果（见那个文件开头）。
 *
 * **同一个公式写在两处，迟早会漂。** 这里钉一组由 Python 那一份真跑出来的标准答案：
 * 任何一侧改了公式，这条测试就红。
 *
 * 标准答案怎么来的（改公式时照这个重生成）：
 *
 *     ./.venv/bin/python -c "
 *     import sys; sys.path.insert(0,'apps/api')
 *     from stock_decision.scenarios import Scenario, value_of, implied_growth
 *     print(value_of(Scenario('base', 8.84, 11.66, 24.8), 423701834000.0,
 *                    4551419768.664564, 5, 10.0))"
 *
 * 底数取的是宁德时代 2025 年报：营收 4237 亿、总股本 45.51 亿股、现价 304.63。
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { valueOf, impliedGrowth, inYi } from "./valuation.ts";

const FACTS = { baseRevenue: 423701834000.0, shares: 4551419768.664564, years: 5, discountRate: 10.0 };
const PRICE = 304.63;

/** 由 apps/api/stock_decision/scenarios.py 真跑出来的。**不要手改这里的数。** */
const GOLDEN = [
  { name: "宁德·基准5年10%", growth: 8.84, margin: 11.66, pe: 24.8, years: 5, rate: 10.0,
    futureRevenue: 647147100065.1, futureProfit: 75457351867.59, perShare: 255.3, implied: 12.75 },
  { name: "宁德·悲观5年10%", growth: -9.7, margin: 9.35, pe: 21.0, years: 5, rate: 10.0,
    futureRevenue: 254389449453.43, futureProfit: 23785413523.9, perShare: 68.14, implied: 21.83 },
  { name: "宁德·乐观5年10%", growth: 53.13, margin: 17.04, pe: 42.3, years: 5, rate: 10.0,
    futureRevenue: 3567481720182.61, futureProfit: 607898885119.12, perShare: 3508.01, implied: -6.07 },
  { name: "1年5%", growth: 20.0, margin: 11.66, pe: 24.6, years: 1, rate: 5.0,
    futureRevenue: 508442200800.0, futureProfit: 59284360613.28, perShare: 305.17, implied: 19.79 },
  { name: "零增长3年8%", growth: 0.0, margin: 10.0, pe: 20.0, years: 3, rate: 8.0,
    futureRevenue: 423701834000.0, futureProfit: 42370183400.0, perShare: 147.8, implied: 27.26 },
  { name: "负增长10年12%", growth: -5.0, margin: 8.0, pe: 15.0, years: 10, rate: 12.0,
    futureRevenue: 253685939238.85, futureProfit: 20294875139.11, perShare: 21.54, implied: 23.82 },
];

test("每股价值跟后端算出来的一模一样", () => {
  for (const g of GOLDEN) {
    const facts = { ...FACTS, years: g.years, discountRate: g.rate };
    const got = valueOf({ revenueGrowth: g.growth, netMargin: g.margin, exitPe: g.pe }, facts);
    assert.equal(got.perShare, g.perShare, `${g.name} 的每股价值对不上后端`);
    assert.equal(got.futureRevenue, g.futureRevenue, `${g.name} 的未来营收对不上后端`);
    assert.equal(got.futureProfit, g.futureProfit, `${g.name} 的未来净利对不上后端`);
  }
});

test("反推的隐含增速跟后端算出来的一模一样", () => {
  for (const g of GOLDEN) {
    const facts = { ...FACTS, years: g.years, discountRate: g.rate };
    const got = impliedGrowth(PRICE, { revenueGrowth: g.growth, netMargin: g.margin, exitPe: g.pe }, facts);
    assert.equal(got, g.implied, `${g.name} 的隐含增速对不上后端`);
  }
});

test("算不出来的时候返回 null，不返回 0", () => {
  // **0 会被当成「它一文不值」**，而真相是这一项没数据。
  const broken = { ...FACTS, shares: 0 };
  assert.equal(valueOf({ revenueGrowth: 10, netMargin: 10, exitPe: 20 }, broken).perShare, null);
  assert.equal(valueOf({ revenueGrowth: 10, netMargin: 10, exitPe: 20 }, { ...FACTS, years: 0 }).perShare, null);
  assert.equal(impliedGrowth(0, { revenueGrowth: 10, netMargin: 10, exitPe: 20 }, FACTS), null);
  assert.equal(impliedGrowth(PRICE, { revenueGrowth: 10, netMargin: 0, exitPe: 20 }, FACTS), null);
});

test("五年后的营收要一眼能跟别的公司比大小", () => {
  // 乐观情景算出每股三千多的时候，这一行会写着「3.57 万亿」——
  // **那个数字自己会说话**：比中国石化还大。
  assert.equal(inYi(423701834000), "4237 亿");
  assert.equal(inYi(3566700000000), "3.57 万亿");
  assert.equal(inYi(null), "—");
});
