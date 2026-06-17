import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'motion/react';
import { X, Plus, Check, Trash2, User, Sparkles, Zap, Loader2, AlertCircle, ChevronDown } from 'lucide-react';
import {
  listProviders, addProvider, activateProvider, deleteProvider, testProvider,
  getSettings, putSettings, type Connection, type Settings,
} from './api';

const PRESETS = [
  { name: 'Claude 官方', provider: 'anthropic', base_url: '', eg: 'claude-sonnet-4-6' },
  { name: 'DeepSeek', provider: 'openai', base_url: 'https://api.deepseek.com', eg: 'deepseek-chat' },
  { name: 'Kimi', provider: 'openai', base_url: 'https://api.moonshot.cn/v1', eg: 'moonshot-v1-8k' },
  { name: '智谱 GLM', provider: 'openai', base_url: 'https://open.bigmodel.cn/api/paas/v4', eg: 'glm-4-plus' },
  { name: 'OpenAI', provider: 'openai', base_url: 'https://api.openai.com/v1', eg: 'gpt-4o' },
  { name: '本地 Ollama', provider: 'openai', base_url: 'http://localhost:11434/v1', eg: 'qwen2.5' },
  { name: '自定义', provider: 'openai', base_url: '', eg: '模型 id' },
];
const APPROVALS = [
  { v: 'read_only', label: '只读（不许改任何东西）' }, { v: 'ask', label: '问一下（越权才停下确认）' },
  { v: 'auto', label: '自动（不打断）' }, { v: 'full', label: '完全放开（仅可信环境）' },
];
type TestState = 'loading' | { ok: boolean; latency_ms?: number; error?: string };

