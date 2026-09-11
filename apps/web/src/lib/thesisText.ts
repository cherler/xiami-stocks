/**
 * 投资逻辑那段文字怎么拆成条目。
 *
 * 拆错的代价是页面上出现一串读不通的残句，而**内容本身是对的**——
 * 人会以为模型写坏了，实际是渲染这一步切错了地方。实测出过两种切法都错：
 *
 * 1. 按「；」无脑切，切进了括号里：
 *    「…近5年偏低分位（市盈率TTM 7.37 倍，处于近 5 年 12.7% 分位；
 *      市净率 0.96 倍…2026-08-05）」
 *    切出来一条以「（…12.7% 分位」结尾、下一条以「市净率 0.96 倍…）」开头，
 *    括号对不上。
 *
 * 2. 把小数点当成列表标记：正则写的是 `\d+[）)、.]`，而**小数点正是
 *    「数字 + 点」**；再加上 `\d+` 会回溯，小数点前的每一位数字都成了切点：
 *      「一季度 394.02%」 → 「3」「9」「4.02%」
 *      「已升至 18.9 天」 → 「1」「8.9 天」
 *    页面上就是一串孤零零的数字。
 */

/** 按分隔符切，但**括号里的不切**。 */
export function splitOutsideBrackets(text: string, separators: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let buffer = "";
  for (const ch of String(text || "")) {
    if ("（(【[「".includes(ch)) depth += 1;
    else if ("）)】]」".includes(ch)) depth = Math.max(0, depth - 1);
    if (depth === 0 && separators.includes(ch)) {
      parts.push(buffer);
      buffer = "";
      continue;
    }
    buffer += ch;
  }
  parts.push(buffer);
  return parts.map((x) => x.trim()).filter(Boolean);
}

/** 判断句之后的依据。第一段是判断本身，后面才是依据。 */
export function thesisRest(claim: string): string[] {
  return splitOutsideBrackets(claim, "；").slice(1);
}

/** 把「1）… 2）…」拆成条目。拆不开就整段返回，不硬切。
 *
 * 三条守卫缺一不可：
 * 1. 分隔符是 `.` 时后面不能紧跟数字——这一条直接杀掉小数；
 * 2. 标记前面必须是句首或空白/分隔符，不然会切在词中间；
 * 3. 编号只认 1–2 位：列表不会编到三位数，而三位数很可能是别的东西。
 */
export function splitClauses(text: string): string[] {
  const source = String(text || "").trim();
  if (!source) return [];

  const marker = /(?:^|[\s；。，,])\s*[（(]?(\d{1,2})[）)、.](?!\d)/g;
  const starts: number[] = [];
  let hit: RegExpExecArray | null;
  while ((hit = marker.exec(source)) !== null) {
    // hit.index 落在前导空白上，标记本身从括号或数字开始
    const offset = hit[0].search(/[（(\d]/);
    starts.push(hit.index + (offset < 0 ? 0 : offset));
    marker.lastIndex = hit.index + hit[0].length;
  }
  if (starts.length < 2) return [source];

  const parts: string[] = [];
  if (starts[0] > 0) parts.push(source.slice(0, starts[0]));
  starts.forEach((start, index) => {
    parts.push(source.slice(start, index + 1 < starts.length ? starts[index + 1] : undefined));
  });
  return parts.map((x) => x.trim()).filter(Boolean);
}
