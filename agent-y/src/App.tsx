import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Plus, Settings as SettingsIcon, Code2, Briefcase, ArrowUp, Check, X,
  AlertTriangle, Activity, MessageSquare, KeyRound,
} from 'lucide-react';
import {
  createSession, listSessions, getSessionMessages, streamMessage, postApproval,
  listProviders, getSettings, type Frame, type SessionSummary, type Connection,
} from './api';
import SettingsPanel from './Settings';

type Msg = { id: string; role: 'user' | 'assistant'; content: string };
type Step = { id: string; label: string; target?: string; status: 'running' | 'done' | 'error' };
type Approval = Extract<Frame, { type: 'approval_request' }>;

const uid = () => Math.random().toString(36).slice(2);
const target = (input: Record<string, any>) =>
  String(input?.path ?? input?.command ?? input?.cmd ?? Object.values(input || {})[0] ?? '');

function toChat(stored: { role: string; content: any[] }[]): Msg[] {
  const out: Msg[] = [];
  for (const m of stored) {
    const text = (m.content || []).filter((b) => b.type === 'text' && b.text).map((b) => b.text).join('\n');
    if (text) out.push({ id: uid(), role: m.role === 'user' ? 'user' : 'assistant', content: text });
  }
  return out;
}

function greet(): string {
  const h = new Date().getHours();
  return h < 5 ? '夜深了。' : h < 11 ? '早上好。' : h < 14 ? '中午好。' : h < 18 ? '下午好。' : '晚上好。';
}

// Agent「在场感」光球：空闲缓呼吸，运行时脉冲（Marvis 式拟人化）
function AgentOrb({ running, size = 64 }: { running: boolean; size?: number }) {
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      {running && <span className="absolute inset-0 rounded-full" style={{ background: 'var(--color-gold)', animation: 'ring 1.5s ease-out infinite' }} />}
      <div className="orb absolute inset-0" style={{ animation: `breathe ${running ? 1.3 : 4.5}s ease-in-out infinite` }} />
    </div>
  );
}

