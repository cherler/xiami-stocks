/**
 * 花钱的动作，点之前标价。
 *
 * **原来 11 个会调模型的动作里只有 1 个事前告诉你要花多少**，
 * 另外 17 处是事后才显示花费。对一个按 token 计费的产品，
 * 「点了才知道多少钱」的结果不是省着用，是**不敢用**——
 * 而这几个功能恰恰是这个产品最贵重的部分。
 *
 * 价目由后端 `llm.TYPICAL_TOKENS` 给，前端不自己算：
 * 同一个数写在两处迟早会漂开，而漂开之后标出来的价比不标更糟。
 */

import { useEffect, useState } from "react";

import { getCreditEstimates } from "../api";
import { confirmAction } from "./confirm";

let cache: Record<string, number | null> | null = null;
let inflight: Promise<Record<string, number | null>> | null = null;

/** 拿一次价目表，全站共用。拿不到就返回空——**宁可不标价，也不标错**。 */
export function useCreditEstimates(): Record<string, number | null> {
  const [table, setTable] = useState<Record<string, number | null>>(cache ?? {});
  useEffect(() => {
    if (cache) return;
    inflight = inflight ?? getCreditEstimates();
    let live = true;
    inflight.then((data) => { cache = data; if (live) setTable(data); }).catch(() => undefined);
    return () => { live = false; };
  }, []);
  return table;
}

/** 「约 6 分」。不认识的动作返回空串——不要瞎猜一个数。 */
export function priceTag(table: Record<string, number | null>, task: string): string {
  const credits = table[task];
  return typeof credits === "number" ? `约 ${credits} 分` : "";
}

/**
 * 花钱之前问一句，而不是把价钱贴在每个按钮上。
 *
 * ## 为什么把价签撤了
 *
 * 之前的做法是每个花钱的动作都在按钮上挂「・约 50 分」。出发点没错——
 * 点之前该知道要花多少——但**做过头了**：一个页面上四五个价签，
 * 界面看着像在收费，而其中大部分按钮你这次根本不会点。
 *
 * 使用者原话："其他地方能不能不要动不动就把价钱放上去啊"。
 *
 * 所以改成：按钮上只写动作，**真正要扣的那一下弹一句确认**。
 * 该知道的时候知道，不该打扰的时候安静。
 *
 * 取不到价（这个动作不在报价表里）就直接放行——**不要为了弹窗而弹窗**，
 * 一个说不出价钱的确认框只是多一次点击。
 */
export function useSpendGuard() {
  const table = useCreditEstimates();
  // **返回 Promise。** 原来用的是 window.confirm（同步、阻塞主线程、
  // 手机上还会带出主站域名）。现在走站内确认框，所以调用处要 await ——
  // 忘了 await 的话 `if (!Promise)` 恒为假，会直接开跑并扣钱，
  // 这一点由 lib/confirm.test.ts 扫源码挡着。
  /**
   * `live` 传一个能算出**这一次**真实价钱的函数时优先用它。
   *
   * 典型值表报的是均值。抽承诺那一条填的是 83000 token（17 分），
   * 而线上真跑一次是**冻结 7 分、实扣 3 分** —— 报 17 扣 3 差了五倍多。
   * **报高跟报低同样糟：它会把人吓得不敢点。**
   * 算得出来的就别猜；算不出来（或者算失败）再退回典型值。
   */
  return async (task: string, what: string,
                live?: () => Promise<{ credits: number; note?: string } | null>): Promise<boolean> => {
    let price = priceTag(table, task);
    let detail = "";
    if (live) {
      try {
        const got = await live();
        if (got && got.credits >= 0) {
          price = `约 ${got.credits} 分`;
          detail = got.note ? `　${got.note}` : "";
        }
      } catch { /* 报价失败就退回典型值，不能因为估不出来就拦住他 */ }
    }
    if (!price) return true;
    return confirmAction({
      title: what,
      detail: `这一次大概花 ${price}。${detail}`,
      confirmText: "继续",
    });
  };
}
