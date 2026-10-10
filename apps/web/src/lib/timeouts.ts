/**
 * 请求超时。**默认 20 秒，AI 那几条走 240 秒。**
 *
 * 没有超时的 fetch 会一直挂着：移动网络切换、后端卡在一次外部数据源上、
 * 反代那头断了但没关连接——这几种情况下页面上的按钮会永远停在「正在…」，
 * 而用户唯一能做的是刷新整页。转圈不结束比报错更难受：报错至少能重试。
 *
 * 20 秒是按"本地一条 SQL + 一次外部行情"给的上限。模型调用另算：
 * 深度报告、反方复核这些本来就要一两分钟，用同一个数会把正常的调用掐掉。
 */
export const TIMEOUT_MS = 20_000;
export const SLOW_TIMEOUT_MS = 240_000;
// **这里曾经有第三档 DATA_TIMEOUT_MS = 90 秒**，为「同步实时行情」加的。
// 线上复验时它又超了 —— 那活要跑几分钟。继续加大只是把"静默失败"换成
// "干等四分钟"，所以那个接口改成了后台任务，这一档也就没有存在的理由了。
// 一个被线上证伪过的档位留在这儿，只会让下一个人以为"放宽超时"是个办法。

/** 这些路径下的请求是模型调用，慢是正常的。 */
export const SLOW_PATHS = [
  "/advocate", "/deep-report", "/reports", "/draft", "/assess", "/ai-pick",
  "/agent-pool", "/classify", "/promises", "/chain/draft",
  "/digest", "/ask", "/fundraising",   // 读文档：出结果、追问、抽募投都是模型调用
];

/**
 * 同一个路径 **GET 快、POST 才调模型** 的那几条。
 *
 * 上面那张子串表没有方法这一维，分不出这种：
 * `GET /companies/8/evidence-direction` 是读已经判好的结果，
 * `POST` 才去调模型重判；`GET /value-candidates/review/status` 是查进度，
 * `POST /value-candidates` 才真的跑一轮筛选。
 * 用子串一刀切，会把快的那半边也拖成 240 秒——请求真挂住时要等四分钟才报错。
 *
 * 所以这几条按**归一化之后的完整路径**精确匹配，只对 POST 生效。
 *
 * 2026-08-18 实测撞到的：「自动整理收件箱」（POST /inbox/tidy）不在任何一张表里，
 * 拿的是默认 20 秒，而它一次要跑 5 批模型分级，线上必然超时。
 */
const SLOW_POST_ROUTES = [
  "/api/v1/inbox/tidy",
  "/api/v1/counter-hits/check",
  "/api/v1/value-candidates",
  "/api/v1/companies/{id}/evidence-direction",
  // 涨跌归因：**GET 是纯算术，POST 才调模型。**
  // 写进上面那张子串表的话，`GET /rally` 也会拿到 240 秒 ——
  // 而它本来一百毫秒就回来了，真挂住时要等四分钟才报错。
  "/api/v1/companies/{id}/rally/narrate",
];

/** 去掉 query、把数字 id 段换成 {id}，好跟上面那张表按整条路径比。 */
function routeKey(path: string): string {
  return path.split("?")[0].replace(/\/\d+(?=\/|$)/g, "/{id}");
}

/**
 * 这个请求会不会走到模型。
 *
 * **两件事都由它决定**：给多长超时，以及扣完分之后要不要让顶栏重新拉余额。
 * 原来这两处各自 `SLOW_PATHS.some(...)`，加路径时很容易只改一处 ——
 * 那样表现出来是「整理完了，但顶栏的积分还是旧数」。
 */
export function isModelCall(path: string, method = "GET"): boolean {
  if (SLOW_PATHS.some((slow) => path.includes(slow))) return true;
  return method.toUpperCase() === "POST" && SLOW_POST_ROUTES.includes(routeKey(path));
}

export function timeoutFor(path: string, method = "GET"): number {
  return isModelCall(path, method) ? SLOW_TIMEOUT_MS : TIMEOUT_MS;
}
