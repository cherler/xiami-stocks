import { test } from "node:test";
import assert from "node:assert/strict";
import { trackingRows } from "./tracking.ts";
import type { DecisionLoopView, DecisionLoopItem } from "../api.ts";

const research = (id: number) => ({ company_id: id, name: `公司${id}`, symbol: String(id),
  industry: "", is_sample: 0, thesis_count: 0, latest_claim: null, thesis_status: null,
  valuation_count: 0, report_count: 0, report_title: null, price: null, price_date: null });
const card = (id: number) => ({ ...research(id), state: "triggered" } as unknown as DecisionLoopItem);
const board = (groups: DecisionLoopView["groups"], ids: number[]) => ({ groups,
  research: ids.map(research) } as DecisionLoopView);
const group = (items: DecisionLoopItem[], actionable: boolean) => ({
  state: "triggered", label: "", means: "", next: "", actionable, items, count: items.length });

test("没有卡片时展示已有公司，空的待办分组不制造条目", () => {
  assert.deepEqual(trackingRows(board([group([], true)], [1, 2])).map(r => r.company_id), [1, 2]);
});
test("有变化的优先、公司不重复、不漏掉研究池外的持仓计划", () => {
  const input = board([group([card(2), card(3)], true), group([card(1)], false)], [1, 2, 4]);
  const before = JSON.stringify(input);
  assert.deepEqual(trackingRows(input).map(r => r.company_id), [2, 3, 1, 4]);
  assert.equal(JSON.stringify(input), before);
});
