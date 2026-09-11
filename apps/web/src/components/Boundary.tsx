/**
 * 边界说明：默认一行，点开才展开。
 *
 * ## 为什么要收起来
 *
 * 全站 30 处面板底部挂着这种说明块，加上 54 处面板头的三件套，
 * **84 处文字包着内容**。单句不长（中位 32 字），但你从来不是在读一句，
 * 是在读第 84 段。
 *
 * 而它们只在第一次有用。第一百次进这一页时，「这张台账不会自动判未兑现」
 * 已经变成背景噪音——它占的是那一屏最该给内容的位置。
 *
 * ## 但一个字都不删
 *
 * 这些话是**防误读**的：「没查出重合 ≠ 你是分散的」「不会自动判未兑现」
 * 「引不出数据的当场丢掉」。删掉是隐瞒，不是简洁。
 *
 * 所以收起来而不是删掉，而且**收起来那一行要说清里面是什么**——
 * 写「详情」等于让人猜，写「这些数从哪来、它不会做什么」他才知道要不要点。
 *
 * ## 有一种情况默认展开：空态
 *
 * 面板没有内容时，这段说明就是这一屏唯一的内容——那时候它该完整摊开，
 * 因为**空态是这个产品唯一该解释自己的地方**。调用方传 open 控制。
 */

import { useState } from "react";

function rich(text: string) {
  return text.split("\n\n").map((paragraph, block) =>
    <p key={block}>{paragraph.split(/\*\*/).map((part, index) =>
      index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>)}</p>);
}

export function Boundary({ text, label = "这些数从哪来、它不会做什么" }: {
  text: string;
  /** 收起时那一行写什么。**别写「详情」**——那等于让人猜里面有什么。 */
  label?: string;
}) {
  const [manual, setManual] = useState<boolean | null>(null);
  const shown = manual ?? false;
  const setShown = (next: (value: boolean) => boolean) => setManual(next(shown));
  if (!text) return null;
  return <div className={`boundary${shown ? " boundary--open" : ""}`}>
    <button className="boundary-toggle" type="button" aria-expanded={shown}
      onClick={() => setShown((value) => !value)}>
      <span aria-hidden="true">{shown ? "▾" : "▸"}</span> {label}
    </button>
    {shown && <div className="boundary-body">{rich(text)}</div>}
  </div>;
}
