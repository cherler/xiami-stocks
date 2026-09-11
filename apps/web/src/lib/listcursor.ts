/**
 * 上下键在一个列表里走一格。
 *
 * 抽出来只为一件事：**这段算错了在代码上完全看不出来。**
 * 第一版写的是 `(value + step + count + 1) % count`——多出来那个 +1 让
 * 第一次按下箭头跳到第 2 条、第二次跳到第 4 条，每次都多走一格。
 * 页面不报错，下拉也照常高亮，只是"高亮的不是我按到的那条"。
 * 靠截图才发现（第二次按下时高亮停在第 4 行）。
 *
 * 起手是 -1，表示还没选中任何一条：
 *   往下一格 → 第 0 条（不是第 1 条）
 *   往上一格 → 最后一条
 */
export function nextCursor(value: number, step: number, count: number): number {
  if (count <= 0) return -1;
  // -1 不是"第 -1 条"，是"还站在列表外面"——**往下和往上要从不同的地方起步**，
  // 否则往上一格会落在倒数第二条（实测 7 条列表里落在第 6 条）。
  const from = value < 0 ? (step > 0 ? -1 : 0) : value;
  return (from + step + count) % count;
}
