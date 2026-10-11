import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, MessageCircle, X, ChevronDown, ExternalLink } from "lucide-react";
import { getAssistantWebStatus, getAssistantMessages, sendAssistantMessage, connectAssistantFeishu, confirmCloudFeishu, disconnectCloudFeishu, getCompany,
  type AssistantWebStatus, type AssistantChatMessage } from "../api";
import { errorMessage } from "../lib/errormessage";
import { apiUrl } from "../config";
import "./AssistantChat.css";

type Props = { companyId: number | null; onClose: () => void;
  onOpenCompany: (id: number) => void; onChanged: () => void };

// Render emphasis as React text nodes; never execute HTML from model output.
function answerText(value: string) {
  return value.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part.startsWith("`") && part.endsWith("`") ? <code key={index}>{part.slice(1, -1)}</code> : part);
}

export default function AssistantChat({ companyId, onClose, onOpenCompany, onChanged }: Props) {
  const [status, setStatus] = useState<AssistantWebStatus | null>(null);
  const [messages, setMessages] = useState<AssistantChatMessage[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [guide, setGuide] = useState(false);
  const [company, setCompany] = useState<{ id: number; name: string } | null>(null);
  const [useCompany, setUseCompany] = useState(true);
  const input = useRef<HTMLTextAreaElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const seen = useRef<Set<string> | null>(null);
  const pending = useRef<{ id: string; text: string; company_id: number | null } | null>(null);
  const changed = useRef(onChanged);
  changed.current = onChanged;
  const isGuide = status?.mode === "guide";
  const isCloud = status?.mode === "cloud";
  const busy = sending || messages.some(m => m.state === "running" || m.state === "queued");

  useEffect(() => {
    if (!isCloud) return;
    const timer = window.setInterval(() => {
      void getAssistantWebStatus().then(setStatus).catch(() => {});
    }, 5000);
    return () => window.clearInterval(timer);
  }, [isCloud]);

  const refresh = useCallback(async () => {
    const rows = await getAssistantMessages();
    const done = new Set(rows.filter(m => m.actions.length > 0).map(m => m.id));
    if (seen.current && [...done].some(id => !seen.current!.has(id))) changed.current();
    seen.current = done;
    setMessages(rows);
  }, []);

  useEffect(() => {
    let active = true;
    let timer: number;
    const load = async () => {
      try {
        await refresh();
      } catch (e) { if (active) setError(errorMessage(e)); }
      if (active) timer = window.setTimeout(load, 2500);
    };
    void getAssistantWebStatus().then(s => {
      if (!active) return;
      setStatus(s);
      if (s.mode !== "guide") void load();
    })
      .catch(e => { if (active) setError(errorMessage(e)); });
    return () => { active = false; window.clearTimeout(timer); };
  }, [refresh]);

  useEffect(() => {
    let active = true;
    setCompany(null); setUseCompany(true);
    if (companyId !== null) void getCompany(companyId).then(c => {
      if (active) setCompany({ id: companyId, name: c.name });
    }).catch(() => { /* Keep the input usable without guessing a company. */ });
    return () => { active = false; };
  }, [companyId]);

  useEffect(() => {
    if (isGuide) dialog.current?.querySelector<HTMLButtonElement>("button")?.focus();
    else if (status?.ready) input.current?.focus();
  }, [isGuide, status?.ready]);

  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [messages.length, messages.at(-1)?.state]);

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    (input.current ?? dialog.current?.querySelector<HTMLButtonElement>("button"))?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key === "Tab") {
        const nodes = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], textarea:not(:disabled), input:not(:disabled)');
        if (!nodes?.length) return;
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", handle);
    return () => {
      document.removeEventListener("keydown", handle);
      document.body.style.overflow = previousOverflow;
      before?.focus({ preventScroll: true });
    };
  }, [onClose]);

  async function send() {
    if (!text.trim() || busy || !status?.ready) return;
    const value = text.trim();
    const selected = useCompany ? company?.id ?? null : null;
    if (!pending.current || pending.current.text !== value || pending.current.company_id !== selected) {
      pending.current = { id: crypto.randomUUID().replaceAll("-", ""), text: value, company_id: selected };
    }
    setSending(true); setError("");
    try {
      await sendAssistantMessage(pending.current);
      pending.current = null;
      setText("");
      await refresh();
    } catch (e) { setError(errorMessage(e)); }
    finally { setSending(false); input.current?.focus(); }
  }

  async function checkConnection(bind = false) {
    setError("");
    try {
      const next = await (bind ? connectAssistantFeishu() : getAssistantWebStatus());
      setStatus(next);
      if (next.mode !== "guide") await refresh();
    }
    catch (e) { setError(errorMessage(e)); }
  }

  return <div className="sa-scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <aside className="sa-panel" ref={dialog} role="dialog" aria-modal="true" aria-label="看股助手">
      <header className="sa-header">
        <div className="sa-title"><MessageCircle size={20}/><h2>看股助手</h2></div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="关闭助手"><X size={20}/></button>
        <p><span className={status?.ready ? "sa-dot is-ready" : "sa-dot"}/>
          {isGuide ? "连接你自己的私人助手" : status ? status.ready ? "在线 · 和飞书里的助手共用研究资料" : status.configured ? "暂未连接" : "尚未接入" : "正在检查连接…"}</p>
      </header>
      <div className="sa-conversation" aria-label="助手对话">
        {isGuide && <div className="sa-welcome sa-onboarding">
          <h3>把看股助手接到你的飞书</h3>
          <p>查股票、记想法、盯变化、核对计划，直接说就行。助手在你的电脑运行，用你自己的模型和研究资料。</p>
          <ol>{status.guide.map(step => <li key={step.title}><strong>{step.title}</strong><p>{step.text}</p></li>)}</ol>
          <a className="page-action" href="https://github.com/cherler/xiami-stocks/blob/main/apps/assistant/README.md" target="_blank" rel="noreferrer">查看安装与飞书接入说明 <ExternalLink size={14}/></a>
          <p>已经在本地用过？继续使用原来的机器人，无需重新绑定。</p>
          <small>线上目前提供接入指引。线上与本地的研究资料不会自动同步；电脑休眠或关机后，本地助手会暂停。</small>
        </div>}
        {status && !isGuide && messages.length === 0 && <div className="sa-welcome">
          <h3>股票的事，直接说。</h3>
          <p>问研究、记想法，或告诉我需要盯什么。</p>
          <div className="sa-examples">
            {["我的票有什么需要关注的？", "帮我记一下工业富联：先看现金流", "帮我看看原来的判断有什么变化"].map(example =>
              <button type="button" className="text-button" key={example} onClick={() => { setText(example); input.current?.focus(); }}>{example}</button>)}
          </div>
          <small>聊天不会自动变成交易计划。需要保存时，直接说“帮我记下”。</small>
        </div>}
        {messages.map(message => <section className="sa-turn" key={message.id}>
          <div className="sa-user"><span>你{message.company_name ? ` · ${message.company_name}` : ""}</span><p>{message.content}</p></div>
          <div className="sa-answer"><span>看股助手</span>
            {message.state === "queued" ? <p className="sa-wait" role="status">已排队，轮到后自动处理，关掉窗口也会继续。</p>
              : message.state === "running" ? <p className="sa-wait" role="status">正在查阅和处理，关掉窗口也会继续。</p>
              : <p>{answerText(message.answer || message.error)}</p>}
            {message.actions.filter(a => a.company_id && ["remember", "correct", "undo"].includes(a.operation)).map((a, index) =>
              <button type="button" className="text-button" key={`${a.record_id}-${index}`} onClick={() => onOpenCompany(a.company_id!)}>查看公司记录</button>)}
            {message.state === "interrupted" && message.company_id && <button type="button" className="text-button" onClick={() => onOpenCompany(message.company_id!)}>核对公司记录</button>}
          </div>
        </section>)}
        <div ref={end}/>
      </div>
      {error && <p className="sa-error" role="alert">{error}</p>}
      {status && !isGuide && !status.ready && <div className="sa-offline"><p>{status.message}</p><button type="button" className="text-button" onClick={() => void checkConnection()}>重新检查</button></div>}
      {status && !isGuide && <div className="sa-composer">
        {company && <div className="sa-context"><span>{useCompany ? `当前公司：${company.name}` : "未附带当前页面的公司"}</span>
          <button type="button" className="text-button" onClick={() => setUseCompany(!useCompany)}>{useCompany ? "清除" : "带上当前公司"}</button></div>}
        <form onSubmit={e => { e.preventDefault(); void send(); }}>
          <textarea ref={input} aria-label="给看股助手发消息" value={text} maxLength={12000} rows={3}
            placeholder={company && useCompany ? `问问${company.name}，或者记下你的想法…` : "问股票、记想法，或告诉我需要盯什么…"}
            onChange={e => setText(e.target.value)} onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); }
            }}/>
          <button type="submit" className="page-action sa-send" aria-label="发送消息" disabled={busy || !status?.ready || !text.trim()}><ArrowUp size={18}/></button>
        </form>
        <small>{busy ? "上一条还在处理，可以先写下一条。" : "Enter 发送，Shift + Enter 换行"}</small>
      </div>}
      {status && !isGuide && <footer className="sa-footer">
        <button type="button" className="text-button sa-guide-toggle" aria-expanded={guide} onClick={() => setGuide(!guide)}>
          {status?.feishu_bound ? "飞书已绑定 · 接入与帮助" : "连接飞书，在手机上继续聊"}<ChevronDown size={15}/></button>
        {guide && <div className="sa-guide">
          <p>网页和飞书使用同一份研究资料；你在任一处记下的想法，都能在公司档案里找到。</p>
          <ol>{status?.guide.map(step => <li key={step.title}><strong>{step.done ? "已完成 · " : ""}{step.title}</strong><p>{step.text}</p></li>)}</ol>
          {status?.settings_url && <a className="text-button" href={status.settings_url} target="_blank" rel="noreferrer">打开连接设置 <ExternalLink size={13}/></a>}
          {!status?.configured && <a className="text-button" href="https://github.com/cherler/xiami-stocks/blob/main/apps/assistant/README.md" target="_blank" rel="noreferrer">查看本机安装说明 <ExternalLink size={13}/></a>}
          {isCloud ? <>
            {status.feishu?.error && <p role="status">{status.feishu.error}</p>}
            {status.feishu?.qr_url && <div className="sa-qr">
              <img width="200" height="200" alt="使用飞书扫码连接看股助手" src={apiUrl(`/api/v1/assistant/cloud/feishu/qr?v=${encodeURIComponent(status.feishu.expires_at || "")}`)}/>
              <p>用自己的飞书扫码，完成应用创建后回到这里。</p>
              <a href={status.feishu.qr_url} target="_blank" rel="noreferrer">在手机上打开连接页面</a>
            </div>}
            {status.feishu?.state === "awaiting_confirmation" && <div>
              <p>应用已创建。如果刚才是你本人扫码，确认后即可使用。</p>
              <button type="button" className="page-action" onClick={() => void confirmCloudFeishu().then(setStatus).catch(e => setError(errorMessage(e)))}>是我扫码的，完成连接</button>
            </div>}
            {["authorized", "connected"].includes(status.feishu?.state || "") && status.feishu?.app_id &&
              <a className="page-action" href={`https://applink.feishu.cn/client/bot/open?appId=${encodeURIComponent(status.feishu.app_id)}`} target="_blank" rel="noreferrer">去飞书聊聊 <ExternalLink size={13}/></a>}
            {[undefined, "failed", "disconnected"].includes(status.feishu?.state) &&
              <button type="button" className="page-action" onClick={() => void checkConnection(true)}>扫码连接飞书</button>}
            {["requested", "registering"].includes(status.feishu?.state || "") && !status.feishu?.qr_url && <p role="status">正在准备二维码…</p>}
            {status.feishu?.state && !["failed", "disconnected"].includes(status.feishu.state) &&
              <button type="button" className="text-button" onClick={() => void disconnectCloudFeishu().then(setStatus).catch(e => setError(errorMessage(e)))}>断开飞书连接</button>}
            <small>助手在云端运行，电脑关机也能用。聊天保留 90 天，保存到公司档案的研究会继续保留。按账户积分计费，繁忙时排队；本地助手与这里独立。</small>
          </> : <>
            <button type="button" className="text-button" onClick={() => void checkConnection(true)}>{status?.feishu_bound ? "检查飞书绑定" : "完成飞书绑定"}</button>
            <small>本机助手需要电脑保持运行。网页聊天记录仅显示在网页发送的消息。</small>
          </>}
        </div>}
      </footer>}
    </aside>
  </div>;
}
