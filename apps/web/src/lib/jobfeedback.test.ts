/**
 * 后台任务守门：**轮询任务状态的地方，必须显示失败。**
 *
 * 这条规则是被实测逼出来的。承诺台账那一页轮询 promise_extract 任务，
 * 但没有失败分支——于是任务连着 500 了五次，而页面上什么都不显示：
 * 使用者看到的是一片空白，跟"这家公司没有承诺"长得一模一样。
 * 他连点了几次，得到的唯一信息是"这功能没用"。
 *
 * 这类 bug 肉眼看不出来，因为**失败路径在正常开发时几乎不会被触发**。
 * 所以在这里守住模式本身：凡是调 getJob 轮询的组件，
 * 源码里必须出现「失败」这个状态判断。
 *
 * 不启动浏览器、不渲染组件——这是一条源码级的规则，
 * 而源码级的规则用扫源码来守最省事，也最不会因为渲染细节变化而失效。
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const SRC = join(import.meta.dirname, "..");

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return walk(full);
    return entry.name.endsWith(".tsx") ? [full] : [];
  });
}

test("每个轮询后台任务的组件都要显示失败", () => {
  const offenders: string[] = [];
  for (const file of walk(SRC)) {
    const source = readFileSync(file, "utf8");
    if (!source.includes("getJob(")) continue;
    // 「失败」是后端写进 background_jobs.status 的字面值；
    // 「已中断」是服务重启留下的那种，也要认。
    if (!source.includes("\"失败\"") && !source.includes("'失败'")) {
      offenders.push(file.replace(SRC, "src"));
    }
  }
  assert.deepEqual(
    offenders, [],
    `这些组件轮询了后台任务却不显示失败——任务 500 之后页面会是一片空白，\n` +
    `而空白跟"这次真的没有结果"长得一模一样：\n  ${offenders.join("\n  ")}`);
});

/**
 * 第二条：**轮询任务状态的地方，进来必须先问一次。**
 *
 * 反方 Agent 和承诺抽取都写成了「running 为真才轮询」，而挂载时 job 是 null、
 * running 就是 false——于是跑完的结果在 background_jobs 里躺着，前端从来不去问。
 * 切出去再回来看到的是空的，只能再花一次积分重跑
 * （使用者原话："等我回来还是没有结果，还要重新处理"）。
 *
 * 这几个都是花钱的动作，白跑一次是真损失。而这个 bug 的形状是**少了一段代码**，
 * 页面上跟"这次没查出东西"长得一模一样，靠看是看不出来的。
 *
 * 判据：文件里出现 `if (!running) return`（或等价的只在跑动时轮询），
 * 就必须另有一个不依赖 running 的 getJob 调用。
 */
test("轮询后台任务的组件，进来要先问一次", () => {
  const offenders: string[] = [];
  for (const file of walk(SRC)) {
    const source = readFileSync(file, "utf8");
    if (!source.includes("getJob(")) continue;
    if (!/if \(!running\) return/.test(source)) continue;

    // 把「只在跑动时轮询」那一段挖掉，剩下的地方还得有 getJob——
    // 那就是挂载时问的那一次。
    const rest = source.replace(/useEffect\(\(\) => \{\s*if \(!running\) return;[\s\S]*?\n  \}, \[[^\]]*\]\);/g, "");
    if (!rest.includes("getJob(")) {
      offenders.push(file.replace(SRC, "src"));
    }
  }
  assert.deepEqual(offenders, [],
    "这些组件只在任务跑动时轮询，挂载时不问——\n" +
    "跑完的结果在库里躺着，切出去再回来看到的是空的，只能再花一次积分重跑：\n" +
    offenders.join("\n"));
});
