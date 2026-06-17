import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  MessageSquare, Sparkles, Plus, Settings, ChevronDown,
  Code2, Briefcase, Play, Check, Terminal,
  Box, Database, ArrowRight, ChevronRight, AlertTriangle, X,
} from 'lucide-react';
import {
  createSession, listSessions, getSessionMessages, streamMessage, postApproval,
  type Frame, type SessionSummary,
} from './api';

type Msg = { id: string; role: 'user' | 'assistant'; content: string };
type Step = { id: string; label: string; target?: string; status: 'running' | 'done' | 'error' };
type Approval = Extract<Frame, { type: 'approval_request' }>;

const uid = () => Math.random().toString(36).slice(2);

function traceTarget(input: Record<string, any>): string {
  if (input?.path) return String(input.path);
  if (input?.cmd) return String(input.cmd);
  const v = Object.values(input || {})[0];
  return v !== undefined ? String(v) : '';
}

// 把后端存的消息（含 tool_use/tool_result 块）映射成 chat 文本气泡
function toChat(stored: { role: string; content: any[] }[]): Msg[] {
  const out: Msg[] = [];
  for (const m of stored) {
    const text = (m.content || [])
      .filter((b) => b.type === 'text' && b.text)
      .map((b) => b.text)
      .join('\n');
    if (text) out.push({ id: uid(), role: m.role === 'user' ? 'user' : 'assistant', content: text });
  }
  return out;
}

