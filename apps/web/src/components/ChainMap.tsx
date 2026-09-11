/**
 * 经营关系线索：把四种线索按空间方向排开。
 *
 * ## 原来的问题
 *
 * 叫"地图"，实际是四段带小标题的文字列表——上游一段、下游一段、对手一段、
 * 替代一段。而链条**唯一值得画的东西就是方向**：钱和货从上游流进来、从下游流出去，
 * 对手在同一层横着站，替代方案在旁边等着抢需求。这四种关系的空间位置本身就是
 * 信息，排成上下四段等于把它扔了。
 *
 * ## 布局
 *
 * 上游 → 本公司 → 下游 横着一行，方向就是链条方向。
 * 同业对手和替代方案摆在下面一排：它们不在链条上，是**站在本公司位置上的竞争者**，
 * 画进主链会让人误以为货也从它们那里流过。
 *
 * ## 节点上写什么
 *
 * 只写短名。counterpart 那一栏在库里全是整段描述
 * （「个人客户（寿险、产险、健康险投保人）」），后端在读取时派生了 label——
 * **节点上塞一段话，图就退化成了文字**，而那正是这一页原来的毛病。
 * 完整原文与该去哪核对在点开之后的卡片里，一个字不丢。
 * **但删除按钮留在节点上。** 上一版把它也挪进了卡片，结果这个操作
 * 从页面上消失了——用户报的「无法删除」不是功能没有，是找不到。
 *
 * ## 颜色
 *
 * 三层用的是**位置**而不是类别：上游/本公司/下游是一条轴上的三个位置。
 * 所以用同一色相的三级明度（#1e5f9e → #2a78d6 → #6ba3e0，明度严格单调），
 * 而不是三个色相。竞争者那一排刻意退成中性灰边框——它们不在链上。
 *
 * 「已证实」不靠颜色区分：整页默认全是待证实，用颜色标出少数已证实的，
 * 等于让人用颜色去数数。改成实心小勾 + 文字。
 */

import { useState } from "react";

import type { SupplyChainLink } from "../types";

type Extended = SupplyChainLink & { label?: string };

const LANES = [
  { relation: "上游供应", title: "上游", hint: "它从这里买", tone: "up" },
  { relation: "下游客户", title: "下游", hint: "它卖给这里", tone: "down" },
] as const;

const RIVALS = [
  { relation: "同业对手", title: "同业对手", hint: "抢同一批客户" },
  { relation: "替代方案", title: "替代方案", hint: "客户不买它、可以买什么" },
] as const;

/** 一个节点。
 *
 * **删除按钮直接放在节点上，不藏在点击之后。** 上一版把确认与删除挪进了
 * "点了才出现的详情卡"，结果是这两个操作从页面上消失了——用户报的
 * 「无法删除」不是功能没有，是找不到。做成图之后更该注意这件事：
 * 列表天然把每行的操作摆在那里，图没有这个便利，得自己补回来。
 */
function Node({ link, open, onToggle, onDelete }: {
  link: Extended; open: boolean; onToggle: () => void; onDelete: () => void;
}) {
  return (
    <div className={`chain-node${open ? " chain-node--open" : ""}`}>
      <button type="button" className="chain-node-main" onClick={onToggle}>
        <span className="chain-node-name">{link.label || link.counterpart}</span>
        {link.confidence === "已证实" && <span className="chain-node-ok" title="已核对">✓</span>}
      </button>
      <button type="button" className="chain-node-drop" title="删掉这条关系"
              aria-label={`删掉「${link.label || link.counterpart}」这条关系`}
              onClick={onDelete}>×</button>
    </div>
  );
}

/** 手动加一条。模型给的往往不全——实测工商银行的上游只给出「中央银行」一条，
 *  而你自己知道的没地方录，这一页就只能被动接受模型给什么看什么。 */
