import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { X, Plus, Trash2, Sparkles, BookOpen } from 'lucide-react';
import { listSkills, addSkill, deleteSkill, type SkillMeta } from './api';

const EMPTY = { name: '', description: '', when_to_use: '', body: '' };

// 技能：保存一段「做某类事的步骤说明」，平时只把名字+简介给到 agent；
// 任务相关时它会用 use_skill 自动把完整正文拉进上下文照做（渐进披露）。
export default function SkillsPanel({ onClose }: { onClose: () => void }) {
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const reload = () => listSkills().then(setSkills).catch(() => {});
  useEffect(() => { reload(); }, []);

  const save = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try { await addSkill(form); setForm(EMPTY); reload(); }
    finally { setSaving(false); }
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-[120] flex items-center justify-center px-4" style={{ background: 'rgba(43,42,39,0.42)' }} onClick={onClose}>
      <motion.div initial={{ opacity: 0, scale: 0.985, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.985, y: 10 }}
        transition={{ type: 'spring', bounce: 0, duration: 0.38 }} onClick={(e) => e.stopPropagation()}
        className="card w-full max-w-2xl max-h-[88vh] flex flex-col overflow-hidden" style={{ boxShadow: '0 40px 90px rgba(60,40,30,0.24)' }}>
        <div className="flex items-center justify-between px-6 h-16 shrink-0" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <div className="flex items-center gap-2.5">
            <Sparkles className="w-5 h-5" style={{ color: 'var(--color-gold)' }} />
            <span className="font-serif text-2xl tracking-tight">技能</span>
          </div>
          <button onClick={onClose} className="btn btn-ghost p-2"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-7 no-scrollbar space-y-6">
          <p className="text-[12.5px] leading-relaxed" style={{ color: 'var(--color-ink-3)' }}>
            技能 = 一段可复用的「做某类事的步骤」。平时只有名字和简介进入助手上下文（省 token）；当任务相关，它会自动加载正文照着做（渐进披露，类似 Codex skills）。
          </p>

          {skills.length > 0 && (
            <div className="space-y-2">
              <div className="label">已保存技能</div>
              {skills.map((s) => (
                <div key={s.name} className="flex items-start gap-3 px-4 py-3 rounded-xl" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-line)' }}>
                  <BookOpen className="w-4 h-4 mt-0.5 shrink-0" style={{ color: 'var(--color-gold)' }} />
                  <div className="min-w-0 flex-1">
                    <div className="text-[13.5px] font-medium">{s.name}</div>
                    {s.description && <div className="text-[12px] mt-0.5" style={{ color: 'var(--color-ink-2)' }}>{s.description}</div>}
                    {s.when_to_use && <div className="text-[11px] mt-0.5" style={{ color: 'var(--color-ink-3)' }}>何时用：{s.when_to_use}</div>}
                  </div>
                  <button onClick={() => deleteSkill(s.name).then(reload)} className="btn btn-ghost p-1.5 shrink-0"><Trash2 className="w-3.5 h-3.5" /></button>
                </div>
              ))}
            </div>
          )}

          <div className="card p-4" style={{ background: 'var(--color-elevated)' }}>
            <div className="label mb-3">导入技能</div>
            <div className="space-y-2.5">
              <div>
                <div className="label mb-1.5">名字</div>
                <input className="field" placeholder="如 周报撰写 / PDF 提取" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div>
                <div className="label mb-1.5">简介（一句话，会进上下文目录）</div>
                <input className="field" placeholder="这个技能是做什么的" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </div>
              <div>
                <div className="label mb-1.5">何时用（可选）</div>
                <input className="field" placeholder="什么场景下该用它" value={form.when_to_use} onChange={(e) => setForm({ ...form, when_to_use: e.target.value })} />
              </div>
              <div>
                <div className="label mb-1.5">正文（完整步骤 / 注意事项 / 惯例，命中才加载）</div>
                <textarea className="field leading-relaxed" rows={6} placeholder={'例：\n1. 先读最近一周的提交/笔记\n2. 按「完成 / 进行中 / 下周计划」三段写\n3. 控制在 200 字内，专业口吻'}
                  value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
              </div>
            </div>
            <button onClick={save} disabled={saving || !form.name.trim()} className="btn btn-gold mt-3.5 w-full"><Plus className="w-4 h-4" /> 保存技能</button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
