/**
 * 把一个异常说成人话。**App.tsx 和 Documents.tsx 共用这一句。**
 *
 * 这里只处理"根本没拿到响应"那一种：后端返回的错误由 ApiError 自己带文案
 * （超时那句也在 apiFetch 里就换好了），走到兜底的只剩网络层失败 ——
 * 断网、切网、DNS、连接被重置。
 *
 * ## 原来那句为什么不行
 *
 *     "保存失败，请检查 API 是否正在运行。"
 *
 * 它被用在 126 个地方：同步行情、切换筛选、删除一笔、生成报告……
 * **绝大多数都不是"保存"**。2026-08-19 巡检把请求掐断，
 * 点「同步实时行情」和切收件箱筛选，弹出来的都是这句。
 *
 * 后半句更麻烦：「请检查 API 是否正在运行」是对开发者说的话。
 * 用线上站点的人做不到这件事，也不该被要求去想这件事。
 */
export function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error
      && typeof (error as { message: unknown }).message === "string"
      && (error as { message: string }).message) {
    return (error as { message: string }).message;
  }
  // 不说是哪一步失败了 —— 这句话要对全部 126 处都成立。
  return "连不上服务器，这一步没有做成。检查一下网络再重试。";
}
