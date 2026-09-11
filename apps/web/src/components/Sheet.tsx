/**
 * 校样语法：一块内容该按什么顺序摊开。
 *
 * ## 这是设计样张定下的那套结构
 *
 *     结论      宋体大字，一句话，能不能只看这一句就懂
 *     数据      带出处的条，数字旁边就是 ▸年报
 *     原文      宋体引文 + 出处落款，可点回原文
 *     批注      朱边注，"这条对你不利"
 *     方法      发丝线下的小字，怎么算的、它不做什么
 *     动作      按钮
 *
 * **顺序本身是设计。** 现在站里到处是反过来的：解释三行在最上面、
 * 结论埋在中间、原文折在 <details> 里。首页那块"让它驳一驳你的判断"
 * 就是典型——两行边界说明压着一段 12 行的原始文本，
 * 而那段文本里真正是结论的只有第一句。
 *
 * ## 为什么做成组件而不是几个 class
 *
 * 只给 class，用的人还是可以按任意顺序摆。做成组件，顺序写死在这里，
 * **调用方只能提供内容，不能重排**。这套语法的价值全在顺序上。
 */

import type { ReactNode } from "react";

/** 结论。一句话，宋体，大字。**写不出一句话就说明这块还没想清楚。** */
export function Lead({ children }: { children: ReactNode }) {
  return <p className="lead">{children}</p>;
}

/** 原文引文。宋体排，落款带出处。 */
export function Quote({ children, by }: { children: ReactNode; by?: ReactNode }) {
  return <blockquote className="sheet-quote">
    {children}
    {by && <span className="sheet-by">{by}</span>}
  </blockquote>;
}

/** 朱批边注：这条对你不利。**只在真的踩到你写下的条件时用**——
 *  逢事就批，批注就不再是信号了。 */
export function ZhuNote({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return <div className="zhu-note">
    <b>{title}</b>
    {children && <span>{children}</span>}
  </div>;
}

/** 方法层：怎么算的、它不做什么。发丝线以下，最小号。 */
export function Method({ children }: { children: ReactNode }) {
  return <p className="sheet-method">{children}</p>;
}
