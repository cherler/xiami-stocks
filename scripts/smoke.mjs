/**
 * 上线前的冒烟测试。**跑真实的部署形态，不是单元测试。**
 *
 *   node scripts/smoke.mjs                          # 默认打本机网关 :8090（/stocks/ 分流）
 *   node scripts/smoke.mjs --base http://127.0.0.1:8091
 *   node scripts/smoke.mjs --api-only               # 只做接口层检查，不起浏览器
 *
 * ## 为什么需要它
 *
 * 这个仓的单元测试很厚（后端 670 条），但它们全都绕过了两样东西：
 * **部署形态**（挂在 /stocks/ 子路径下、接口前缀是 /stocks-api）和**浏览器**。
 * 已经因此漏过两次：
 *
 * - 三个下载链接裸写 `/api/...`，测试只看 `fetch(` 所以一直没发现，线上点了是 404；
 * - 熔断抛的 CreditsError 被接口层的 `except RuntimeError` 改写成 503，
 *   而单测直接调 `llm.reserve()`，根本走不到那一层。
 *
 * 两个都是"本地全绿、真跑才炸"。所以这支脚本只做真跑。
 *
 * ## 一条铁律：**找不到目标 = 失败，不是跳过**
 *
 * 第一版里"页面上没有可删的策略"被我写成了跳过，于是整支脚本打印了绿色的 ✓ ——
 * 而真正要验的那一步一次都没跑。检查项找不到落点时必须报错，
 * 否则这支脚本会在最需要它的时候说"一切正常"。
 */
import { argv, exit } from "node:process";

const args = new Map();
for (let i = 2; i < argv.length; i += 1) {
  if (argv[i].startsWith("--")) args.set(argv[i].slice(2), argv[i + 1]?.startsWith("--") ? true : argv[i + 1]);
}
const BASE = String(args.get("base") || "http://127.0.0.1:8090").replace(/\/$/, "");
const API = `${BASE}/stocks-api`;
const apiOnly = args.has("api-only");

const results = [];
const check = async (name, fn) => {
  try {
    const detail = await fn();
    results.push({ ok: true, name, detail: detail || "" });
  } catch (error) {
    results.push({ ok: false, name, detail: String(error.message || error) });
  }
};
const must = (condition, message) => { if (!condition) throw new Error(message); };

// ── 接口层：这些不需要浏览器 ────────────────────────────────────────────

await check("后端活着，并且说得出自己连的是哪个库", async () => {
  const health = await (await fetch(`${API}/health`)).json();
  must(health.status === "ok", `health 不是 ok：${JSON.stringify(health)}`);
  return `${health.database}｜访问姿态 ${health.access}｜行级安全 ${health.row_level_security}`;
});

await check("运营脉搏：AI 没有因为闸口宕掉而停摆", async () => {
  const health = await (await fetch(`${API}/health`)).json();
  const ops = health.ops;
  must(ops, "/health 里没有 ops —— 漏计费、任务连着失败、数据源太旧这三件事就没人看得见");
  // **只有"AI 停摆"算失败。** 数据源旧了、昨天有几个任务失败，都是"该有人看一眼"，
  // 不是"别上线"——把它们判成失败，这支脚本很快会被当成狼来了。
  must(!ops.ai_paused, `AI 已因积分闸口不可用而暂停（最近 ${ops.unbilled_recent} 次未计费）`);
  const notes = (ops.alerts || []).length ? `　⚠️ ${ops.alerts.join("；")}` : "";
  return `一天内失败任务 ${ops.jobs_failed_24h ?? "?"} 个｜待对账 ${ops.unbilled_pending} 条${notes}`;
});

await check("多用户模式下行级安全必须是生效的", async () => {
  const health = await (await fetch(`${API}/health`)).json();
  if (health.access === "owner" || String(health.database).startsWith("sqlite")) return "单机/仅站主，这条不适用";
  must(health.row_level_security === "生效",
    `多用户模式下行级安全是「${health.row_level_security}」——别人的研究记录可能被读到`);
  return "生效";
});

await check("导出接口在 /stocks-api 下拿得到（线上裸写 /api 会打到主站）", async () => {
  for (const path of ["/api/v1/companies/export", "/api/v1/export"]) {
    const response = await fetch(`${API}${path}`);
    must(response.ok, `${path} 返回 ${response.status}`);
  }
  return "两个导出接口都是 200";
});

