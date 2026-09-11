/**
 * 长列表只先给一屏，其余按需展开。
 *
 * ## 为什么需要
 *
 * 实测（1440×900）：资讯证据 12435px = **13.8 屏**、203 个可聚焦元素；
 * 研究任务 8588px = 9.5 屏、**355 个可聚焦元素**——
 * 键盘用户要按 355 次 Tab 才能穿过那一页。
 * 这几页都没有分页、没有折叠、没有"只看未处理"的过滤。
 *
 * ## 为什么是「展开更多」而不是翻页
 *
 * 翻页要记住自己在第几页，而这些列表是**扫读**用的（找一条相关的），
 * 不是逐页读完的。展开保留了"一路往下扫"的手感，同时把默认高度压住。
 *
 * 剩下多少条要写出来——只写「展开更多」的话，人不知道下面还有 3 条还是 300 条。
 */

import { useState, type ReactNode } from "react";

export function ShowMore<T>({ items, step = 20, render, noun = "条" }: {
  items: T[];
  /** 首屏给几条，之后每次再展开几条。 */
  step?: number;
  render: (item: T, index: number) => ReactNode;
  /** 计量单位：「条」「家」「笔」。 */
  noun?: string;
}) {
  const [shown, setShown] = useState(step);
  const rest = items.length - shown;
  return <>
    {items.slice(0, shown).map(render)}
    {rest > 0 && (
      <div className="show-more">
        <button className="text-button" onClick={() => setShown((n) => n + step)}>
          还有 {rest} {noun}，再展开 {Math.min(step, rest)} {noun}
        </button>
        {rest > step && (
          <button className="text-button show-more-all" onClick={() => setShown(items.length)}>
            全部展开
          </button>
        )}
      </div>
    )}
  </>;
}
