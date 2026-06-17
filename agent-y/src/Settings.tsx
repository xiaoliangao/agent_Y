import React, { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { X, Plus, Check, Trash2, KeyRound, User, Sparkles } from 'lucide-react';
import {
  listProviders, addProvider, activateProvider, deleteProvider,
  listModels, getSettings, putSettings,
  type Connection, type ModelInfo, type Settings,
} from './api';

const APPROVALS = [
  { v: 'read_only', label: '只读' },
  { v: 'ask', label: '问一下（默认）' },
  { v: 'auto', label: '自动' },
  { v: 'full', label: '完全放开' },
];

export default function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'provider' | 'persona'>('provider');
  const [conns, setConns] = useState<Connection[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [suggestion, setSuggestion] = useState('');
  const [np, setNp] = useState({ provider: 'anthropic', api_key: '', base_url: '', model_default: '' });
  const [saving, setSaving] = useState(false);

  const reloadConns = () => listProviders().then(setConns);
  useEffect(() => {
    reloadConns();
    listModels().then(setModels);
    getSettings().then((d) => { setSettings(d.settings); setSuggestion(d.persona_suggestion); });
  }, []);

  const submitConn = async () => {
    if (!np.api_key.trim()) return;
    setSaving(true);
    try {
      await addProvider({ provider: np.provider, api_key: np.api_key,
        base_url: np.base_url || undefined, model_default: np.model_default || undefined });
      setNp({ provider: 'anthropic', api_key: '', base_url: '', model_default: '' });
      reloadConns();
    } finally { setSaving(false); }
  };
  const save = async (patch: Partial<Settings>) => setSettings((await putSettings(patch)).settings);

  const provModels = models.filter((m) => m.provider === np.provider);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-[120] flex items-center justify-center px-4"
      style={{ background: 'rgba(6,6,8,0.6)', backdropFilter: 'blur(6px)' }} onClick={onClose}>
      <motion.div initial={{ opacity: 0, scale: 0.98, y: 12 }} animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.98, y: 12 }} transition={{ type: 'spring', bounce: 0, duration: 0.4 }}
        onClick={(e) => e.stopPropagation()}
        className="card w-full max-w-2xl max-h-[86vh] flex flex-col overflow-hidden"
        style={{ boxShadow: '0 30px 80px rgba(0,0,0,0.5)' }}>
        {/* header */}
        <div className="flex items-center justify-between px-6 h-16 border-b" style={{ borderColor: 'var(--color-line)' }}>
          <div className="flex items-center gap-3">
            <span className="font-serif text-2xl tracking-tight">设置</span>
            <div className="flex gap-1 ml-2">
              {(['provider', 'persona'] as const).map((t) => (
                <button key={t} onClick={() => setTab(t)}
                  className="px-3 py-1.5 rounded-lg text-[13px] font-medium transition-colors"
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
              <div>
                <div className="label mb-3">已连接（key 存于系统钥匙串，不入库）</div>
                <div className="space-y-2">
                  {conns.length === 0 && <div className="text-[13px]" style={{ color: 'var(--color-ink-3)' }}>还没有连接，下面添加一个。</div>}
                  {conns.map((c) => (
                    <div key={c.id} className="flex items-center gap-3 px-3.5 py-3 rounded-xl"
                      style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-line)' }}>
                      <KeyRound className="w-4 h-4" style={{ color: c.active ? 'var(--color-gold)' : 'var(--color-ink-3)' }} />
                      <div className="min-w-0 flex-1">
                        <div className="text-[13.5px] font-medium">{c.provider}{c.model_default ? ` · ${c.model_default}` : ''}</div>
                        {c.base_url && <div className="text-[11px] font-mono truncate" style={{ color: 'var(--color-ink-3)' }}>{c.base_url}</div>}
                      </div>
                      {c.active
                        ? <span className="text-[11px] font-semibold flex items-center gap-1" style={{ color: 'var(--color-gold)' }}><Check className="w-3.5 h-3.5" />使用中</span>
                        : <button onClick={() => activateProvider(c.id).then(reloadConns)} className="btn btn-ghost text-[12px] px-2 py-1">设为默认</button>}
                      <button onClick={() => deleteProvider(c.id).then(reloadConns)} className="btn btn-ghost p-1.5"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card p-4" style={{ background: 'var(--color-elevated)' }}>
                <div className="label mb-3">添加连接</div>
                <div className="grid grid-cols-2 gap-3">
                  <select className="field" value={np.provider} onChange={(e) => setNp({ ...np, provider: e.target.value, model_default: '' })}>
                    <option value="anthropic">Anthropic（Claude 原生）</option>
                    <option value="openai">OpenAI 兼容（DeepSeek/GPT/本地…）</option>
                  </select>
                  <select className="field" value={np.model_default} onChange={(e) => setNp({ ...np, model_default: e.target.value })}>
                    <option value="">默认模型（可选）</option>
                    {provModels.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                  </select>
                  <input className="field col-span-2" type="password" placeholder="API key" value={np.api_key}
                    onChange={(e) => setNp({ ...np, api_key: e.target.value })} />
                  {np.provider === 'openai' && (
                    <input className="field col-span-2" placeholder="base_url（如 https://api.deepseek.com）" value={np.base_url}
                      onChange={(e) => setNp({ ...np, base_url: e.target.value })} />
                  )}
                </div>
                <button onClick={submitConn} disabled={saving || !np.api_key.trim()} className="btn btn-gold mt-3 w-full">
                  <Plus className="w-4 h-4" /> 保存连接
                </button>
              </div>
            </div>
          )}

          {tab === 'persona' && settings && (
            <div className="space-y-6">
              <div>
                <div className="label mb-2 flex items-center gap-2"><User className="w-3.5 h-3.5" /> Agent 名字</div>
                <input className="field" value={settings.agent_name}
                  onChange={(e) => setSettings({ ...settings, agent_name: e.target.value })}
                  onBlur={(e) => save({ agent_name: e.target.value })} />
              </div>
              <div>
                <div className="label mb-2 flex items-center justify-between">
                  <span className="flex items-center gap-2"><Sparkles className="w-3.5 h-3.5" /> 角色 / 人设提示词</span>
                  <button className="btn btn-ghost text-[11px] px-2 py-1" onClick={() => { setSettings({ ...settings, persona: suggestion }); save({ persona: suggestion }); }}>载入推荐</button>
                </div>
                <textarea className="field font-sans leading-relaxed" rows={10} placeholder="留空则用场景默认。这里定义助手的身份、语气、行为边界（参考 docs/CLAUDE-FABLE-5）。"
                  value={settings.persona}
                  onChange={(e) => setSettings({ ...settings, persona: e.target.value })}
                  onBlur={(e) => save({ persona: e.target.value })} />
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
