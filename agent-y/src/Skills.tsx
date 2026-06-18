import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { X, Plus, Trash2, Sparkles, BookOpen, Package, FolderOpen, FileCode2, ChevronDown } from 'lucide-react';
import { listSkills, addSkill, installSkill, deleteSkill, hasNativeFolderPick, pickFolderNative, type SkillMeta } from './api';

const EMPTY = { name: '', description: '', when_to_use: '', body: '' };

// 技能库：像 Claude Desktop 那样「安装」一个技能包（含 SKILL.md 的文件夹，可带脚本）。
// 装好后 agent 平时只看到名字+简介；检测到相关任务，会自动从技能库调用对应技能（渐进披露）。
export default function SkillsPanel({ onClose }: { onClose: () => void }) {
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [err, setErr] = useState('');
  const [manualOpen, setManualOpen] = useState(false);

  const reload = () => listSkills().then(setSkills).catch(() => {});
  useEffect(() => { reload(); }, []);

  const install = async () => {
    const path = hasNativeFolderPick() ? await pickFolderNative() : window.prompt('技能文件夹路径（里面要有 SKILL.md）：');
    if (!path || !path.trim()) return;
    setInstalling(true); setErr('');
    try { await installSkill(path.trim()); reload(); }
    catch { setErr('安装失败：所选文件夹里要有 SKILL.md'); }
    finally { setInstalling(false); }
  };
  const save = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try { await addSkill(form); setForm(EMPTY); setManualOpen(false); reload(); }
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
            <span className="font-serif text-2xl tracking-tight">技能库</span>
          </div>
          <button onClick={onClose} className="btn btn-ghost p-2"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-7 no-scrollbar space-y-6">
          <p className="text-[12.5px] leading-relaxed" style={{ color: 'var(--color-ink-3)' }}>
            像装插件一样把技能装进库（一个含 <span className="font-mono">SKILL.md</span> 的文件夹，可带脚本/资源）。装好后平时只有名字+简介进入上下文；当任务相关，
            <span style={{ color: 'var(--color-gold)' }}>助手会自动从技能库调用对应技能</span>、按其步骤（含运行附带脚本）完成。
          </p>

          {/* 安装入口 */}
          <button onClick={install} disabled={installing}
            className="w-full flex items-center gap-3 px-4 py-4 rounded-xl transition-colors"
            style={{ border: '1.5px dashed var(--color-line-2)', background: 'var(--color-elevated)' }}>
            <Package className="w-5 h-5 shrink-0" style={{ color: 'var(--color-gold)' }} />
            <div className="text-left">
              <div className="text-[14px] font-medium">{installing ? '安装中…' : '安装技能（选择文件夹）'}</div>
              <div className="text-[11.5px]" style={{ color: 'var(--color-ink-3)' }}>选一个含 SKILL.md 的技能文件夹，连同脚本一起装入库</div>
            </div>
            <FolderOpen className="w-4 h-4 ml-auto shrink-0" style={{ color: 'var(--color-ink-3)' }} />
          </button>
          {err && <div className="text-[12px]" style={{ color: 'var(--color-danger)' }}>{err}</div>}

          {/* 已装技能 */}
          <div className="space-y-2">
            <div className="label">已安装 · {skills.length}</div>
            {skills.length === 0 && <div className="text-[12.5px]" style={{ color: 'var(--color-ink-3)' }}>还没装技能。装一个，助手就会在合适的任务里自动用上。</div>}
            {skills.map((s) => (
              <div key={s.name} className="flex items-start gap-3 px-4 py-3 rounded-xl" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-line)' }}>
                <BookOpen className="w-4 h-4 mt-0.5 shrink-0" style={{ color: 'var(--color-gold)' }} />
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-medium">{s.name}</div>
                  {s.description && <div className="text-[12px] mt-0.5" style={{ color: 'var(--color-ink-2)' }}>{s.description}</div>}
                  {s.when_to_use && <div className="text-[11px] mt-0.5" style={{ color: 'var(--color-ink-3)' }}>何时用：{s.when_to_use}</div>}
                  {s.files && s.files.length > 0 && (
                    <div className="flex items-center gap-1 mt-1.5 text-[11px]" style={{ color: 'var(--color-ink-3)' }}>
                      <FileCode2 className="w-3 h-3" /> {s.files.length} 个附带文件
                    </div>
                  )}
                </div>
                <button onClick={() => deleteSkill(s.name).then(reload)} title="卸载" className="btn btn-ghost p-1.5 shrink-0"><Trash2 className="w-3.5 h-3.5" /></button>
              </div>
            ))}
          </div>

          {/* 手动新建（次要） */}
          <div>
            <button onClick={() => setManualOpen((v) => !v)} className="flex items-center gap-1.5 text-[12.5px]" style={{ color: 'var(--color-ink-3)' }}>
              <ChevronDown className="w-3.5 h-3.5 transition-transform" style={{ transform: manualOpen ? 'rotate(180deg)' : 'none' }} /> 或手动写一个简单技能
            </button>
            {manualOpen && (
              <div className="card p-4 mt-3" style={{ background: 'var(--color-elevated)' }}>
                <div className="space-y-2.5">
                  <input className="field" placeholder="名字（如 周报撰写）" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                  <input className="field" placeholder="简介（一句话，会进上下文目录）" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                  <input className="field" placeholder="何时用（可选）" value={form.when_to_use} onChange={(e) => setForm({ ...form, when_to_use: e.target.value })} />
                  <textarea className="field leading-relaxed" rows={5} placeholder={'完整步骤 / 注意事项（命中才加载）'} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
                </div>
                <button onClick={save} disabled={saving || !form.name.trim()} className="btn btn-gold mt-3 w-full"><Plus className="w-4 h-4" /> 保存</button>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