await check("计费状态带着未计费台账", async () => {
  const state = await (await fetch(`${API}/api/v1/credits/state`)).json();
  must(state.unbilled, "credits/state 里没有 unbilled —— 闸口宕掉时漏了多少就没人看得见");
  const { recent, threshold, pending, paused } = state.unbilled;
  must(typeof recent === "number" && typeof threshold === "number", "unbilled 字段不完整");
  return `最近 ${recent} 次未计费（阈值 ${threshold}）｜待对账 ${pending} 条｜停手中 ${paused}`;
});

await check("监测上报收得下（未登录也要收）", async () => {
  // **这一条是上线后才补的。** 本机冒烟打的是 open 姿态的实例，
  // 而线上是 multi：游客的写请求被中间件一律挡成 401，于是监测上报
  // 在公网上一条都收不到——本地全绿、真跑才炸的又一例。
  const response = await fetch(`${API}/api/v1/rum`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page: "companies", kind: "nav", device: "desktop", lcp_ms: 1234 }),
  });
  must(response.status === 204,
    `上报返回 ${response.status}（要 204）——401 说明它被当成"游客不能写"挡掉了`);
  return "204";
});

await check("资金流有本地快照，并且说得出截至什么时候", async () => {
  const view = await (await fetch(`${API}/api/v1/market/fund-flow`)).json();
  must(Array.isArray(view.points), "没有 points");
  must("degraded" in view && "synced_at" in view,
    "缺 degraded / synced_at —— 降级返回的旧数据必须能被看出来是旧的");
  return `${view.points.length} 个点｜截至 ${view.as_of}｜同步于 ${view.synced_at}｜降级 ${view.degraded}`;
});

// ── 浏览器层：部署形态 + 真实交互 ──────────────────────────────────────

