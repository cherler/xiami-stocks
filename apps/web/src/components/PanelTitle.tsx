/**
 * 面板标题，把第三行说明收进标题旁边的一个记号里。
 *
 * ## 三件套压成两件
 *
 * 面板头现在是眉标 + 标题 + 说明三行文字，全站 43 处。
 * 内容还没开始，已经读了三行——**而标题本身往往已经把话说完了**：
 * 「它们会一起出事吗」下面那句「查这些持仓在行业、年报分部、上下游对手方、
 * 估值位置和认错条件上有没有字面重合」是方法，第一次有用，第十次是噪声。
 *
 * ## 但有一类说明不该收进来，该消失
 *
 * 扫完 26 处纯文本说明，最大的一类是**出处**——「价格、涨跌和估值来自最近
 * 一次 StockSDK 同步」「营收、利润……均来自定期报告」。它们之所以要写在
 * 面板头，是因为**下面的数字自己不带出处**。数字挂上 ▸底座 之后，
 * 这句话不是该折叠，是该删掉：出处搬到了它真正该在的地方（见 Source）。
 *
 * 所以这里只接三类：方法（怎么算的）、机制（什么时候会动）、边界（它不做什么）。
 *
 * ## 为什么是包住标题，而不是替换那个 <p>
 *
 * 记号要跟标题在同一行，说明要在标题下面——这两件事跨了 h2 的边界。
 * 把按钮塞进 h2 里，展开的段落就成了 h2 的子元素（非法）；
 * 放在 h2 后面，按钮就掉到下一行去了。所以由这里同时管住两者。
 *
 * ## 记号写什么
 *
 * 一个 ? 就够，但 aria/title 要说清里面是什么——「这块怎么算的」比「更多信息」
 * 有用，因为它让人能判断要不要点。跟 Boundary 一条规矩：**别让人猜。**
 */

import { useState, type ReactNode } from "react";

export function PanelTitle({ children, hint, id, label = "这块怎么算的" }: {
  children: ReactNode;
  /** 原来那第三行。**出处类的别放这里**——那种该做成 Source 挂到数字上。 */
  hint?: string;
  id?: string;
  /** 无障碍名称。**别写「更多信息」**——那等于让人猜。 */
  label?: string;
}) {
  const [manual, setManual] = useState<boolean | null>(null);
  const shown = manual ?? false;
  const setShown = (next: (value: boolean) => boolean) => setManual(next(shown));
  return <>
    <div className="panel-title-row">
      <h2 id={id}>{children}</h2>
      {hint && <button className={`hint-mark${shown ? " hint-mark--on" : ""}`} type="button"
        aria-expanded={shown} aria-label={label} title={`${label}：${hint}`}
        onClick={() => setShown((value) => !value)}>?</button>}
    </div>
    {hint && shown && <p className="hint-body">{hint}</p>}
  </>;
}