export default function App() {
  const [scene, setScene] = useState<'coding' | 'assistant'>('coding');
  const [threads, setThreads] = useState<SessionSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [trace, setTrace] = useState<Step[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [running, setRunning] = useState(false);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const refreshThreads = async () => setThreads(await listSessions().catch(() => []));
  useEffect(() => { refreshThreads(); }, []);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, trace]);

  const handleFrame = (fr: Frame) => {
    switch (fr.type) {
      case 'text_delta':
        if (fr.text) setMessages((p) => [...p, { id: uid(), role: 'assistant', content: fr.text }]);
        break;
      case 'tool_use':
        setTrace((p) => [...p, { id: fr.id, label: fr.name, target: traceTarget(fr.input), status: 'running' }]);
        break;
      case 'tool_result':
        setTrace((p) => p.map((s) => (s.id === fr.id ? { ...s, status: fr.is_error ? 'error' : 'done' } : s)));
        break;
      case 'approval_request':
        setApproval(fr);
        break;
      case 'error':
        setError(fr.message);
        break;
    }
  };

  const handleRun = async () => {
    const text = inputValue.trim();
    if (running || !text) return;
    setInputValue('');
    setError(null);
    setRunning(true);
    setMessages((p) => [...p, { id: uid(), role: 'user', content: text }]);
    try {
      let sid = sessionId;
      if (!sid) {
        sid = await createSession(text.slice(0, 40), scene);
        setSessionId(sid);
        refreshThreads();
      }
      for await (const fr of streamMessage(sid, text)) handleFrame(fr);
      refreshThreads();
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
      setApproval(null);
    }
  };

  const decide = async (decision: 'allow' | 'deny') => {
    const a = approval;
    setApproval(null);
    if (a) await postApproval(a.approval_id, decision); // 后端恢复，进行中的 SSE 继续收帧
  };

  const newThread = async () => {
    const sid = await createSession('新会话', scene).catch(() => null);
    setSessionId(sid);
    setMessages([]); setTrace([]); setError(null);
    refreshThreads();
  };

  const selectThread = async (id: string) => {
    setSessionId(id);
    setTrace([]); setError(null);
    setMessages(toChat(await getSessionMessages(id)));
  };

  return (
    <div className="flex h-screen w-full bg-[#FAFAFC] font-sans overflow-hidden text-gray-900 selection:bg-gray-200">
      {/* THREADS SIDEBAR */}
      <aside className="w-[260px] shrink-0 bg-[#F4F4F5] border-r border-gray-200/60 flex flex-col hidden md:flex z-10">
        <div className="h-14 flex items-center px-5 shrink-0 border-b border-gray-200/50">
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 bg-gray-900 text-white rounded flex items-center justify-center shadow-sm">
              <Box className="w-3.5 h-3.5" strokeWidth={2.5} />
            </div>
            <span className="font-semibold tracking-tight text-[14px]">Agent Y</span>
          </div>
        </div>
        <div className="p-4">
          <button onClick={newThread} className="w-full flex items-center gap-2 px-3 py-2 text-[13px] font-medium text-gray-700 bg-white border border-gray-200/80 rounded shadow-[0_1px_2px_rgb(0,0,0,0.02)] hover:shadow-sm hover:border-gray-300 transition-all">
            <Plus className="w-4 h-4 text-gray-400" /> New Thread
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-2 no-scrollbar">
          <div className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest mb-3 px-2">Threads</div>
          <div className="space-y-0.5">
            {threads.length === 0 && <div className="px-3 text-[12px] text-gray-400">还没有会话，发一条消息开始。</div>}
            {threads.map((th) => {
              const active = th.id === sessionId;
              return (
                <button key={th.id} onClick={() => selectThread(th.id)}
                  className={`w-full flex items-center text-left px-3 py-2 rounded-md transition-colors ${active ? 'bg-white shadow-[0_1px_3px_rgb(0,0,0,0.04)] border border-gray-200/60' : 'border border-transparent hover:bg-gray-200/40'}`}>
                  <div className="flex items-center gap-2.5 min-w-0">
                    <MessageSquare className={`w-3.5 h-3.5 shrink-0 ${active ? 'text-gray-900' : 'text-gray-400'}`} />
                    <span className={`text-[13px] truncate ${active ? 'font-medium text-gray-900' : 'text-gray-600'}`}>{th.title}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
        <div className="p-4 border-t border-gray-200/50">
          <button className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-200/40 rounded transition-colors border border-transparent">
            <Settings className="w-4 h-4 text-gray-400" /> Settings
          </button>
        </div>
      </aside>

      {/* MAIN + TRACE */}
      <main className="flex-1 flex flex-col min-w-0 bg-white">
        <header className="h-14 flex items-center justify-between px-6 border-b border-gray-200/60 shrink-0 bg-white z-10">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-gray-200 bg-gray-50/50 shadow-sm">
              <Sparkles className="w-3.5 h-3.5 text-gray-600" />
              <span className="text-[13px] font-medium text-gray-700">模型由后端配置</span>
              <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
            </div>
            <div className="hidden lg:flex items-center gap-2 text-[13px] text-gray-400 font-medium tracking-wide">
              <span>{sessionId ? sessionId.slice(0, 12) : 'new'}</span>
              <ChevronRight className="w-3 h-3 text-gray-300" />
              <span className="text-gray-600">{running ? 'running' : 'idle'}</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex bg-gray-100/80 p-0.5 rounded-md border border-gray-200/50">
              <button onClick={() => setScene('coding')} className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-[12px] font-medium transition-all ${scene === 'coding' ? 'bg-white text-gray-900 shadow-[0_1px_2px_rgb(0,0,0,0.06)]' : 'text-gray-500 hover:text-gray-700'}`}>
                <Code2 className="w-3.5 h-3.5" /> Code
              </button>
              <button onClick={() => setScene('assistant')} className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-[12px] font-medium transition-all ${scene === 'assistant' ? 'bg-white text-gray-900 shadow-[0_1px_2px_rgb(0,0,0,0.06)]' : 'text-gray-500 hover:text-gray-700'}`}>
                <Briefcase className="w-3.5 h-3.5" /> Assist
              </button>
            </div>
          </div>
        </header>

        <div className="flex flex-1 overflow-hidden">
          {/* CHAT */}
          <div className="flex flex-1 flex-col relative min-w-0">
            <div ref={scrollRef} className="flex-1 overflow-y-auto w-full pt-10 pb-40 px-6 no-scrollbar">
              <div className="max-w-3xl mx-auto w-full">
                {messages.length === 0 && (
                  <div className="text-center text-gray-400 text-[14px] mt-20">输入一个编码任务，Agent Y 会在沙箱里读/改/跑测试。</div>
                )}
                {messages.map((msg) => (
                  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} key={msg.id}
                    className={`flex gap-5 mb-10 group ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    {msg.role === 'assistant' && (
                      <div className="shrink-0 pt-0.5 select-none">
                        <div className="w-7 h-7 rounded border border-gray-200 bg-gray-50 flex items-center justify-center text-gray-600 shadow-[0_1px_2px_rgb(0,0,0,0.02)]"><Box className="w-4 h-4" /></div>
                      </div>
                    )}
                    <div className={`max-w-[85%] ${msg.role === 'user' ? 'bg-gray-100 rounded-[18px] rounded-tr-sm px-5 py-3.5 border border-gray-200/50 shadow-sm' : 'pt-0.5'}`}>
                      {msg.role === 'assistant' && <div className="font-semibold text-gray-900 text-sm mb-1.5 tracking-wide">Agent Y</div>}
                      <div className={`text-[14px] leading-relaxed whitespace-pre-wrap ${msg.role === 'user' ? 'text-gray-800' : 'text-gray-700'} tracking-wide`}>{msg.content}</div>
                    </div>
                  </motion.div>
                ))}
                <AnimatePresence>
                  {running && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex gap-5 mb-10 justify-start">
                      <div className="shrink-0 pt-0.5 opacity-50"><div className="w-7 h-7 rounded border border-gray-200 bg-gray-50 flex items-center justify-center text-gray-600 shadow-sm"><Box className="w-4 h-4" /></div></div>
                      <div className="pt-1.5 flex gap-1.5 items-center">
                        {[0, 0.2, 0.4].map((d) => (
                          <motion.div key={d} animate={{ opacity: [0.3, 1, 0.3] }} transition={{ repeat: Infinity, duration: 1.5, delay: d }} className="w-1.5 h-1.5 rounded-full bg-gray-500" />
                        ))}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
                {error && <div className="text-[13px] text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2 mb-6">⚠️ {error}</div>}
              </div>
            </div>

            {/* INPUT */}
            <div className="absolute bottom-0 w-full bg-gradient-to-t from-white via-white/95 to-transparent pt-12 pb-6 px-6 z-10 pointer-events-none">
              <div className="max-w-3xl mx-auto relative pointer-events-auto shadow-sm">
                <div className="bg-white border border-gray-200/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-[16px] p-1.5 flex items-end focus-within:border-gray-300 relative overflow-hidden">
                  <div className="absolute top-0 left-0 w-1 h-full bg-gray-900 rounded-l-[16px]" />
                  <div className="p-3 pl-4"><Terminal className="w-[18px] h-[18px] text-gray-400" /></div>
                  <textarea value={inputValue} onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleRun(); } }}
                    className="flex-1 max-h-48 bg-transparent py-3 px-1 outline-none resize-none text-[14px] text-gray-800 placeholder-gray-400 tracking-wide"
                    rows={1} placeholder={scene === 'coding' ? '让 agent 改代码 / 修测试…' : '问问你的助手…'} disabled={running} />
                  <button onClick={handleRun} disabled={running}
                    className={`p-2.5 m-1 rounded-[10px] transition-all shrink-0 flex items-center justify-center ${!running ? 'bg-gray-900 text-white hover:bg-gray-800 shadow-[0_2px_4px_rgb(0,0,0,0.1)]' : 'bg-gray-100 text-gray-400 cursor-not-allowed'}`}>
                    <Play className="w-[14px] h-[14px] fill-current" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* TRACE PANEL */}
          {scene === 'coding' && (
            <aside className="w-[360px] shrink-0 border-l border-gray-200/60 bg-[#FAFAFC] flex flex-col hidden lg:flex">
              <div className="h-12 border-b border-gray-200/60 flex items-center px-5 shrink-0 bg-white">
                <h3 className="text-[11px] font-semibold text-gray-500 uppercase tracking-widest flex items-center gap-2"><Database className="w-3.5 h-3.5" /> Execution Trace</h3>
              </div>
              <div className="flex-1 overflow-y-auto p-6 relative no-scrollbar">
                {trace.length === 0 && <div className="text-[12px] text-gray-400">工具调用会实时出现在这里。</div>}
                {trace.length > 0 && <div className="absolute left-[34px] top-8 bottom-8 w-[1px] bg-gray-200" />}
                <div className="space-y-6 relative">
                  {trace.map((step) => (
                    <motion.div layout key={step.id} initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0 }} className="flex items-start gap-4 z-10 relative">
                      <div className="mt-0.5 bg-[#FAFAFC]">
                        {step.status === 'done' ? (
                          <div className="w-[18px] h-[18px] rounded-full border border-gray-300 flex items-center justify-center bg-white shadow-sm"><Check className="w-2.5 h-2.5 text-gray-700" strokeWidth={3} /></div>
                        ) : step.status === 'error' ? (
                          <div className="w-[18px] h-[18px] rounded-full border border-red-300 flex items-center justify-center bg-red-50"><X className="w-2.5 h-2.5 text-red-600" strokeWidth={3} /></div>
                        ) : (
                          <div className="w-[18px] h-[18px] flex items-center justify-center"><div className="w-2 h-2 rounded-full bg-gray-900 animate-pulse" /></div>
                        )}
                      </div>
                      <div className="flex-1 min-w-0 font-mono text-[13px] pt-px">
                        <div className={`${step.status === 'running' ? 'text-gray-900 font-semibold' : step.status === 'error' ? 'text-red-700' : 'text-gray-700'} truncate`}>{step.label}</div>
                        {step.target && <div className="text-[11px] text-gray-500 mt-0.5 truncate pr-2">{step.target}</div>}
                      </div>
                    </motion.div>
                  ))}
                </div>
              </div>
              <div className="p-5 border-t border-gray-200/60 bg-white shrink-0 z-10">
                <div className="flex items-center justify-between font-mono text-[12px] tracking-wide">
                  <span className="text-gray-500">Eval pass@1</span>
                  <span className="flex items-center gap-2 font-medium text-gray-800">62% <ArrowRight className="w-3.5 h-3.5 text-gray-400" /> <span className="text-gray-900 bg-gray-100 px-1.5 py-0.5 rounded">81%</span></span>
                </div>
              </div>
            </aside>
          )}
        </div>
      </main>

      {/* APPROVAL MODAL */}
      <AnimatePresence>
        {approval && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-[100] flex items-center justify-center bg-gray-900/20 backdrop-blur-sm px-4">
            <motion.div initial={{ opacity: 0, scale: 0.97, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97, y: 10 }} transition={{ type: 'spring', bounce: 0, duration: 0.4 }}
              className="w-full max-w-md bg-white border border-gray-200 rounded-[20px] shadow-2xl flex flex-col overflow-hidden">
              <div className="p-5 border-b border-gray-100 flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 shrink-0"><AlertTriangle className="w-4 h-4" /></div>
                <div className="font-semibold text-gray-900">需要确认</div>
              </div>
              <div className="p-6 space-y-4">
                <div className="bg-[#FAFAFC] border border-gray-200/80 p-3 rounded-xl shadow-sm">
                  <div className="text-[10px] uppercase text-gray-400 tracking-wider mb-1 font-semibold">操作</div>
                  <div className="text-gray-900 font-medium text-[14px]">{approval.summary || approval.tool}</div>
                </div>
                <div className="flex items-center gap-2 text-[13px]">
                  <span className="text-gray-500">风险等级</span>
                  <span className={`px-2 py-0.5 rounded font-medium ${approval.risk === 'high' ? 'bg-red-100 text-red-700' : approval.risk === 'medium' ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-600'}`}>{approval.risk}</span>
                </div>
              </div>
              <div className="p-4 px-6 border-t border-gray-100 bg-[#FAFAFC] flex justify-end gap-3">
                <button onClick={() => decide('deny')} className="px-5 py-2.5 rounded-[12px] font-medium text-gray-600 hover:bg-gray-200 transition-colors text-[13px]">拒绝</button>
                <button onClick={() => decide('allow')} className="px-6 py-2.5 rounded-[12px] font-medium bg-gray-900 shadow-[0_2px_4px_rgb(0,0,0,0.1)] hover:bg-gray-800 text-white transition-all text-[13px]">允许本次</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
