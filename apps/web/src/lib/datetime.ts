/**
 * 日期时间的显示。**只有日期的东西不许印出时分。**
 *
 * 公告和大事只有 `event_date`（一个日子），后端为了凑成时间戳补了 `T00:00:00`
 * （repository.py:3376），前端再无条件把时分打出来 —— 于是证据档案里
 * 每一条都写着 `8月18日 00:00`。
 *
 * 那个 `00:00` 是**假精度**：它看起来像"这件事发生在零点"，
 * 而真相是"我们只知道是哪一天"。跟本仓反复守的那条是同一件事 ——
 * **看起来能用的数字比没有数字糟**，因为读的人不会去怀疑它。
 * 顺带它还把一列本来能区分先后的信息变成了噪音：四条都是 00:00，等于没排序。
 *
 * ## 边界在哪
 *
 * 真的发生在零点整分的事会被一起当成"只有日期"。这个取舍是有意的：
 * 把一个真零点显示成日期，代价是丢掉"零点"这一个信息；
 * 把一堆补出来的零点显示成时刻，代价是给每一条都编一个发生时间。后者贵得多。
 * 判据是**整点整分**，所以 `00:05` 这种照常显示。
 */
const MIDNIGHT = /T00:00(:00(\.0+)?)?(Z|[+-]\d{2}:?\d{2})?$/;

export function looksDateOnly(value: string): boolean {
  return MIDNIGHT.test(value) || !value.includes("T");
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    ...(looksDateOnly(value) ? {} : { hour: "2-digit", minute: "2-digit", hour12: false }),
  }).format(new Date(value));
}
