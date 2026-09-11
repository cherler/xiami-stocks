/**
 * 读文档结果里那张表的两件小事：**行列对齐**、**数字右对齐**。
 *
 * 为什么要有表：研报里的「营收（百万元）2023A 709 → 2024E 1536 → 2025E 2674 →
 * 2026E 3342」写成一句话，**谁都对不齐**，也就看不出增速是在哪一年掉下来的。
 * 同样这几个数排成一张表，一眼就看出来。所以成组的数字一律走表格。
 */

export type DigestTable = { title?: string; columns?: string[]; rows?: string[][]; note?: string };
export type Grid = { columns: string[]; rows: string[][] };

/**
 * 把模型给的表补成规整的矩阵。
 *
 * 模型偶尔会给出一行比表头多一格或少一格的表。**少一格补空、多一格给表头补空标题 ——
 * 不许截掉**：被截掉的那一格正好可能是最要紧的那个数，而截掉之后这张表
 * 看起来完全正常，没有任何迹象说明它少了东西。
 */
export function tableGrid(table: DigestTable): Grid {
  const rows = (table.rows ?? []).filter((row): row is string[] => Array.isArray(row));
  const columns = table.columns ?? [];
  const width = Math.max(columns.length, ...rows.map((row) => row.length), 0);
  const pad = (cells: unknown[]) =>
    Array.from({ length: width }, (_, i) => (cells[i] == null ? "" : String(cells[i])));
  return { columns: pad(columns), rows: rows.map(pad) };
}

/**
 * 这一格是数吗 —— 决定它右对齐还是左对齐。
 *
 * 判据是**开头**：以数字（可带正负号）打头的就算数，后面跟着单位（`亿`、`%`、`X`）
 * 不影响。误判成本是不对称的：把「营业收入」当成数只是左边空一点，
 * 把 `-848` 当成文字则会让整列数字参差不齐 —— 而对齐正是这张表存在的理由。
 */
export function numeric(cell: string): boolean {
  return /^[+\-−–—]?[\d,]+(\.\d+)?/.test(cell.trim());
}
