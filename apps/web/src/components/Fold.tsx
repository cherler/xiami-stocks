/**
 * 整块内容的折叠。跟 ShowMore 不同：那个折的是**列表的尾巴**，这个折的是**整个区域**。
 *
 * ## 为什么首页需要它
 *
 * 决策总览一页排了 12 块面板。前面几块回答的是这一页标题问的那句话
 * （今天哪些判断需要重新检查），后面三块——研究池市场图、行业关注度、
 * 关注公司——是**参考资料**：你不是每天进来都要看的，但删掉又确实会少东西，
 * 因为这三块在别的页面上没有第二份。
 *
 * 所以折起来，而不是挪走或删掉。
 *
 * ## 收起那一行必须说清里面是什么
 *
 * 跟 Boundary 一条规矩：写「展开更多」等于让人猜。写「市场图、行业分布、
 * 关注列表」他才知道要不要点。
 */

import { useState, type ReactNode } from "react";

export function Fold({ label, hint, children }: {
  label: string;
  /** 里面有什么。**别省**——省掉之后这个开关就只能靠试。 */
  hint?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return <section className="fold">
    <button className="fold-toggle" type="button" aria-expanded={open}
      onClick={() => setOpen((value) => !value)}>
      <span className="fold-caret" aria-hidden="true">{open ? "▾" : "▸"}</span>
      <b>{label}</b>
      {hint && <em>{hint}</em>}
    </button>
    {open && <div className="fold-body">{children}</div>}
  </section>;
}