// 弹层用 createPortal 挂到 body，避开设置弹窗 overflow 的裁剪
function Dropdown({ value, options, onChange }: { value: string; options: { v: string; label: string }[]; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<{ left: number; top: number; width: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const cur = options.find((o) => o.v === value);
  const toggle = () => {
    if (!open && btn.current) {
      const r = btn.current.getBoundingClientRect();
      const h = options.length * 42 + 12;               // 估算弹层高度
      const up = window.innerHeight - r.bottom < h + 16 && r.top > h + 16;  // 下方不够 → 向上翻
      setRect({ left: r.left, top: up ? r.top - h - 6 : r.bottom + 6, width: r.width });
    }
    setOpen(!open);
  };
  return (
    <>
      <button ref={btn} type="button" onClick={toggle} className="field flex items-center justify-between text-left">
        <span>{cur?.label ?? value}</span>
        <ChevronDown className="w-4 h-4 transition-transform" style={{ color: 'var(--color-ink-3)', transform: open ? 'rotate(180deg)' : 'none' }} />
      </button>
      {open && rect && createPortal(
        <>
          <div className="fixed inset-0 z-[200]" onClick={() => setOpen(false)} />
          <div className="fixed z-[201] rounded-xl overflow-hidden py-1 rise"
            style={{ left: rect.left, top: rect.top, width: rect.width, background: 'var(--color-panel)', border: '1px solid var(--color-line-2)', boxShadow: '0 16px 36px rgba(60,40,30,0.2)' }}>
            {options.map((o) => (
              <button key={o.v} type="button" onClick={() => { onChange(o.v); setOpen(false); }}
                className="w-full text-left px-3.5 py-2.5 text-[13.5px] flex items-center justify-between transition-colors"
                style={o.v === value ? { background: 'rgba(192,106,77,0.1)', color: 'var(--color-gold)' } : { color: 'var(--color-ink-2)' }}
                onMouseEnter={(e) => { if (o.v !== value) e.currentTarget.style.background = 'rgba(43,42,39,0.04)'; }}
                onMouseLeave={(e) => { if (o.v !== value) e.currentTarget.style.background = 'transparent'; }}>
                {o.label} {o.v === value && <Check className="w-3.5 h-3.5 shrink-0" />}
              </button>
            ))}
          </div>
        </>, document.body)}
    </>
  );
}

export default function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'provider' | 'persona'>('provider');
  const [conns, setConns] = useState<Connection[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [suggestion, setSuggestion] = useState('');
  const [preset, setPreset] = useState(0);
  const [np, setNp] = useState({ api_key: '', base_url: '', model_default: '' });
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [saving, setSaving] = useState(false);

  const reloadConns = () => listProviders().then(setConns);
  useEffect(() => {
    reloadConns();
    getSettings().then((d) => { setSettings(d.settings); setSuggestion(d.persona_suggestion); });
  }, []);

  const cur = PRESETS[preset];
  const pickPreset = (i: number) => { setPreset(i); setNp({ ...np, base_url: PRESETS[i].base_url }); };

  const submit = async () => {
    if (!np.api_key.trim()) return;
    setSaving(true);
    try {
      await addProvider({
        provider: cur.provider, api_key: np.api_key,
        base_url: (np.base_url || cur.base_url) || undefined, model_default: np.model_default || undefined,
      });
      setNp({ api_key: '', base_url: '', model_default: '' });
      reloadConns();
    } finally { setSaving(false); }
  };
  const test = async (id: string) => {
    setTests((t) => ({ ...t, [id]: 'loading' }));
    try { const r = await testProvider(id); setTests((t) => ({ ...t, [id]: r })); }
    catch (e) { setTests((t) => ({ ...t, [id]: { ok: false, error: String(e) } })); }
  };
  const save = async (patch: Partial<Settings>) => setSettings((await putSettings(patch)).settings);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-[120] flex items-center justify-center px-4"
      style={{ background: 'rgba(43,42,39,0.42)' }} onClick={onClose}>
      <motion.div initial={{ opacity: 0, scale: 0.985, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.985, y: 10 }} transition={{ type: 'spring', bounce: 0, duration: 0.38 }}
        onClick={(e) => e.stopPropagation()} className="card w-full max-w-2xl max-h-[88vh] flex flex-col overflow-hidden"
        style={{ boxShadow: '0 40px 90px rgba(60,40,30,0.24)' }}>
        <div className="flex items-center justify-between px-6 h-16 shrink-0" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <div className="flex items-center gap-3">
            <span className="font-serif text-2xl tracking-tight">设置</span>
            <div className="flex gap-1 ml-1">
              {(['provider', 'persona'] as const).map((t) => (
                <button key={t} onClick={() => setTab(t)} className="px-3 py-1.5 rounded-lg text-[13px] font-medium transition-colors"
                  style={tab === t ? { background: 'var(--color-elevated)', color: 'var(--color-ink)' } : { color: 'var(--color-ink-3)' }}>
                  {t === 'provider' ? '模型连接' : '人设与偏好'}
                </button>
              ))}
            </div>
          </div>
          <button onClick={onClose} className="btn btn-ghost p-2"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-7 no-scrollbar">
          {tab === 'provider' && (
            <div className="space-y-7">
              {conns.length > 0 && (
                <div>
                  <div className="label mb-3">已保存的连接 · 点卡片即切换（key 存系统钥匙串，不入库）</div>
                  <div className="space-y-2">
                    {conns.map((c) => {
                      const tr = tests[c.id];
                      return (
                        <div key={c.id} onClick={() => !c.active && activateProvider(c.id).then(reloadConns)}
                          className="flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer transition-all"
                          style={{ background: c.active ? 'rgba(192,106,77,0.07)' : 'var(--color-panel)', border: `1px solid ${c.active ? 'var(--color-gold)' : 'var(--color-line)'}` }}>
                          <div className="w-2 h-2 rounded-full shrink-0" style={{ background: c.active ? 'var(--color-gold)' : 'var(--color-line-2)', boxShadow: c.active ? '0 0 9px var(--color-gold)' : 'none' }} />
                          <div className="min-w-0 flex-1">
                            <div className="text-[13.5px] font-medium">{c.provider}{c.model_default ? ` · ${c.model_default}` : ''}</div>
                            {c.base_url && <div className="text-[11px] font-mono truncate" style={{ color: 'var(--color-ink-3)' }}>{c.base_url}</div>}
                          </div>
                          {tr === 'loading' ? <Loader2 className="w-4 h-4 animate-spin" style={{ color: 'var(--color-ink-3)' }} />
                            : tr ? <span className="text-[11px] font-mono flex items-center gap-1" style={{ color: tr.ok ? 'var(--color-ok)' : 'var(--color-danger)' }}>
                                {tr.ok ? <><Check className="w-3 h-3" />{tr.latency_ms}ms</> : <><AlertCircle className="w-3 h-3" />失败</>}</span>
                            : null}
                          <button onClick={(e) => { e.stopPropagation(); test(c.id); }} className="btn btn-ghost text-[12px] px-2 py-1"><Zap className="w-3.5 h-3.5" />测连接</button>
                          {c.active && <span className="text-[11px] font-semibold" style={{ color: 'var(--color-gold)' }}>使用中</span>}
                          <button onClick={(e) => { e.stopPropagation(); deleteProvider(c.id).then(reloadConns); }} className="btn btn-ghost p-1.5"><Trash2 className="w-3.5 h-3.5" /></button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="card p-4" style={{ background: 'var(--color-elevated)' }}>
                <div className="label mb-3">添加连接</div>
                <div className="flex flex-wrap gap-1.5 mb-4">
                  {PRESETS.map((p, i) => (
                    <button key={p.name} onClick={() => pickPreset(i)} className="px-3 py-1.5 rounded-lg text-[12.5px] font-medium transition-all"
                      style={preset === i ? { background: 'var(--color-gold)', color: '#fff7f1' } : { background: 'var(--color-panel)', color: 'var(--color-ink-2)', border: '1px solid var(--color-line)' }}>
                      {p.name}
                    </button>
                  ))}
                </div>
                <div className="space-y-2.5">
                  <div>
                    <div className="label mb-1.5">API key</div>
                    <input className="field" type="password" placeholder="sk-..." value={np.api_key} onChange={(e) => setNp({ ...np, api_key: e.target.value })} />
                  </div>
                  <div>
                    <div className="label mb-1.5">Base URL{cur.provider === 'anthropic' ? '（Claude 官方可留空）' : ''}</div>
                    <input className="field font-mono text-[12.5px]" placeholder={cur.base_url || 'https://...'} value={np.base_url} onChange={(e) => setNp({ ...np, base_url: e.target.value })} />
                  </div>
                  <div>
                    <div className="label mb-1.5">模型 id</div>
                    <input className="field font-mono text-[12.5px]" placeholder={`如 ${cur.eg}`} value={np.model_default} onChange={(e) => setNp({ ...np, model_default: e.target.value })} />
                  </div>
                </div>
                <button onClick={submit} disabled={saving || !np.api_key.trim()} className="btn btn-gold mt-3.5 w-full"><Plus className="w-4 h-4" /> 保存连接</button>
              </div>
            </div>
          )}

          {tab === 'persona' && settings && (
            <div className="space-y-7">
              <div>
                <div className="label mb-2 flex items-center gap-2"><User className="w-3.5 h-3.5" /> Agent 名字</div>
                <input className="field" value={settings.agent_name} onChange={(e) => setSettings({ ...settings, agent_name: e.target.value })} onBlur={(e) => save({ agent_name: e.target.value })} />
              </div>
              <div>
                <div className="label mb-2 flex items-center justify-between">
                  <span className="flex items-center gap-2"><Sparkles className="w-3.5 h-3.5" /> 角色 / 人设</span>
                  <button className="btn btn-ghost text-[11px] px-2 py-1" onClick={() => { setSettings({ ...settings, persona: suggestion }); save({ persona: suggestion }); }}>载入推荐</button>
                </div>
                <textarea className="field leading-relaxed" rows={8}
                  placeholder="例：你是我的产品经理搭档，说话直接、先问清楚再动手，回答简短不啰嗦。"
                  value={settings.persona} onChange={(e) => setSettings({ ...settings, persona: e.target.value })} onBlur={(e) => save({ persona: e.target.value })} />
                <div className="text-[11.5px] mt-2 leading-relaxed" style={{ color: 'var(--color-ink-3)' }}>
                  这段会拼在每次对话最前面，决定助手的身份、语气和边界。留空用默认助手；点右上「载入推荐」可填一份模板再改。失焦自动保存。
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="label mb-2">默认模型 id（可选，覆盖连接）</div>
                  <input className="field font-mono text-[12.5px]" placeholder="留空跟随连接" value={settings.default_model}
                    onChange={(e) => setSettings({ ...settings, default_model: e.target.value })} onBlur={(e) => save({ default_model: e.target.value })} />
                </div>
                <div>
                  <div className="label mb-2">审批模式</div>
                  <Dropdown value={settings.approval_mode || 'ask'} options={APPROVALS} onChange={(v) => save({ approval_mode: v })} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="label mb-2">代码沙箱</div>
                  <Dropdown value={settings.sandbox || 'local'} options={[{ v: 'local', label: '本机（开发友好）' }, { v: 'docker', label: 'Docker（隔离，需装 Docker）' }]} onChange={(v) => save({ sandbox: v })} />
                </div>
              </div>
            </div>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}
