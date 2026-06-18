import React from 'react';
import { motion } from 'motion/react';
import {
  MessageCircle, Sparkles, BookOpen, Calendar, Send, Paperclip, Square,
  CheckCircle2, Circle, Droplets, Wind, Plus, Trash2, X, KeyRound,
} from 'lucide-react';
import type { Weather, Todo, Folder } from './api';
import Markdown from './Markdown';

type Msg = { id: string; role: 'user' | 'assistant'; content: string };

// WMO 天气代码 → emoji（手绘风用 emoji 更贴）
function codeEmoji(code?: number): string {
  if (code == null) return '🌡';
  if (code === 0) return '☀️';
  if (code === 1) return '🌤';
  if (code === 2) return '⛅';
  if (code === 3) return '☁️';
  if (code === 45 || code === 48) return '🌫';
  if (code >= 51 && code <= 67) return '🌧';
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return '❄️';
  if (code >= 80 && code <= 82) return '🌦';
  if (code >= 95) return '⛈';
  return '🌡';
}

const SKETCH = "'Comic Sans MS', 'Chalkboard SE', 'Marker Felt', cursive";

const QUICK = [
  { icon: Sparkles, label: '创意灵感', color: '#f4a261', prompt: '给我几个关于' },
  { icon: BookOpen, label: '学习笔记', color: '#6a9fb5', prompt: '帮我把这些整理成学习笔记：' },
  { icon: Calendar, label: '日程安排', color: '#e76f51', prompt: '帮我安排今天的日程：' },
  { icon: MessageCircle, label: '快速问答', color: '#2a9d8f', prompt: '' },
];

export interface AssistantPaperProps {
  agentName: string;
  messages: Msg[];
  running: boolean;
  input: string; setInput: (v: string) => void; onSend: () => void; onStop: () => void;
  weather: Weather | null;
  todos: Todo[]; newTodo: string; setNewTodo: (v: string) => void;
  onAddTodo: () => void; onToggleTodo: (t: Todo) => void; onDeleteTodo: (id: string) => void;
  folders: Folder[]; onPickFolder: () => void; onRemoveFolder: (id: string) => void;
  hasConns: boolean; onOpenSettings: () => void;
  error: string | null;
}

