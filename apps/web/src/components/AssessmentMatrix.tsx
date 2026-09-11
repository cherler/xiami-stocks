/**
 * 研究池 × 方法体检：一眼横向比较。
 *
 * **列表做不到横向。** 体检结论存在每家公司自己的档案里，想知道「哪几家在价格类
 * 方法上都不利」，得点进八个档案挨个看。做成 公司×方法 的网格之后，
 * 一列看下来就是「所有公司在这个方法下什么样」，一行看过去就是「这家公司哪类方法说好」。
 *
 * ## 颜色：发散，不是分类
 *
 * 有利↔不利是**极性**，两端对立、中间是「说不上好坏」。所以用发散对
 * （青绿 ↔ 朱红，中间中性灰），不是分类色——分类色会让人以为四个档位是四种
 * 并列的东西，而它们其实在一根轴上。
 *
 * 配色跟着 A 股惯例走：**红是坏、绿是好**在这里反过来——本产品的 `.quote-up`
 * 用朱红、`.quote-down` 用青绿。同一屏里红不能一会儿是好一会儿是坏，
 * 所以这里也是「朱红=不利」。
 *
 * 跑过 validate_palette（#1baf7a / #d03b3b）：正常视力 ΔE 31.9、
 * 色觉障碍最差 9.9（红绿一起用最容易踩的就是这个数——status 色板里的
 * good/critical 组合实测只有 4.1，典型红绿色盲陷阱）。
 * 青绿对比度 2.74 触发 WARN，规范要求「必须有可见标签」——格子里本来就写着字。
 *
 * ## 「数据不足」不在这根轴上
 *
 * 它不是「中间」，是「没测出来」。用极浅的灰加斜纹，明确退到背景里，
 * 免得被当成「中性」读。
 */

import type { AssessmentItem } from "../api";

const TONE: Record<string, { bg: string; ink: string; short: string }> = {
  有利: { bg: "#d8f2e7", ink: "#0a6b49", short: "利" },
  中性: { bg: "#f0efec", ink: "#5b6472", short: "中" },
  不利: { bg: "#fadcdc", ink: "#9b2929", short: "弊" },
  数据不足: { bg: "#f7f7f6", ink: "#a8aeb6", short: "—" },
  未体检: { bg: "#fbfbfa", ink: "#c2c7cd", short: "" },
};

const CATEGORY_LABEL: Record<string, string> = {
  find: "找什么", business: "生意好不好", price: "价格贵不贵",
};

export type MatrixRow = {
  company_id: number;
  company_name: string;
  symbol: string;
  results: Pick<AssessmentItem, "method_key" | "method_name" | "category" | "verdict" | "summary">[];
};

export function AssessmentMatrix({ rows, onOpenCompany }: {
  rows: MatrixRow[];
  onOpenCompany: (id: number) => void;
}) {
  if (rows.length === 0) {
    return <div className="empty-state">还没有公司做过方法体检。去公司档案的「方法体检」页跑一次。</div>;
  }
  // 方法顺序取第一行的——后端按方法库的固定顺序返回，所有行一致。
  const methods = rows[0].results;

  return <>
    <div className="matrix-wrap">
      <table className="matrix">
        <thead>
          <tr>
            <th scope="col" className="matrix-corner">公司</th>
            {methods.map((m) => (
              <th scope="col" key={m.method_key} title={m.method_name}>
                <span className="matrix-cat">{CATEGORY_LABEL[m.category] ?? ""}</span>
                <span className="matrix-method">{m.method_name}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.company_id}>
              <th scope="row">
                <button className="text-button" onClick={() => onOpenCompany(row.company_id)}>
                  {row.company_name}
                </button>
                <em>{row.symbol}</em>
              </th>
              {row.results.map((cell) => {
                const tone = TONE[cell.verdict] ?? TONE["未体检"];
                return (
                  <td key={cell.method_key}
                      style={{ background: tone.bg, color: tone.ink }}
                      title={`${row.company_name} · ${cell.method_name}：${cell.verdict}${cell.summary ? `\n${cell.summary}` : ""}`}>
                    {/* 格子里写字，不只靠颜色 —— 色觉障碍、打印、强制配色模式下颜色都会失效 */}
                    {tone.short}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>

    <div className="timeline-legend">
      {["有利", "中性", "不利", "数据不足"].map((v) => (
        <span key={v}>
          <i style={{ background: TONE[v].bg, border: `1px solid ${TONE[v].ink}33` }} />
          {TONE[v].short && <b style={{ color: TONE[v].ink }}>{TONE[v].short}</b>} {v}
        </span>
      ))}
    </div>
  </>;
}
