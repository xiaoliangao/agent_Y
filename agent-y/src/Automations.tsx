import React, { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { X, Plus, Play, Trash2, Check, Loader2, Clock, Inbox } from 'lucide-react';
import {
  listAutomations, addAutomation, patchAutomation, deleteAutomation, runAutomation,
  listReviews, decideReview, type Automation, type Review,
} from './api';

export default function AutomationsPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'autos' | 'review'>('autos');
  const [autos, setAutos] = useState<Automation[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [na, setNa] = useState({ name: '', schedule: 'daily@09:00', prompt: '' });
  const [busy, setBusy] = useState<string | null>(null);

  const reload = () => { listAutomations().then(setAutos); listReviews('pending').then(setReviews); };
  useEffect(reload, []);

  const create = async () => {
    if (!na.name.trim() || !na.prompt.trim()) return;
    await addAutomation(na);
    setNa({ name: '', schedule: 'daily@09:00', prompt: '' });
    reload();
  };
  const runNow = async (id: string) => { setBusy(id); try { await runAutomation(id); reload(); } finally { setBusy(null); } };
  const decide = async (id: string, d: 'accept' | 'discard') => { await decideReview(id, d); reload(); };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-[120] flex items-center justify-center px-4"
      style={{ background: 'rgba(43,42,39,0.42)' }} onClick={onClose}>
      <motion.div initial={{ opacity: 0, scale: 0.985, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.985, y: 10 }}
        transition={{ type: 'spring', bounce: 0, duration: 0.38 }} onClick={(e) => e.stopPropagation()}
        className="card w-full max-w-2xl max-h-[88vh] flex flex-col overflow-hidden" style={{ boxShadow: '0 40px 90px rgba(60,40,30,0.24)' }}>
        <div className="flex items-center justify-between px-6 h-16 shrink-0" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <div className="flex items-center gap-3">
            <span className="font-serif text-2xl tracking-tight">自动化</span>
            <div className="flex gap-1 ml-1">
              <button onClick={() => setTab('autos')} className="px-3 py-1.5 rounded-lg text-[13px] font-medium transition-colors"
                style={tab === 'autos' ? { background: 'var(--color-elevated)', color: 'var(--color-ink)' } : { color: 'var(--color-ink-3)' }}>定时任务</button>
              <button onClick={() => setTab('review')} className="px-3 py-1.5 rounded-lg text-[13px] font-medium transition-colors flex items-center gap-1.5"
                style={tab === 'review' ? { background: 'var(--color-elevated)', color: 'var(--color-ink)' } : { color: 'var(--color-ink-3)' }}>
                待审 {reviews.length > 0 && <span className="px-1.5 rounded-full text-[10px]" style={{ background: 'var(--color-gold)', color: '#fff7f1' }}>{reviews.length}</span>}
              </button>
            </div>
          </div>
          <button onClick={onClose} className="btn btn-ghost p-2"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-7 no-scrollbar">
          {tab === 'autos' && (
            <div className="space-y-7">
              {autos.length > 0 && (
                <div className="space-y-2">
                  {autos.map((a) => (
                    <div key={a.id} className="flex items-center gap-3 px-4 py-3 rounded-xl" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-line)' }}>
                      <Clock className="w-4 h-4 shrink-0" style={{ color: a.enabled ? 'var(--color-gold)' : 'var(--color-ink-3)' }} />
                      <div className="min-w-0 flex-1">
                        <div className="text-[13.5px] font-medium">{a.name}</div>
                        <div className="text-[11px] font-mono truncate" style={{ color: 'var(--color-ink-3)' }}>{a.schedule} · {a.scenario}{a.last_run ? ` · 上次 ${a.last_run.slice(5, 16).replace('T', ' ')}` : ''}</div>
                      </div>
                      <button onClick={() => patchAutomation(a.id, { enabled: !a.enabled }).then(reload)} className="btn btn-ghost text-[12px] px-2 py-1">{a.enabled ? '已启用' : '已停用'}</button>
                      <button onClick={() => runNow(a.id)} className="btn btn-ghost p-1.5" title="立即运行">{busy === a.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}</button>
                      <button onClick={() => deleteAutomation(a.id).then(reload)} className="btn btn-ghost p-1.5"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  ))}
                </div>
              )}
              <div className="card p-4" style={{ background: 'var(--color-elevated)' }}>
                <div className="label mb-3">新建自动化</div>
                <div className="space-y-2.5">
                  <input className="field" placeholder="名字，如 每日新闻简报" value={na.name} onChange={(e) => setNa({ ...na, name: e.target.value })} />
                  <div>
                    <input className="field font-mono text-[12.5px]" placeholder="daily@09:00 / 30m / 2h" value={na.schedule} onChange={(e) => setNa({ ...na, schedule: e.target.value })} />
                    <div className="text-[11px] mt-1" style={{ color: 'var(--color-ink-3)' }}>每天某点 daily@HH:MM，或每 N 分钟 Nm / N 小时 Nh</div>
                  </div>
                  <textarea className="field leading-relaxed" rows={3} placeholder="让助手做什么（如：搜一下今天的 AI 新闻，挑 3 条总结）" value={na.prompt} onChange={(e) => setNa({ ...na, prompt: e.target.value })} />
                </div>
                <button onClick={create} disabled={!na.name.trim() || !na.prompt.trim()} className="btn btn-gold mt-3 w-full"><Plus className="w-4 h-4" /> 创建</button>
              </div>
            </div>
          )}

          {tab === 'review' && (
            <div className="space-y-3">
              {reviews.length === 0 && (
                <div className="flex flex-col items-center text-center py-16" style={{ color: 'var(--color-ink-3)' }}>
                  <Inbox className="w-7 h-7 mb-3" /> <div className="text-[13px]">待审队列空。自动化跑完的产出会出现在这里等你收口。</div>
                </div>
              )}
              {reviews.map((r) => (
                <div key={r.id} className="rounded-xl overflow-hidden" style={{ border: '1px solid var(--color-line)' }}>
                  <div className="px-4 py-2.5 flex items-center justify-between" style={{ background: 'var(--color-elevated)' }}>
                    <span className="text-[13px] font-medium">{r.title}</span>
                    <span className="text-[11px] font-mono" style={{ color: 'var(--color-ink-3)' }}>{r.created_at.slice(5, 16).replace('T', ' ')}</span>
                  </div>
                  <div className="px-4 py-3 text-[13px] leading-relaxed whitespace-pre-wrap max-h-52 overflow-y-auto no-scrollbar" style={{ background: 'var(--color-panel)' }}>{r.output}</div>
                  <div className="px-4 py-2.5 flex justify-end gap-2" style={{ background: 'var(--color-elevated)', borderTop: '1px solid var(--color-line)' }}>
                    <button onClick={() => decide(r.id, 'discard')} className="btn btn-ghost text-[12px]">丢弃</button>
                    <button onClick={() => decide(r.id, 'accept')} className="btn btn-gold text-[12px] px-3 py-1.5"><Check className="w-3.5 h-3.5" /> 采纳</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}
