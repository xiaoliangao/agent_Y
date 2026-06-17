import React, { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { X, Plus, Check, Trash2, User, Sparkles, Zap, Loader2, AlertCircle } from 'lucide-react';
import {
  listProviders, addProvider, activateProvider, deleteProvider, testProvider,
  listModels, getSettings, putSettings,
  type Connection, type ModelInfo, type Settings,
} from './api';

// ccswitch 式预设：点一下填好 provider + base_url，只需再填 key
const PRESETS = [
  { name: 'Claude 官方', provider: 'anthropic', base_url: '' },
  { name: 'DeepSeek', provider: 'openai', base_url: 'https://api.deepseek.com' },
  { name: 'Kimi', provider: 'openai', base_url: 'https://api.moonshot.cn/v1' },
  { name: '智谱 GLM', provider: 'openai', base_url: 'https://open.bigmodel.cn/api/paas/v4' },
  { name: 'OpenAI', provider: 'openai', base_url: 'https://api.openai.com/v1' },
  { name: '本地 Ollama', provider: 'openai', base_url: 'http://localhost:11434/v1' },
  { name: '自定义', provider: 'openai', base_url: '' },
];
const APPROVALS = [
  { v: 'read_only', label: '只读' }, { v: 'ask', label: '问一下（默认）' },
  { v: 'auto', label: '自动' }, { v: 'full', label: '完全放开' },
];
type TestState = 'loading' | { ok: boolean; latency_ms?: number; error?: string };

export default function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'provider' | 'persona'>('provider');
  const [conns, setConns] = useState<Connection[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [suggestion, setSuggestion] = useState('');
  const [preset, setPreset] = useState(0);
  const [np, setNp] = useState({ api_key: '', base_url: '', model_default: '' });
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [saving, setSaving] = useState(false);

  const reloadConns = () => listProviders().then(setConns);
  useEffect(() => {
    reloadConns();
    listModels().then(setModels);
    getSettings().then((d) => { setSettings(d.settings); setSuggestion(d.persona_suggestion); });
  }, []);

  const cur = PRESETS[preset];
  const provModels = models.filter((m) => m.provider === cur.provider);

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
    try {
      const r = await testProvider(id);
      setTests((t) => ({ ...t, [id]: r }));
    } catch (e) {
      setTests((t) => ({ ...t, [id]: { ok: false, error: String(e) } }));
    }
  };
  const save = async (patch: Partial<Settings>) => setSettings((await putSettings(patch)).settings);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-[120] flex items-center justify-center px-4"
      style={{ background: 'rgba(6,6,8,0.62)', backdropFilter: 'blur(7px)' }} onClick={onClose}>
      <motion.div initial={{ opacity: 0, scale: 0.98, y: 12 }} animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.98, y: 12 }} transition={{ type: 'spring', bounce: 0, duration: 0.4 }}
        onClick={(e) => e.stopPropagation()} className="card w-full max-w-2xl max-h-[88vh] flex flex-col overflow-hidden"
        style={{ boxShadow: '0 40px 90px rgba(0,0,0,0.55)' }}>
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

        <div className="flex-1 overflow-y-auto p-6 no-scrollbar">
          {tab === 'provider' && (
            <div className="space-y-6">
              {conns.length > 0 && (
                <div>
                  <div className="label mb-3">已保存的连接 · 点卡片即切换（key 存系统钥匙串）</div>
                  <div className="space-y-2">
                    {conns.map((c) => {
                      const tr = tests[c.id];
                      return (
                        <div key={c.id} onClick={() => !c.active && activateProvider(c.id).then(reloadConns)}
                          className="flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer transition-all"
                          style={{ background: 'var(--color-elevated)', border: `1px solid ${c.active ? 'var(--color-gold)' : 'var(--color-line)'}` }}>
                          <div className="w-2 h-2 rounded-full shrink-0" style={{ background: c.active ? 'var(--color-gold)' : 'var(--color-line-2)', boxShadow: c.active ? '0 0 10px var(--color-gold)' : 'none' }} />
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
                    <button key={p.name} onClick={() => { setPreset(i); setNp({ ...np, base_url: p.base_url, model_default: '' }); }}
                      className="px-3 py-1.5 rounded-lg text-[12.5px] font-medium transition-all"
                      style={preset === i ? { background: 'var(--color-gold)', color: '#1a1408' } : { background: 'var(--color-bg)', color: 'var(--color-ink-2)', border: '1px solid var(--color-line)' }}>
                      {p.name}
                    </button>
                  ))}
                </div>
                <div className="space-y-2.5">
                  <input className="field" type="password" placeholder="API key" value={np.api_key} onChange={(e) => setNp({ ...np, api_key: e.target.value })} />
                  {cur.provider === 'openai' && (
                    <input className="field" placeholder="base_url" value={np.base_url || cur.base_url} onChange={(e) => setNp({ ...np, base_url: e.target.value })} />
                  )}
                  <select className="field" value={np.model_default} onChange={(e) => setNp({ ...np, model_default: e.target.value })}>
                    <option value="">默认模型（可选）</option>
                    {provModels.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                  </select>
                </div>
                <button onClick={submit} disabled={saving || !np.api_key.trim()} className="btn btn-gold mt-3 w-full"><Plus className="w-4 h-4" /> 保存连接</button>
              </div>
            </div>
          )}

          {tab === 'persona' && settings && (
            <div className="space-y-6">
              <div>
                <div className="label mb-2 flex items-center gap-2"><User className="w-3.5 h-3.5" /> Agent 名字</div>
                <input className="field" value={settings.agent_name} onChange={(e) => setSettings({ ...settings, agent_name: e.target.value })} onBlur={(e) => save({ agent_name: e.target.value })} />
              </div>
              <div>
                <div className="label mb-2 flex items-center justify-between">
                  <span className="flex items-center gap-2"><Sparkles className="w-3.5 h-3.5" /> 角色 / 人设提示词</span>
                  <button className="btn btn-ghost text-[11px] px-2 py-1" onClick={() => { setSettings({ ...settings, persona: suggestion }); save({ persona: suggestion }); }}>载入推荐</button>
                </div>
                <textarea className="field leading-relaxed" rows={10} placeholder="留空则用场景默认。这里定义助手的身份、语气、行为边界（参考 docs/CLAUDE-FABLE-5）。"
                  value={settings.persona} onChange={(e) => setSettings({ ...settings, persona: e.target.value })} onBlur={(e) => save({ persona: e.target.value })} />
                <div className="text-[11px] mt-1.5" style={{ color: 'var(--color-ink-3)' }}>失焦自动保存。会拼在场景提示词之前，决定 Agent 的身份与语气。</div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="label mb-2">默认模型</div>
                  <select className="field" value={settings.default_model || ''} onChange={(e) => save({ default_model: e.target.value })}>
                    <option value="">跟随连接</option>
                    {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                  </select>
                </div>
                <div>
                  <div className="label mb-2">审批模式</div>
                  <select className="field" value={settings.approval_mode || 'ask'} onChange={(e) => save({ approval_mode: e.target.value })}>
                    {APPROVALS.map((a) => <option key={a.v} value={a.v}>{a.label}</option>)}
                  </select>
                </div>
              </div>
            </div>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}
