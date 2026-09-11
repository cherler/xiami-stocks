/**
 * 站内确认框。**替掉 window.confirm。**
 *
 * ## 为什么原生的不够用
 *
 * 这个产品里需要确认的动作有两类，原生弹框对两类都不合适：
 *
 * - **删除类**：删一条投资逻辑、删一笔交易、拿备份覆盖整个库。
 *   这些的关键不是"再问一次"，是**把后果说清楚**——「删掉之后，
 *   这之后所有的成本价与持仓都会跟着重算」。原生框把这段话挤成一行系统字，
 *   还在最上面写着 `127.0.0.1:8090 显示`，读起来像浏览器的事，不像你的数据的事。
 * - **花钱类**：点下去要扣积分。它需要的是一句"这一次大概花多少"。
 *
 * 原生框还有两个实打实的毛病：它**阻塞主线程**（弹着的时候页面什么都做不了，
 * 后台任务的轮询也停了），以及在手机上会带出网址——而这个模块挂在
 * 主站的子路径下，弹出来的域名是主站的，看着像是主站要删你的东西。
 *
 * ## 兜底为什么还是 window.confirm
 *
 * `confirmAction()` 是模块级函数，靠 `<ConfirmHost />` 挂上去才有 UI。
 * 万一 Host 没挂（渲染顺序变了、某个页面单独挂载），**不能默认返回 true**
 * （那等于跳过确认直接删），也不能默认返回 false（那等于按钮点了没反应）。
 * 退回原生框是唯一诚实的选择：难看，但语义没变。
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type ConfirmAsk = {
  /** 一句话说清要做什么。别写「确定吗」——那句话不含任何信息。 */
  title: string;
  /** 后果、代价、能不能撤回。删除类必须写。 */
  detail?: string;
  /** 确认按钮上的字。默认「确认」；删除类建议写成动作本身，如「删掉这一笔」。 */
  confirmText?: string;
  /** 不可撤销的动作。按钮变红，并且默认焦点落在「取消」上。 */
  danger?: boolean;
};

type Pending = ConfirmAsk & { resolve: (ok: boolean) => void };

let open: ((ask: Pending) => void) | null = null;

/**
 * 问一句，等他点。**返回 Promise，所以调用处必须 await。**
 *
 * 原来这些地方是 `if (!window.confirm(...)) return;` —— 同步的。
 * 改成异步之后，忘了 await 的话 `if (!Promise)` 恒为假，动作会直接执行；
 * 所以每一处调用点都改成了 `if (!(await confirmAction(...))) return;`，
 * 并且 lib/confirm.test.ts 会扫源码挡住漏掉 await 的写法。
 */
export function confirmAction(ask: ConfirmAsk): Promise<boolean> {
  if (!open) {
    const text = [ask.title, ask.detail].filter(Boolean).join("\n\n");
    return Promise.resolve(window.confirm(text));
  }
  return new Promise<boolean>((resolve) => open?.({ ...ask, resolve }));
}

/** 挂一次就够（放在应用根上）。没有它，confirmAction 会退回原生框。 */
export function ConfirmHost() {
  const [pending, setPending] = useState<Pending | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    open = (ask) => {
      // 记住是谁触发的，关掉之后把焦点还回去——键盘用户不该被扔回页面顶部。
      returnTo.current = document.activeElement as HTMLElement | null;
      setPending(ask);
    };
    return () => { open = null; };
  }, []);

  const close = useCallback((ok: boolean) => {
    setPending((current) => { current?.resolve(ok); return null; });
    returnTo.current?.focus?.();
  }, []);

  useEffect(() => {
    if (!pending) return;
    // **危险动作的初始焦点给「取消」**：连按两下回车不该把东西删了。
    (pending.danger ? cancelRef : confirmRef).current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); close(false); }
      if (event.key === "Enter" && !pending.danger) { event.preventDefault(); close(true); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [pending, close]);

  if (!pending) return null;
  return <div className="confirm-scrim" onMouseDown={(event) => {
    if (event.target === event.currentTarget) close(false);   // 点遮罩=取消，点框里不算
  }}>
    <div className={`confirm-box${pending.danger ? " confirm-box--danger" : ""}`}
         role="alertdialog" aria-modal="true" aria-label={pending.title}>
      <p className="confirm-title">{pending.title}</p>
      {pending.detail && <p className="confirm-detail">{pending.detail}</p>}
      <div className="confirm-actions">
        <button ref={cancelRef} className="text-button" type="button" onClick={() => close(false)}>取消</button>
        <button ref={confirmRef} type="button"
                className={pending.danger ? "page-action page-action--danger" : "page-action"}
                onClick={() => close(true)}>{pending.confirmText || "确认"}</button>
      </div>
    </div>
  </div>;
}