if (!apiOnly) {
  // playwright **故意不进 package.json**：部署脚本在仓根跑 npm ci，
  // 加进去等于让应用服务器下载一套浏览器（一百多兆），而那台机器不跑测试。
  // 所以用 PLAYWRIGHT_PATH 指向已有的安装，或者本机临时 npm i -D playwright。
  const modulePath = process.env.PLAYWRIGHT_PATH || "playwright";
  let chromium;
  try {
    ({ chromium } = await import(modulePath));
  } catch (error) {
    // **不许静默跳过。** 浏览器这一层挡的正是单测挡不住的那类问题。
    results.push({ ok: false, name: "浏览器检查",
      detail: `加载不到 playwright（${modulePath}）：设 PLAYWRIGHT_PATH 指向已装好的那份，`
        + "或本机 npm i -D playwright；只想跑接口层就显式加 --api-only" });
    report();
  }
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  let nativeDialogs = 0;
  page.on("dialog", async (dialog) => { nativeDialogs += 1; await dialog.dismiss(); });

  await check("页面上的下载链接指向 /stocks-api，不是裸的 /api", async () => {
    await page.goto(`${BASE}/stocks/companies`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    const links = await page.locator("a").evaluateAll((els) => els
      .filter((el) => /导出|下载/.test(el.textContent || ""))
      .map((el) => ({ text: el.textContent.trim(), href: el.getAttribute("href") })));
    must(links.length > 0, "这一页上一个导出链接都没找到——检查项落空了，不能算通过");
    const bare = links.filter((link) => (link.href || "").startsWith("/api/"));
    must(bare.length === 0, `还有裸写 /api 的：${bare.map((l) => l.text).join("、")}`);
    return links.map((l) => `${l.text}→${l.href}`).join("；");
  });

  await check("删除类动作弹站内确认框；Esc 不误删，确认才发请求", async () => {
    let deletes = 0;
    await page.route("**/stocks-api/api/v1/theses/**", async (route) =>
      route.request().method() === "DELETE"
        ? (deletes += 1, route.fulfill({ status: 204, body: "" }))
        : route.fallback());
    // **要找一家真有投资逻辑的公司。** 第一版取的是列表里的第一家，
    // 而列表里没有 thesis_count 这个字段，`?? 1` 于是永远为真 —— 挑中的那家
    // 一条逻辑都没有，页面上自然没有删除按钮，检查项直接落空。
    // 落空被这支脚本判成失败（而不是跳过），所以它当场就露馅了。
    const companies = await (await fetch(`${API}/api/v1/companies`)).json();
    let withThesis = null;
    for (const company of companies) {
      const detail = await (await fetch(`${API}/api/v1/companies/${company.id}`)).json();
      if ((detail.theses || []).length > 0) { withThesis = company; break; }
    }
    must(withThesis, "库里没有任何一条投资逻辑，这条验不了——先写一条再跑");
    await page.goto(`${BASE}/stocks/companies/${withThesis.id}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);
    await page.locator("button", { hasText: "逻辑与证据" }).first().click();
    await page.waitForTimeout(2000);
    const del = page.locator("button", { hasText: /^删除$|^删掉/ }).first();
    must(await del.count(), "这一页没有删除入口——检查项落空了，不能算通过");

    await del.click();
    await page.waitForTimeout(500);
    const box = page.locator(".confirm-box");
    must(await box.count(), "点了删除但站内确认框没出来（是不是又退回 window.confirm 了）");
    const copy = (await box.innerText()).replace(/\s+/g, " ").slice(0, 60);

    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
    must(!(await box.count()), "Esc 关不掉确认框");
    must(deletes === 0, `Esc 取消之后竟然发了 ${deletes} 个删除请求`);

    await del.click();
    await page.waitForTimeout(400);
    await page.locator(".confirm-box .page-action").click();
    await page.waitForTimeout(900);
    must(deletes === 1, `确认之后应当发 1 个删除请求，实际 ${deletes}`);
    return `「${copy}…」｜Esc 不删｜确认才删`;
  });

  await check("请求卡住时页面会说超时，而不是一直转圈", async () => {
    await page.route("**/stocks-api/api/v1/companies*", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 25_000));
      await route.abort();
    });
    const started = Date.now();
    await page.goto(`${BASE}/stocks/companies`, { waitUntil: "domcontentloaded" });
    await page.getByText(/请求超时/).first().waitFor({ timeout: 30_000 });
    await page.unroute("**/stocks-api/api/v1/companies*");
    return `${((Date.now() - started) / 1000).toFixed(1)} 秒时给出了超时提示`;
  });

  await check("全程没有弹出浏览器原生确认框", async () => {
    must(nativeDialogs === 0, `弹了 ${nativeDialogs} 次原生框——它会阻塞主线程，手机上还会带出主站域名`);
    return "0 次";
  });

  await check("我的判断三页：星号不许漏到界面上，窄屏不许横向溢出", async () => {
    // **后端的散文用 `**粗体**` 标重点，渲染时要拆掉。**
    //
    // 漏一处的表现是界面上明晃晃两个星号 —— 而 tsc 不管（className 与文本
    // 都只是字符串）、单测不管、构建也不管。2026-09-22 决策卡那一页就漏了
    // 三处（守卫的「去哪补」、价格带说明、触发提示），是对着截图才看见的。
    //
    // 窄屏溢出同理：1440 宽下一切正常，390 宽下判据表整片被推到屏幕外。
    const bad = [];
    for (const [name, path] of [["决策闭环", "/stocks/decision-loop"],
                                ["做 T 回测", "/stocks/swing"],
                                ["涨跌归因", "/stocks/rally"]]) {
      await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
      await page.waitForTimeout(1800);
      const stars = await page.evaluate(() =>
        (document.body.innerText.match(/\*\*[^*\n]{2,40}\*\*/g) || []).slice(0, 3));
      if (stars.length) bad.push(`${name} 星号：${stars.join(" / ")}`);
      await page.setViewportSize({ width: 390, height: 900 });
      // **改完视口要等重排。** 立刻量的话拿到的是上一个宽度下的 scrollWidth，
      // 配上新的 clientWidth —— 这个差值既可能虚报一个几百像素的溢出，
      // 也可能在真溢出时读出 0。实测虚报过一次 708px，而页面其实是好的。
      await page.waitForFunction(() => document.documentElement.clientWidth <= 400,
                                 null, { timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (overflow > 2) bad.push(`${name} 390px 下横向溢出 ${overflow}px`);
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.waitForTimeout(200);
    }
    must(bad.length === 0, bad.join("；"));
    return "三页 × 星号 + 窄屏，都干净";
  });

  await browser.close();
}

report();

function report() {
  const failed = results.filter((r) => !r.ok);
  console.log(`\n冒烟测试 · ${BASE}\n`);
  for (const item of results) {
    console.log(`${item.ok ? "✓" : "✗"} ${item.name}`);
    if (item.detail) console.log(`    ${item.detail}`);
  }
  console.log(failed.length ? `\n${failed.length} 项没过。别上线。` : `\n${results.length} 项全过。`);
  exit(failed.length ? 1 : 0);
}
