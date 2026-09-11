/**
 * 「这次访问是不是站主」——**整实例操作的可见性都挂在它上面。**
 *
 * ## 为什么需要它
 *
 * 备份、还原、下载整库、导出，后端一律 `access.require_owner`：
 * 还原会用一份快照覆盖所有人的记录，下载拿到的是所有人的原始行，
 * 这类动作没有「只做我那份」的版本，所以只能按人挡（见 access.py）。
 *
 * 挡是挡住了，但前端此前**完全没有这个信号**：
 * 「备份与恢复」在设置分区里对每个用户都亮着，偏好设置页还有第二个入口。
 * 后果不是泄漏，是**每个用户都看得见一个自己永远点不动的菜单**，
 * 而且等于向所有人公告「这里有整站还原」。
 *
 * ## 为什么做成共享的
 *
 * 三个地方要用同一个答案（分区页签 / 偏好设置里的入口 / 备份页自身）。
 * 各自 fetch 一次的话，一次进站就问三遍身份，而且三处可能短暂不一致。
 * 所以把 promise 存起来共享 —— 身份在一次会话里不会变。
 */
import { useEffect, useState } from "react";
import { getAccess } from "../api";

let pending: Promise<boolean> | null = null;

/** 问一次，之后所有调用方共用同一个答案。 */
function askOnce(): Promise<boolean> {
  // **拿不到就当不是站主。** 判据用于「要不要显示整库操作」，
  // 出错时宁可少显示一个入口，不要在没确认身份的情况下把它亮出来。
  //
  // **但"没认出你是谁"那一次不许记住。** 2026-08-15 线上实测：主站
  // `/v1/me` 在首屏那一瞬返回 401，九秒后同一个人就是 200。而这里把
  // 答案存成了模块级变量、一存一整场 —— 于是那一秒的抖动会让站主整个会话
  // 都看不见「备份与恢复」，而他刷新之前不会知道为什么。
  //
  // 认出来是谁了（不管是不是站主）就照旧共用一个答案：身份在一次会话里不会变。
  // 只有"根本没认出来"才作废重问，代价是下一个调用方多一次请求。
  pending ??= getAccess()
    .then((view) => {
      if (view.is_guest) pending = null;
      return Boolean(view.is_owner);
    })
    .catch(() => { pending = null; return false; });
  return pending;
}

export function useIsOwner(): boolean | null {
  // **null = 还不知道**，与 false 分开：加载中的时候不要先显示再收回去，
  // 那一闪对使用者来说就是「刚才那个菜单去哪了」。
  const [owner, setOwner] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    askOnce().then((value) => { if (live) setOwner(value); });
    return () => { live = false; };
  }, []);
  return owner;
}