export default function AssistantPaper(p: AssistantPaperProps) {
  const pending = p.todos.filter((t) => !t.done).length;
  const progress = p.todos.length ? Math.round(p.todos.filter((t) => t.done).length / p.todos.length * 100) : 0;
  const cur = p.weather?.current;
  const today = p.weather?.today;
  const temp = cur?.temp ?? today?.tmax ?? null;

  return (
    <div className="flex-1 flex flex-col overflow-hidden relative" style={{ fontFamily: SKETCH }}>
      {/* 手绘 SVG 滤镜 + 涂鸦装饰 */}
      <svg style={{ position: 'absolute', width: 0, height: 0 }}>
        <defs>
          <filter id="sketch"><feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="5" result="noise" /><feDisplacementMap in="SourceGraphic" in2="noise" scale="1.2" xChannelSelector="R" yChannelSelector="G" /></filter>
        </defs>
      </svg>
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <svg className="absolute top-6 right-14 opacity-20" width="56" height="56" viewBox="0 0 60 60">
          <circle cx="30" cy="30" r="12" fill="#f4a261" stroke="#e76f51" strokeWidth="2" />
          {[0, 45, 90, 135, 180, 225, 270, 315].map((a, i) => (
            <line key={i} x1={30 + 16 * Math.cos(a * Math.PI / 180)} y1={30 + 16 * Math.sin(a * Math.PI / 180)} x2={30 + 24 * Math.cos(a * Math.PI / 180)} y2={30 + 24 * Math.sin(a * Math.PI / 180)} stroke="#e76f51" strokeWidth="2.5" strokeLinecap="round" />
          ))}
        </svg>
        {[[86, 12], [10, 30], [91, 56], [7, 72], [93, 84]].map(([x, y], i) => (
          <svg key={i} className="absolute opacity-15" style={{ left: `${x}%`, top: `${y}%` }} width="15" height="15" viewBox="0 0 16 16">
            <polygon points="8,1 10,6 15,6 11,10 13,15 8,12 3,15 5,10 1,6 6,6" fill="#f4a261" stroke="#e76f51" strokeWidth="0.5" />
          </svg>
        ))}
        <svg className="absolute bottom-0 left-0 right-0 opacity-10" width="100%" height="56" viewBox="0 0 800 60" preserveAspectRatio="none">
          <path d="M0,30 Q50,10 100,30 T200,30 T300,30 T400,30 T500,30 T600,30 T700,30 T800,30" fill="none" stroke="#6a9fb5" strokeWidth="3" strokeLinecap="round" />
          <path d="M0,45 Q50,25 100,45 T200,45 T300,45 T400,45 T500,45 T600,45 T700,45 T800,45" fill="none" stroke="#f4a261" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </div>

      <div className="flex-1 flex gap-3 p-4 overflow-hidden relative">
        {/* 左：天气 + 快速操作 + 提示 */}
        <motion.div initial={{ x: -16, opacity: 0 }} animate={{ x: 0, opacity: 1 }} className="w-56 flex flex-col gap-3 overflow-y-auto no-scrollbar flex-shrink-0">
          <div className="hd-card p-3" style={{ background: 'linear-gradient(135deg, #e8f4fd 0%, #fffef9 100%)' }}>
            <p style={{ fontSize: '10px', color: '#9ca3af', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              📍 {p.weather?.ok && p.weather.label ? p.weather.label : '我的城市'} · 今日天气
            </p>
            {p.weather?.ok ? (
              <>
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <span style={{ fontSize: '30px', lineHeight: 1 }}>{codeEmoji(cur?.code ?? today?.code)}</span>
                    <p style={{ fontSize: '11px', color: '#6b7280', marginTop: '2px' }}>{cur?.text ?? today?.text ?? ''}</p>
                  </div>
                  <div className="text-right">
                    <p style={{ fontSize: '28px', color: '#2d2926', fontWeight: 700, lineHeight: 1 }}>{temp != null ? `${Math.round(temp)}°` : '—'}</p>
                    {cur?.feels != null && <p style={{ fontSize: '10px', color: '#9ca3af' }}>体感 {Math.round(cur.feels)}°</p>}
                  </div>
                </div>
                {(cur?.humidity != null || cur?.wind != null) && (
                  <div className="flex items-center gap-3 mb-2" style={{ borderTop: '1px dashed rgba(45,41,38,0.15)', paddingTop: '6px' }}>
                    {cur?.humidity != null && <div className="flex items-center gap-1"><Droplets size={10} style={{ color: '#6a9fb5' }} /><span style={{ fontSize: '10px', color: '#6b7280' }}>{cur.humidity}%</span></div>}
                    {cur?.wind != null && <div className="flex items-center gap-1"><Wind size={10} style={{ color: '#6a9fb5' }} /><span style={{ fontSize: '10px', color: '#6b7280' }}>{Math.round(cur.wind)} km/h</span></div>}
                  </div>
                )}
                {p.weather.hourly && p.weather.hourly.length > 0 && (
                  <div className="flex justify-between">
                    {p.weather.hourly.slice(0, 5).map((h, i) => (
                      <div key={i} className="flex flex-col items-center gap-0.5">
                        <span style={{ fontSize: '9px', color: '#9ca3af' }}>{i === 0 ? '现在' : h.time}</span>
                        <span style={{ fontSize: '13px' }}>{codeEmoji(h.code)}</span>
                        <span style={{ fontSize: '10px', color: '#374151', fontWeight: 600 }}>{h.temp != null ? `${Math.round(h.temp)}°` : '—'}</span>
                      </div>
                    ))}
                  </div>
                )}
                {p.weather.advice && (
                  <p style={{ fontSize: '10.5px', color: '#6b7280', marginTop: '8px', borderTop: '1px dashed rgba(45,41,38,0.15)', paddingTop: '6px', lineHeight: 1.5 }}>☂️ {p.weather.advice}</p>
                )}
              </>
            ) : (
              <button onClick={p.onOpenSettings} style={{ fontSize: '11px', color: '#9ca3af', textAlign: 'left', lineHeight: 1.6 }}>
                在设置里填写城市，这里就会画出今天的天气和出行小贴士 →
              </button>
            )}
          </div>

          <div className="hd-card p-3 flex flex-col">
            <p style={{ fontSize: '10px', color: '#9ca3af', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>快速操作</p>
            <div className="space-y-1.5">
              {QUICK.map((a, i) => (
                <motion.button key={i} whileHover={{ x: 4, scale: 1.01 }} whileTap={{ scale: 0.98 }} onClick={() => p.setInput(a.prompt)}
                  className="w-full flex items-center gap-2.5 p-2 rounded-lg hover:bg-black/5 transition-colors" style={{ cursor: 'pointer' }}>
                  <div className="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: a.color + '20', border: `1.5px solid ${a.color}` }}>
                    <a.icon size={12} style={{ color: a.color }} />
                  </div>
                  <span style={{ fontSize: '12px', color: '#374151' }}>{a.label}</span>
                </motion.button>
              ))}
            </div>
          </div>

          <div className="hd-card p-3" style={{ background: '#fff9e6' }}>
            <div className="flex items-start gap-2">
              <span style={{ fontSize: '14px' }}>💡</span>
              <p style={{ fontSize: '11px', color: '#6b7280', lineHeight: 1.5 }}>"把复杂的事情简单化，这就是智慧。"</p>
            </div>
          </div>
        </motion.div>

        {/* 中：对话 */}
        <motion.div initial={{ y: 16, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.05 }} className="flex-1 flex flex-col overflow-hidden">
          <div className="hd-card flex-1 flex flex-col overflow-hidden" style={{ padding: 0 }}>
            <div className="flex items-center gap-2 px-4 py-3" style={{ borderBottom: '2px dashed rgba(45,41,38,0.15)' }}>
              <MessageCircle size={15} style={{ color: '#f4a261' }} />
              <span style={{ fontSize: '13px', color: '#2d2926', fontWeight: 600 }}>对话记录</span>
              {!p.hasConns && (
                <button onClick={p.onOpenSettings} className="ml-auto flex items-center gap-1" style={{ fontSize: '11px', color: '#e76f51' }}>
                  <KeyRound size={11} /> 未配置模型
                </button>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4 no-scrollbar">
              {p.messages.length === 0 && (
                <div className="flex justify-start">
                  <div className="w-7 h-7 rounded-full flex items-center justify-center mr-2 flex-shrink-0 mt-1" style={{ background: '#f4a261', border: '2px solid #2d2926', boxShadow: '2px 2px 0 #2d2926' }}>
                    <Sparkles size={12} style={{ color: 'white' }} />
                  </div>
                  <div className="max-w-[70%] px-4 py-3 hd-bubble-l" style={{ background: '#fffef9', color: '#2d2926', border: '2px solid #2d2926', boxShadow: '3px 3px 0 rgba(45,41,38,0.15)', fontSize: '13px', lineHeight: 1.6 }}>
                    你好！我是 {p.agentName} ✨ 有什么可以帮你的吗？{p.hasConns ? '' : '（先去设置里配个模型连接哦）'}
                  </div>
                </div>
              )}
              {p.messages.map((m, idx) => (
                <motion.div key={m.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(idx, 4) * 0.04 }}
                  className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  {m.role === 'assistant' && (
                    <div className="w-7 h-7 rounded-full flex items-center justify-center mr-2 flex-shrink-0 mt-1" style={{ background: '#f4a261', border: '2px solid #2d2926', boxShadow: '2px 2px 0 #2d2926' }}>
                      <Sparkles size={12} style={{ color: 'white' }} />
                    </div>
                  )}
                  <div className={`max-w-[70%] px-4 py-3 ${m.role === 'user' ? 'hd-bubble-r' : 'hd-bubble-l'}`}
                    style={m.role === 'user'
                      ? { background: '#2d2926', color: '#fdf8f0', border: '2px solid #2d2926', boxShadow: '3px 3px 0 rgba(45,41,38,0.3)', fontSize: '13px', lineHeight: 1.6 }
                      : { background: '#fffef9', color: '#2d2926', border: '2px solid #2d2926', boxShadow: '3px 3px 0 rgba(45,41,38,0.15)', fontSize: '13px', lineHeight: 1.6 }}>
                    {m.role === 'assistant' ? <Markdown>{m.content}</Markdown> : <p className="whitespace-pre-wrap">{m.content}</p>}
                  </div>
                </motion.div>
              ))}
              {p.running && (
                <div className="flex items-center gap-1.5 pl-9">
                  {[0, 0.2, 0.4].map((d) => <span key={d} className="w-1.5 h-1.5 rounded-full" style={{ background: '#f4a261', animation: `blink 1.4s ${d}s infinite` }} />)}
                </div>
              )}
              {p.error && <div className="px-3 py-2 hd-soft" style={{ fontSize: '12px', color: '#e76f51', background: '#fff' }}>{p.error}</div>}
            </div>

            <div className="p-3" style={{ borderTop: '2px dashed rgba(45,41,38,0.15)' }}>
              <div className="flex items-end gap-2">
                <div className="flex-1 p-3" style={{ background: '#fffef9', borderRadius: '255px 15px 225px 15px/15px 225px 15px 255px', border: '2px solid #2d2926', boxShadow: '2px 2px 0 rgba(45,41,38,0.15)' }}>
                  <textarea value={p.input} onChange={(e) => p.setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); p.onSend(); } }}
                    placeholder="写下你的问题... ✏️" rows={1}
                    className="w-full bg-transparent outline-none resize-none placeholder:text-gray-400"
                    style={{ color: '#2d2926', fontSize: '13px', maxHeight: '80px', fontFamily: SKETCH }} disabled={p.running} />
                  <div className="flex items-center gap-1.5 mt-2 pt-2" style={{ borderTop: '1px dashed rgba(45,41,38,0.15)' }}>
                    <button onClick={p.onPickFolder} title="选择文件夹读取" style={{ display: 'flex' }}>
                      <Paperclip size={13} style={{ color: p.folders.length ? '#f4a261' : '#9ca3af' }} />
                    </button>
                    {p.folders.map((f) => (
                      <span key={f.id} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md" style={{ fontSize: '10px', color: '#6b7280', background: '#fff4e6', border: '1px solid #f4d3b0' }}>
                        <span className="truncate" style={{ maxWidth: '84px' }} title={f.path}>{f.path.split('/').filter(Boolean).pop() || f.path}</span>
                        <button onClick={() => p.onRemoveFolder(f.id)} className="opacity-60 hover:opacity-100"><X size={9} /></button>
                      </span>
                    ))}
                    <span style={{ fontSize: '11px', color: '#d1d5db', marginLeft: 'auto' }}>{p.input.length}/2000</span>
                  </div>
                </div>
                <motion.button whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }} onClick={p.running ? p.onStop : p.onSend} disabled={!p.running && !p.input.trim()} title={p.running ? '停止' : '发送'}
                  style={{ width: '44px', height: '44px', borderRadius: '255px 15px 225px 15px/15px 225px 15px 255px', background: p.running ? '#e76f51' : (p.input.trim() ? '#f4a261' : '#f0d9c4'), border: '2px solid #2d2926', boxShadow: '3px 3px 0 #2d2926', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0 }}>
                  {p.running ? <Square size={14} fill="#2d2926" style={{ color: '#2d2926' }} /> : <Send size={16} style={{ color: '#2d2926' }} />}
                </motion.button>
              </div>
            </div>
          </div>
        </motion.div>

        {/* 右：待办 */}
        <motion.div initial={{ x: 16, opacity: 0 }} animate={{ x: 0, opacity: 1 }} transition={{ delay: 0.1 }} className="w-56 flex flex-col gap-3 overflow-hidden flex-shrink-0">
          <div className="hd-card flex-1 flex flex-col overflow-hidden p-3">
            <div className="flex items-center justify-between mb-3">
              <p style={{ fontSize: '10px', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' }}>📋 待办事项</p>
              <span style={{ fontSize: '10px', color: '#9ca3af' }}>{pending} 未完成</span>
            </div>
            <div className="flex items-center gap-1.5 mb-3 p-2 hd-soft" style={{ background: '#fffef9' }}>
              <input type="text" value={p.newTodo} onChange={(e) => p.setNewTodo(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && p.onAddTodo()}
                placeholder="新增任务..." className="flex-1 bg-transparent outline-none" style={{ fontSize: '11px', color: '#2d2926', fontFamily: SKETCH }} />
              <button onClick={p.onAddTodo} style={{ color: '#f4a261', cursor: 'pointer', display: 'flex' }}><Plus size={14} /></button>
            </div>
            <div className="flex-1 overflow-y-auto space-y-1.5 no-scrollbar">
              {p.todos.length === 0 && <p style={{ fontSize: '11px', color: '#9ca3af', padding: '4px' }}>还没有待办，清清爽爽 ✨</p>}
              {p.todos.map((todo) => (
                <motion.div key={todo.id} layout initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }}
                  className="flex items-start gap-2 p-2 rounded-lg group hover:bg-black/5 transition-colors">
                  <button onClick={() => p.onToggleTodo(todo)} className="flex-shrink-0 mt-0.5" style={{ cursor: 'pointer' }}>
                    {todo.done ? <CheckCircle2 size={14} style={{ color: '#2a9d8f' }} /> : <Circle size={14} style={{ color: '#d1d5db' }} />}
                  </button>
                  <div className="flex-1 min-w-0">
                    <p style={{ fontSize: '11px', color: todo.done ? '#9ca3af' : '#2d2926', textDecoration: todo.done ? 'line-through' : 'none', lineHeight: 1.4, wordBreak: 'break-word' }}>{todo.text}</p>
                    {todo.due && <span style={{ fontSize: '9.5px', color: '#9ca3af' }}>· {todo.due}</span>}
                  </div>
                  <button onClick={() => p.onDeleteTodo(todo.id)} className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" style={{ cursor: 'pointer', color: '#d1d5db' }}>
                    <Trash2 size={11} />
                  </button>
                </motion.div>
              ))}
            </div>
            <div style={{ borderTop: '1px dashed rgba(45,41,38,0.15)', paddingTop: '8px', marginTop: '8px' }}>
              <div className="flex justify-between mb-1">
                <span style={{ fontSize: '10px', color: '#9ca3af' }}>今日进度</span>
                <span style={{ fontSize: '10px', color: '#2a9d8f' }}>{progress}%</span>
              </div>
              <div className="w-full h-2" style={{ background: '#e5e7eb', borderRadius: '99px', border: '1.5px solid #2d2926', overflow: 'hidden' }}>
                <motion.div animate={{ width: `${progress}%` }} transition={{ type: 'spring', stiffness: 100 }} style={{ height: '100%', background: '#2a9d8f', borderRadius: '99px' }} />
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
