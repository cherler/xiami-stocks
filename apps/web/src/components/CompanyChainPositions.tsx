import { ArrowRight, Network } from "lucide-react";
import { useEffect, useState } from "react";

import { getCompanyIndustryChainPositions } from "../api";
import { ROUTE_BASE } from "../config";
import type { CompanyIndustryChainPositions } from "../types";

export function CompanyChainPositions({ companyId }: { companyId: number }) {
  const [data, setData] = useState<CompanyIndustryChainPositions | null>(null);

  useEffect(() => {
    let live = true;
    getCompanyIndustryChainPositions(companyId).then((next) => { if (live) setData(next); }).catch(() => undefined);
    return () => { live = false; };
  }, [companyId]);

  if (!data) return null;
  const href = `${ROUTE_BASE}/industry-chains?company=${companyId}${data.themes[0] ? `&theme=${data.themes[0].theme_id}` : ""}`;
  return <section className="company-chain-position panel">
    <div className="company-chain-position-head">
      <div><span className="eyebrow">产业链底图</span><h2>这家公司在链上的位置</h2></div>
      <a className="text-button" href={href}>打开完整底图 <ArrowRight size={13} /></a>
    </div>
    {data.themes.length === 0
      ? <div className="company-chain-position-empty"><Network size={24} /><span>还没有把这家公司定位到产品或服务节点。</span><a href={href}>去产业链底图定位</a></div>
      : <div className="company-chain-theme-list">{data.themes.map((theme) => <article key={theme.theme_id}>
          <header><strong>{theme.theme_name}</strong><span>{theme.chain_type}</span></header>
          <div>{theme.positions.map((position) => <span className={position.verification === "已核验" ? "is-verified" : "is-draft"} key={position.id}>
            <em>{position.stage_name}</em><ArrowRight size={11} /><strong>{position.node_name}</strong><small>{position.role}</small>
          </span>)}</div>
        </article>)}</div>}
  </section>;
}
