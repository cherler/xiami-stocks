import type { ReactNode } from "react";

export type ResearchSummaryTone = "neutral" | "accent" | "good" | "warn" | "risk";

export interface ResearchSummaryItem {
  label: string;
  value: ReactNode;
  tone?: ResearchSummaryTone;
}

export function ResearchSummary({
  eyebrow,
  title,
  items,
  action,
  className = "",
}: {
  eyebrow: string;
  title: ReactNode;
  items: ResearchSummaryItem[];
  action?: ReactNode;
  className?: string;
}) {
  return <section className={`research-summary${className ? ` ${className}` : ""}`} aria-label={eyebrow}>
    <div className="research-summary-lead">
      <span>{eyebrow}</span>
      <strong>{title}</strong>
    </div>
    <div className="research-summary-metrics">
      {items.map((item) => <span className={`research-summary-metric research-summary-metric--${item.tone ?? "neutral"}`} key={item.label}>
        <em>{item.label}</em>
        <b>{item.value}</b>
      </span>)}
    </div>
    {action && <div className="research-summary-action">{action}</div>}
  </section>;
}