export default function App() {
  const [scene, setScene] = useState<'coding' | 'assistant'>('assistant');
  const [threads, setThreads] = useState<SessionSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [trace, setTrace] = useState<Step[]>([]);
  const [input, setInput] = useState('');
  const [running, setRunning] = useState(false);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [conns, setConns] = useState<Connection[]>([]);
  const [agentName, setAgentName] = useState('Agent Y');
  const scrollRef = useRef<HTMLDivElement>(null);
  const streamId = useRef<string | null>(null);

  const refreshThreads = () => listSessions().then(setThreads).catch(() => {});
  const refreshConfig = () => {
    listProviders().then(setConns).catch(() => {});
    getSettings().then((d) => setAgentName(d.settings.agent_name || 'Agent Y')).catch(() => {});
  };
  useEffect(() => { refreshThreads(); refreshConfig(); }, []);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }); }, [messages, trace, running]);

  const active = conns.find((c) => c.active);

  const onFrame = (fr: Frame) => {
    if (fr.type === 'text_delta' && fr.text) {
      const cur = streamId.current;
      if (cur) setMessages((p) => p.map((m) => (m.id === cur ? { ...m, content: m.content + fr.text } : m)));
      else { const id = uid(); streamId.current = id; setMessages((p) => [...p, { id, role: 'assistant', content: fr.text }]); }
    } else if (fr.type === 'tool_use') {
      streamId.current = null;
      setTrace((p) => [...p, { id: fr.id, label: fr.name, target: target(fr.input), status: 'running' }]);
    } else if (fr.type === 'tool_result') {
      setTrace((p) => p.map((s) => (s.id === fr.id ? { ...s, status: fr.is_error ? 'error' : 'done' } : s)));
    } else if (fr.type === 'approval_request') setApproval(fr);
    else if (fr.type === 'done') streamId.current = null;
    else if (fr.type === 'error') setError(fr.message);
  };

  const run = async () => {
    const text = input.trim();
    if (running || !text) return;
    setInput(''); setError(null); setRunning(true);
    setMessages((p) => [...p, { id: uid(), role: 'user', content: text }]);
    streamId.current = null;
    try {
      let sid = sessionId;
      if (!sid) { sid = await createSession(text.slice(0, 40), scene); setSessionId(sid); }
      for await (const fr of streamMessage(sid, text)) onFrame(fr);
      refreshThreads();
    } catch (e) { setError(String(e)); }
    finally { setRunning(false); setApproval(null); }
  };

  const decide = async (d: 'allow' | 'deny') => { const a = approval; setApproval(null); if (a) await postApproval(a.approval_id, d); };
  const newThread = () => { setSessionId(null); setMessages([]); setTrace([]); setError(null); };
  const selectThread = async (id: string) => { setSessionId(id); setTrace([]); setError(null); setMessages(toChat(await getSessionMessages(id))); };

  return (
    <div className="flex h-screen w-full overflow-hidden" style={{ color: 'var(--color-ink)' }}>
      {/* SIDEBAR */}
      <aside className="w-[258px] shrink-0 hidden md:flex flex-col" style={{ background: 'var(--color-panel)', borderRight: '1px solid var(--color-line)' }}>
        <div className="h-16 flex items-center px-5 gap-3">
          <AgentOrb running={running} size={18} />
          <span className="font-serif text-[22px] leading-none tracking-tight">{agentName}</span>
        </div>

        <div className="px-4">
          <button onClick={newThread} className="btn btn-outline w-full justify-start"><Plus className="w-4 h-4" style={{ color: 'var(--color-gold)' }} /> 新对话</button>
          <div className="flex gap-1 mt-3 p-1 rounded-xl" style={{ background: 'var(--color-bg)' }}>
            {([['assistant', '助手', Briefcase], ['coding', '编码', Code2]] as const).map(([s, label, Icon]) => (
              <button key={s} onClick={() => setScene(s)} className="flex-1 btn text-[12.5px] py-1.5"
                style={scene === s ? { background: 'var(--color-elevated)', color: 'var(--color-ink)' } : { color: 'var(--color-ink-3)' }}>
                <Icon className="w-3.5 h-3.5" /> {label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-3 mt-5 no-scrollbar">
          <div className="label px-2 mb-2">最近</div>
          {threads.length === 0 && <div className="px-2 text-[12.5px]" style={{ color: 'var(--color-ink-3)' }}>还没有对话。</div>}
          {threads.map((th) => {
            const on = th.id === sessionId;
            return (
              <button key={th.id} onClick={() => selectThread(th.id)}
                className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left transition-colors mb-0.5"
                style={on ? { background: 'var(--color-elevated)', boxShadow: 'inset 2px 0 0 var(--color-gold)' } : {}}>
                <MessageSquare className="w-3.5 h-3.5 shrink-0" style={{ color: on ? 'var(--color-gold)' : 'var(--color-ink-3)' }} />
                <span className="text-[13px] truncate" style={{ color: on ? 'var(--color-ink)' : 'var(--color-ink-2)' }}>{th.title}</span>
              </button>
            );
          })}
        </div>

        <div className="p-3" style={{ borderTop: '1px solid var(--color-line)' }}>
          <button onClick={() => setShowSettings(true)} className="btn btn-ghost w-full justify-start"><SettingsIcon className="w-4 h-4" /> 设置</button>
        </div>
      </aside>

      {/* MAIN */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-16 flex items-center justify-between px-6 shrink-0" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <button onClick={() => setShowSettings(true)} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[13px]"
            style={{ background: 'var(--color-panel)', border: '1px solid var(--color-line)' }}>
            <KeyRound className="w-3.5 h-3.5" style={{ color: active ? 'var(--color-gold)' : 'var(--color-danger)' }} />
            <span style={{ color: 'var(--color-ink-2)' }}>{active ? (active.model_default || active.provider) : '未配置模型'}</span>
          </button>
          <div className="flex items-center gap-2">
            <AgentOrb running={running} size={13} />
            <span className="text-[12px]" style={{ color: 'var(--color-ink-3)' }}>{running ? '思考中…' : '在线'}</span>
          </div>
        </header>

        <div className="flex flex-1 overflow-hidden">
          <div className="flex-1 flex flex-col min-w-0 relative">
            <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 pt-10 pb-44 no-scrollbar">
              <div className="max-w-2xl mx-auto w-full">
                {messages.length === 0 && (
                  <div className="mt-20 flex flex-col items-center text-center rise">
                    <AgentOrb running={running} size={72} />
                    <div className="font-serif text-[40px] leading-tight mt-7 mb-2">{greet()}</div>
                    <p className="text-[14px] max-w-sm" style={{ color: 'var(--color-ink-3)' }}>
                      {conns.length === 0
                        ? '我是你的私人 AI 助手。先配一个模型连接，我们就能开始。'
                        : scene === 'assistant' ? '问我点什么，或让我帮你整理文件、起草、做表格。' : '给我一个编码任务，我会读 / 改 / 跑测试。'}
                    </p>
                    {conns.length === 0 && (
                      <button onClick={() => setShowSettings(true)} className="btn btn-gold mt-6"><KeyRound className="w-4 h-4" /> 配置模型连接</button>
                    )}
                  </div>
                )}
                {messages.map((m) => (
                  <div key={m.id} className={`rise mb-8 flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    {m.role === 'user'
                      ? <div className="max-w-[82%] px-4 py-2.5 rounded-2xl rounded-tr-md text-[14px] leading-relaxed" style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-line)' }}>{m.content}</div>
                      : <div className="max-w-[88%]">
                          <div className="text-[12px] font-medium mb-1.5 tracking-wide" style={{ color: 'var(--color-gold)' }}>{agentName}</div>
                          <div className="text-[14.5px] leading-[1.75] whitespace-pre-wrap" style={{ color: 'var(--color-ink)' }}>{m.content}</div>
                        </div>}
                  </div>
                ))}
                {running && !messages.some((m) => m.id === streamId.current) && (
                  <div className="flex gap-1.5 items-center mb-8">
                    {[0, 0.2, 0.4].map((d) => <span key={d} className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--color-gold)', animation: `blink 1.4s ${d}s infinite` }} />)}
                  </div>
                )}
                {error && <div className="text-[13px] rounded-xl px-4 py-2.5 mb-6" style={{ color: 'var(--color-danger)', background: 'rgba(224,121,106,0.1)', border: '1px solid rgba(224,121,106,0.25)' }}>{error}</div>}
              </div>
            </div>

            {/* INPUT */}
            <div className="absolute bottom-0 inset-x-0 px-6 pb-6 pt-12 pointer-events-none" style={{ background: 'linear-gradient(to top, var(--color-bg) 55%, transparent)' }}>
              <div className="max-w-2xl mx-auto pointer-events-auto">
                <div className="flex items-end gap-2 p-2 rounded-2xl" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-line-2)' }}>
                  <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={1} disabled={running}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); run(); } }}
                    placeholder={scene === 'assistant' ? '问问你的助手…' : '让我改代码 / 修测试…'}
                    className="flex-1 bg-transparent outline-none resize-none px-3 py-2.5 text-[14px] max-h-44" style={{ color: 'var(--color-ink)' }} />
                  <button onClick={run} disabled={running || !input.trim()} className="btn btn-gold w-10 h-10 p-0 shrink-0"><ArrowUp className="w-[18px] h-[18px]" /></button>
                </div>
              </div>
            </div>
          </div>

          {/* TRACE */}
          {scene === 'coding' && (
            <aside className="w-[340px] shrink-0 hidden lg:flex flex-col" style={{ background: 'var(--color-panel)', borderLeft: '1px solid var(--color-line)' }}>
              <div className="h-12 flex items-center px-5" style={{ borderBottom: '1px solid var(--color-line)' }}>
                <span className="label flex items-center gap-2"><Activity className="w-3.5 h-3.5" /> 执行轨迹</span>
              </div>
              <div className="flex-1 overflow-y-auto p-5 no-scrollbar">
                {trace.length === 0 && <div className="text-[12.5px]" style={{ color: 'var(--color-ink-3)' }}>工具调用会实时出现在这里。</div>}
                <div className="space-y-4">
                  {trace.map((s) => (
                    <div key={s.id} className="flex items-start gap-3 rise">
                      <div className="mt-0.5">
                        {s.status === 'done' ? <Check className="w-3.5 h-3.5" style={{ color: 'var(--color-ok)' }} strokeWidth={3} />
                          : s.status === 'error' ? <X className="w-3.5 h-3.5" style={{ color: 'var(--color-danger)' }} strokeWidth={3} />
                          : <span className="block w-2 h-2 rounded-full mt-1" style={{ background: 'var(--color-gold)', animation: 'blink 1.2s infinite' }} />}
                      </div>
                      <div className="min-w-0 font-mono text-[12.5px]">
                        <div style={{ color: s.status === 'error' ? 'var(--color-danger)' : 'var(--color-ink)' }}>{s.label}</div>
                        {s.target && <div className="text-[11px] truncate mt-0.5" style={{ color: 'var(--color-ink-3)' }}>{s.target}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </aside>
          )}
        </div>
      </main>

      {/* APPROVAL */}
      <AnimatePresence>
        {approval && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-[110] flex items-center justify-center px-4" style={{ background: 'rgba(43,42,39,0.42)' }}>
            <motion.div initial={{ opacity: 0, scale: 0.97, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }}
              className="card w-full max-w-md overflow-hidden" style={{ boxShadow: '0 30px 80px rgba(60,40,30,0.22)' }}>
              <div className="flex items-center gap-3 px-5 h-14" style={{ borderBottom: '1px solid var(--color-line)' }}>
                <AlertTriangle className="w-4 h-4" style={{ color: 'var(--color-gold)' }} />
                <span className="font-medium">需要你确认</span>
              </div>
              <div className="p-5 space-y-3">
                <div className="text-[14px]">{approval.summary || approval.tool}</div>
                <div className="flex items-center gap-2 text-[12px]">
                  <span style={{ color: 'var(--color-ink-3)' }}>风险</span>
                  <span className="px-2 py-0.5 rounded font-medium" style={{
                    color: approval.risk === 'high' ? 'var(--color-danger)' : 'var(--color-gold)',
                    background: approval.risk === 'high' ? 'rgba(224,121,106,0.12)' : 'rgba(214,168,102,0.12)' }}>{approval.risk}</span>
                </div>
              </div>
              <div className="flex justify-end gap-2 px-5 py-4" style={{ borderTop: '1px solid var(--color-line)' }}>
                <button onClick={() => decide('deny')} className="btn btn-ghost">拒绝</button>
                <button onClick={() => decide('allow')} className="btn btn-gold">允许本次</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showSettings && <SettingsPanel onClose={() => { setShowSettings(false); refreshConfig(); }} />}
      </AnimatePresence>
    </div>
  );
}
