/**
 * 列表上写着几条，就得让人够得着几条。
 *
 * 2026-08-19 巡检实测（待办复核页）：
 *
 *   「已归档」页面写着「窗口内 65 条」，只渲染 40 行
 *   「已忽略」写着 46 条，40 行
 *   「全部」  写着 203 条，40 行 —— **163 条永远够不着**
 *
 * 没有翻页、没有「加载更多」，滚到底也不加载。而「已忽略」正是自动整理
 * 成批扫走的那些 ——「忽略了什么、能不能拿回来」本来就是这一页存在的理由。
 *
 * repository.list_inbox 的注释里批过同一个病：
 * 「页面上就成了"说有 23 条、一条都不给看"」。那次修的是筛选导致的空列表，
 * 这道 40 的天花板是同一件事的另一面。
 *
 * 这里测源码结构：真实分页要跑浏览器，而门禁里没有浏览器。
 * 结构测不了"点了之后真的多出 40 行"，但拦得住"把出口删掉"和"把 limit 写死"。
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const APP = readFileSync(join(import.meta.dirname, "..", "App.tsx"), "utf8");

/** 取出收件箱那个组件的函数体。 */
function inboxSource(): string {
  const at = APP.indexOf('const [box, setBox] = useState<"待核验"');
  assert.notEqual(at, -1, "找不到收件箱组件 —— 改名了就把这条测试一起改");
  return APP.slice(at, at + 9000);
}

test("取多少条是可变的，不是写死 40", () => {
  const src = inboxSource();
  assert.match(src, /const \[limit, setLimit\] = useState\(\d+\)/,
    "条数写死了，用户永远只能看到第一批");
  assert.doesNotMatch(src, /getInbox\([^)]*,\s*40\s*,/,
    "还在往 getInbox 里传死值 40");
});

test("取满了要给出口，并说清还剩多少", () => {
  const src = inboxSource();
  assert.match(src, /setLimit\(\(n\) => .*n \+ \d+/, "没有「再看一批」的入口");
  // 只给按钮不给数字也不行：人得知道还差多少才决定要不要点。
  assert.match(src, /page\.in_window - items\.length/,
    "没告诉用户还有多少条没展开");
});

test("出口只在真的还有剩的时候出现", () => {
  // 否则每一页底下都挂一句"还有 0 条"，比没有更烦。
  assert.match(inboxSource(), /items\.length >= limit && page\.in_window > items\.length/,
    "没判断「取满了」和「确实还有剩」这两个条件");
});

test("换筛选要收回展开的批次", () => {
  // 在「已归档」展开到 200 条，切回「待核验」不该一次拉 200 条。
  assert.match(inboxSource(), /useEffect\(\(\) => \{ setLimit\(40\); \}, \[days, grade, box\]\)/,
    "换筛选时没有复位 —— 会带着几百条走");
});

test("展开有上限，而且跟后端对齐", () => {
  // 接口是 `limit: int = Query(default=40, ge=1, le=200)`。
  // 不夹住的话点到第六次就是 422，整页报错 —— 那比看不全更糟。
  // 这个隐患是加完「再看 40 条」之后自己试出来的：40→80→…→240 就炸。
  const src = inboxSource();
  assert.match(APP, /const INBOX_MAX = 200;/, "没有定义上限");
  assert.match(src, /Math\.min\(n \+ \d+, INBOX_MAX\)/, "累加没有夹上限");
  assert.match(src, /limit < INBOX_MAX/, "到顶之后还在给「再看」按钮");
});

test("后端的上限没变过", () => {
  // 上面那个 200 是抄后端的。后端改了而前端没跟，用户点到某一次就 422。
  const main = readFileSync(
    join(import.meta.dirname, "..", "..", "..", "api", "stock_decision", "main.py"), "utf8");
  const at = main.indexOf("def get_inbox(");
  assert.notEqual(at, -1, "找不到 get_inbox");
  assert.match(main.slice(at, at + 400), /limit: int = Query\(default=\d+, ge=1, le=200\)/,
    "后端的 limit 上限变了 —— 前端 INBOX_MAX 要跟着改");
});
