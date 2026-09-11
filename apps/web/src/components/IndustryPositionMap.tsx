import { useEffect, useState } from "react";

import type { IndustryAggregate, IndustryComparison, PeerCompany } from "../types";

type MetricKey = "pe_ttm" | "pb" | "roe_estimate" | "net_margin" | "cash_conversion";

interface MetricDefinition {
  key: MetricKey;
  label: string;
  group: string;
  unit: "x" | "%";
  left: string;
  right: string;
}

const METRICS: MetricDefinition[] = [
  { key: "pe_ttm", label: "PE", group: "估值", unit: "x", left: "更低", right: "更高" },
  { key: "pb", label: "PB", group: "估值", unit: "x", left: "更低", right: "更高" },
  { key: "roe_estimate", label: "ROE", group: "盈利", unit: "%", left: "较低", right: "较高" },
  { key: "net_margin", label: "净利率", group: "盈利", unit: "%", left: "较低", right: "较高" },
  { key: "cash_conversion", label: "现金含量", group: "现金", unit: "%", left: "较低", right: "较高" },
];

function companyMetric(company: PeerCompany, key: MetricKey): number | null {
  if (key === "pe_ttm" || key === "pb") return company.valuation[key]?.current ?? null;
  return company.financials[key] ?? null;
}

function aggregateMetric(aggregate: IndustryAggregate, key: MetricKey): number | null {
  return aggregate[key];
}

function displayValue(value: number | null, unit: "x" | "%"): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return unit === "x" ? `${value.toFixed(2)} 倍` : `${value.toFixed(1)}%`;
}

function clamp(value: number): number {
  return Math.max(3, Math.min(97, value));
}

function comparisonText(current: number, median: number, metric: MetricDefinition): string {
  if (Math.abs(current - median) < 0.005) return "接近中位";
  const direction = current < median ? "低" : "高";
  if (metric.unit === "%") return `比中位${direction} ${Math.abs(current - median).toFixed(1)} 个百分点`;
  if (Math.abs(median) < 0.005) return `比中位${direction} ${Math.abs(current - median).toFixed(2)}`;
  return `比中位${direction} ${Math.abs(current / median - 1) * 100 < 100 ? (Math.abs(current / median - 1) * 100).toFixed(0) : ">99"}%`;
}

function rulerPositions(current: number, q1: number, median: number, q3: number) {
  const rawIqr = q3 - q1;
  const fallback = Math.max(Math.abs(median) * 0.3, 1);
  const iqr = rawIqr > 0.0001 ? rawIqr : fallback;
  const minimum = q1 - iqr * 1.5;
  const maximum = q3 + iqr * 1.5;
  const span = maximum - minimum || 1;
  const position = (value: number) => clamp(((value - minimum) / span) * 100);
  return {
    current: position(current),
    q1: position(q1),
    median: position(median),
    q3: position(q3),
  };
}

export function IndustryPositionMap({ comparison }: { comparison: IndustryComparison }) {
  const [activeCompanyId, setActiveCompanyId] = useState<number | null>(comparison.companies[0]?.id ?? null);

  useEffect(() => {
    setActiveCompanyId(comparison.companies[0]?.id ?? null);
  }, [comparison.industry, comparison.companies]);

  const company = comparison.companies.find((item) => item.id === activeCompanyId) ?? comparison.companies[0] ?? null;
  if (!company) return null;

  return <section className="panel industry-ruler-panel" aria-labelledby="industry-ruler-title">
    <div className="industry-ruler-head">
      <div>
        <span className="eyebrow">同行位置</span>
        <h2 id="industry-ruler-title">{company.name}，站在行业哪里</h2>
      </div>
      {comparison.companies.length > 1 && <div className="industry-company-picker" role="tablist" aria-label="切换研究池公司">
        {comparison.companies.map((item) => <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={item.id === company.id}
          className={item.id === company.id ? "is-active" : ""}
          onClick={() => setActiveCompanyId(item.id)}
        >{item.name}</button>)}
      </div>}
    </div>

    <div className="industry-rulers">
      {METRICS.map((metric) => {
        const current = companyMetric(company, metric.key);
        const q1 = aggregateMetric(comparison.lower_quartile, metric.key);
        const median = aggregateMetric(comparison.median, metric.key);
        const q3 = aggregateMetric(comparison.upper_quartile, metric.key);
        const comparable = current !== null && q1 !== null && median !== null && q3 !== null;
        const positions = comparable ? rulerPositions(current, q1, median, q3) : null;
        return <article className={`industry-ruler${comparable ? "" : " industry-ruler--missing"}`} key={metric.key}>
          <div className="industry-ruler-label">
            <em>{metric.group}</em>
            <strong>{metric.label}</strong>
          </div>
          <div className="industry-ruler-chart">
            <div className="industry-ruler-axis" aria-label={`${metric.label}：${displayValue(current, metric.unit)}；行业中位 ${displayValue(median, metric.unit)}`}>
              {positions && <>
                <i className="industry-ruler-iqr" style={{ left: `${positions.q1}%`, width: `${Math.max(positions.q3 - positions.q1, 2)}%` }} />
                <i className="industry-ruler-median" style={{ left: `${positions.median}%` }} />
                <i className="industry-ruler-company" style={{ left: `${positions.current}%` }} />
              </>}
            </div>
            <div className="industry-ruler-ends"><span>{metric.left}</span><span>{metric.right}</span></div>
          </div>
          <div className="industry-ruler-value">
            <strong>{displayValue(current, metric.unit)}</strong>
            <span>{comparable ? comparisonText(current, median, metric) : "数据不足，暂不可比"}</span>
          </div>
        </article>;
      })}
    </div>
    <div className="industry-ruler-legend" aria-label="图例">
      <span><i className="industry-ruler-company" />公司</span>
      <span><i className="industry-ruler-median" />行业中位</span>
      <span><i className="industry-ruler-iqr" />行业中间 50%</span>
      <em>位置超出常见区间时会停在标尺边缘，具体值仍以右侧数字为准。</em>
    </div>
  </section>;
}