function AddLink({ relation, onAdd }: {
  relation: string; onAdd: (payload: Record<string, string>) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [detail, setDetail] = useState("");
  const [source, setSource] = useState("");

  if (!open) {
    return <button type="button" className="chain-add" onClick={() => setOpen(true)}>+ 加一条</button>;
  }
  return (
    <form className="chain-add-form" onSubmit={async (event) => {
      event.preventDefault();
      if (!name.trim()) return;
      await onAdd({ relation, counterpart: name.trim(), detail: detail.trim(), source: source.trim() });
      setName(""); setDetail(""); setSource(""); setOpen(false);
    }}>
      <input value={name} onChange={(e) => setName(e.target.value)} autoFocus
             placeholder="对方名称，12 字以内" maxLength={40} />
      <input value={detail} onChange={(e) => setDetail(e.target.value)}
             placeholder="关系是什么（可留空）" maxLength={200} />
      <input value={source} onChange={(e) => setSource(e.target.value)}
             placeholder="来源：年报、公告或官网（有来源才算已证实）" maxLength={200} />
      <div className="chain-add-actions">
        <button type="submit" className="text-button">加上</button>
        <button type="button" className="text-button" onClick={() => setOpen(false)}>取消</button>
      </div>
    </form>
  );
}

export function ChainMap({ links, companyName, busy, onConfirm, onDelete, onAdd }: {
  links: Extended[];
  companyName: string;
  busy: string;
  onConfirm: (id: number) => void;
  onDelete: (id: number) => void;
  onAdd: (payload: Record<string, string>) => Promise<void>;
}) {
  const [openId, setOpenId] = useState<number | null>(null);
  const pick = (relation: string) => links.filter((link) => link.relation === relation);
  const opened = links.find((link) => link.id === openId) ?? null;

  return <>
    <div className="chain-map">
      {LANES.slice(0, 1).map((lane) => (
        <div className="chain-lane" key={lane.relation}>
          <h4>{lane.title}<em>{lane.hint}</em></h4>
          {pick(lane.relation).map((link) => (
            <Node key={link.id} link={link} open={link.id === openId}
                  onToggle={() => setOpenId(link.id === openId ? null : link.id)}
                  onDelete={() => onDelete(link.id)} />
          ))}
          {pick(lane.relation).length === 0 && <p className="chain-lane-empty">还没有</p>}
          <AddLink relation={lane.relation} onAdd={onAdd} />
        </div>
      ))}

      {/* 箭头就是这张图的全部意义：方向。用 aria-hidden，读屏器靠上下游标题理解结构 */}
      <div className="chain-arrow" aria-hidden="true"><i /><span>货与服务</span></div>

      <div className="chain-self">
        <span className="chain-self-label">本公司</span>
        <strong>{companyName}</strong>
      </div>

      <div className="chain-arrow" aria-hidden="true"><i /><span>货与服务</span></div>

      {LANES.slice(1).map((lane) => (
        <div className="chain-lane" key={lane.relation}>
          <h4>{lane.title}<em>{lane.hint}</em></h4>
          {pick(lane.relation).map((link) => (
            <Node key={link.id} link={link} open={link.id === openId}
                  onToggle={() => setOpenId(link.id === openId ? null : link.id)}
                  onDelete={() => onDelete(link.id)} />
          ))}
          {pick(lane.relation).length === 0 && <p className="chain-lane-empty">还没有</p>}
          <AddLink relation={lane.relation} onAdd={onAdd} />
        </div>
      ))}
    </div>

    {/* 竞争者不在链条上，所以不画进上面那一行 —— 画进去会让人以为货也从它们那流过 */}
    <div className="chain-rivals">
      {RIVALS.map((group) => (
        <div className="chain-rival-group" key={group.relation}>
          <h4>{group.title}<em>{group.hint}</em></h4>
          <div className="chain-rival-row">
            {pick(group.relation).map((link) => (
              <Node key={link.id} link={link} open={link.id === openId}
                    onToggle={() => setOpenId(link.id === openId ? null : link.id)}
                    onDelete={() => onDelete(link.id)} />
            ))}
            {pick(group.relation).length === 0 && <p className="chain-lane-empty">还没有</p>}
            <AddLink relation={group.relation} onAdd={onAdd} />
          </div>
        </div>
      ))}
    </div>

    {/* 详情在图外单独一块：开在节点旁边会把整行推开，图的形状就变了 */}
    {opened && <div className="chain-detail">
      <div className="chain-detail-head">
        <strong>{opened.counterpart}</strong>
        <span className={`grade-chip grade-chip--${opened.confidence === "已证实" ? "高" : "中"}`}>
          {opened.confidence}
        </span>
        {opened.segment && <em>{opened.segment}</em>}
      </div>
      <p>{opened.detail}</p>
      <p className="chain-source">{opened.source}</p>
      <div className="chain-actions">
        {opened.confidence !== "已证实" &&
          <button className="text-button" disabled={busy !== ""} onClick={() => onConfirm(opened.id)}>
            我核对过了，标为已证实
          </button>}
        <button className="text-button text-button--danger" disabled={busy !== ""}
                onClick={() => onDelete(opened.id)}>删掉</button>
        <button className="text-button" onClick={() => setOpenId(null)}>收起</button>
      </div>
    </div>}
  </>;
}
