import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Plus, Settings as SettingsIcon, Code2, Briefcase, ArrowUp, X,
  AlertTriangle, MessageSquare, KeyRound, Clock,
  CloudSun, FolderPlus, CheckSquare, Square, FileCode2, Terminal,
  Folder, FolderOpen, ChevronRight, FilePlus, RotateCw, PanelLeftClose, PanelLeftOpen,
} from 'lucide-react';
import {
  createSession, listSessions, getSessionMessages, streamMessage, postApproval, revertFile,
  listProviders, getSettings, listReviews,
  listTodos, addTodo, patchTodo, listFolders, addFolder, deleteFolder,
  getWeather, hasNativeFolderPick, pickFolderNative,
  listWorkspaceFiles, readWorkspaceFile, setWorkspace, clearWorkspace, newWorkspaceFile,
  type Frame, type SessionSummary, type Connection, type Todo, type Folder as FolderT,
  type Weather, type WeatherDay, type WorkspaceFile,
} from './api';
import SettingsPanel from './Settings';
import AutomationsPanel from './Automations';

type Msg = { id: string; role: 'user' | 'assistant'; content: string };
type Step = { id: string; label: string; target?: string; status: 'running' | 'done' | 'error' };
type Approval = Extract<Frame, { type: 'approval_request' }>;
type FileChange = Extract<Frame, { type: 'file_change' }>;

// IDE 风格动态 diff：编辑器窗框(红黄绿灯+文件标签) + 行号槽 + 逐行揭示动画 + 末行光标。
// 保留(关掉卡片) / 撤销(写回原内容)。
function DiffCard({ ch, onKeep, onRevert }: { ch: FileChange; onKeep: () => void; onRevert: () => void }) {
  const lines = ch.diff.split('\n');
  // 最后一条新增行 → 末尾打一个闪烁光标，营造"刚敲进去"的动态感
  const lastAdd = lines.reduce((acc, l, i) => (l[0] === '+' && !l.startsWith('+++') ? i : acc), -1);
  const adds = lines.filter((l) => l[0] === '+' && !l.startsWith('+++')).length;
  const dels = lines.filter((l) => l[0] === '-' && !l.startsWith('---')).length;
  return (
    <div className="rise rounded-xl overflow-hidden mb-3"
      style={{ border: '1px solid var(--color-line-2)', boxShadow: '0 10px 28px rgba(60,40,30,0.08)' }}>
      <div className="flex items-center gap-2 px-3.5 h-9 shrink-0" style={{ background: 'var(--color-elevated)', borderBottom: '1px solid var(--color-line)' }}>
        <span className="flex gap-1.5">
          {['#e0796a', '#d9a441', '#5b8c6e'].map((c) => <span key={c} className="w-2.5 h-2.5 rounded-full" style={{ background: c, opacity: 0.85 }} />)}
        </span>
        <span className="font-mono text-[12px] ml-1.5 truncate" style={{ color: 'var(--color-ink-2)' }}>{ch.path}</span>
        <span className="font-mono text-[10.5px] ml-1.5 shrink-0" style={{ color: 'var(--color-ink-3)' }}>
          <span style={{ color: 'var(--color-ok)' }}>+{adds}</span> <span style={{ color: 'var(--color-danger)' }}>−{dels}</span>
        </span>
        <span className="ml-auto flex gap-1.5 shrink-0">
          <button onClick={onRevert} className="btn btn-ghost text-[11px] px-2 py-1">撤销</button>
          <button onClick={onKeep} className="btn btn-gold text-[11px] px-2.5 py-1">保留</button>
        </span>
      </div>
      <div className="overflow-x-auto no-scrollbar" style={{ background: 'var(--color-panel)' }}>
        <pre className="text-[11.5px] font-mono leading-[1.62] py-2">
          {lines.map((line, i) => {
            const c = line[0];
            const isHunk = line.startsWith('@@');
            const isMeta = line.startsWith('+++') || line.startsWith('---');
            const add = c === '+' && !isMeta, del = c === '-' && !isMeta;
            const bg = add ? 'var(--diff-add)' : del ? 'var(--diff-del)' : 'transparent';
            const col = isHunk ? 'var(--color-gold)' : add ? 'var(--color-ok)' : del ? 'var(--color-danger)' : 'var(--color-ink-2)';
            const sign = add ? '+' : del ? '−' : '';
            const text = (isMeta || isHunk) ? line : line.slice(1);
            return (
              <div key={i} className="diff-line flex" style={{ background: bg, animationDelay: `${Math.min(i, 50) * 20}ms` }}>
                <span className="select-none text-right shrink-0" style={{ width: 34, paddingRight: 9, color: 'var(--color-ink-3)', opacity: 0.55 }}>{i + 1}</span>
                <span className="select-none shrink-0 text-center" style={{ width: 14, color: col }}>{sign}</span>
                <span style={{ color: col, whiteSpace: 'pre', paddingRight: 14 }}>{text || ' '}{i === lastAdd && <span className="caret" />}</span>
              </div>
            );
          })}
        </pre>
      </div>
    </div>
  );
}

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

// Agent「在场感」光圈：扁平细环 + 中心点（轨道感，呼应图标）；运行时转一道弧。小尺寸用状态点。
function AgentOrb({ running, size = 48 }: { running: boolean; size?: number }) {
  const gold = 'var(--color-gold)';
  if (size < 22) {
    return (
      <span className="relative inline-flex shrink-0" style={{ width: size, height: size }}>
        {running && <span className="absolute inset-0 rounded-full" style={{ border: `1.5px solid ${gold}`, animation: 'ring 1.5s ease-out infinite' }} />}
        <span className="m-auto rounded-full" style={{ width: size * 0.46, height: size * 0.46, background: gold, animation: running ? 'blink 1.2s infinite' : 'none' }} />
      </span>
    );
  }
  const ring = (inset: string | number, op: number) =>
    ({ position: 'absolute' as const, inset, borderRadius: 9999, border: `1.5px solid ${gold}`, opacity: op });
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <div style={{ ...ring(0, 0.38), animation: `breathe ${running ? 2.4 : 6}s ease-in-out infinite` }} />
      <div style={ring('24%', 0.7)} />
      <div className="absolute rounded-full" style={{ inset: '44%', background: gold }} />
      {running && <div className="absolute rounded-full" style={{ inset: 0, border: '1.5px solid transparent', borderTopColor: gold, animation: 'spin 0.9s linear infinite' }} />}
    </div>
  );
}

// 右上角「在线」状态点：呼吸灯。在线=绿点柔和明暗+光晕脉动；运行=金点闪烁+外扩环。
function StatusDot({ running }: { running: boolean }) {
  const color = running ? 'var(--color-gold)' : 'var(--color-ok)';
  return (
    <span className="relative inline-flex shrink-0" style={{ width: 9, height: 9 }}>
      {running && <span className="absolute rounded-full" style={{ inset: -3, border: `1.5px solid ${color}`, animation: 'ring 1.4s ease-out infinite' }} />}
      <span className="m-auto rounded-full" style={{ width: 9, height: 9, background: color,
        animation: running ? 'blink 1s infinite' : 'glow 2.6s ease-in-out infinite' }} />
    </span>
  );
}

// 日常面板里的单日天气
function Wx({ day, label }: { day: WeatherDay; label: string }) {
  return (
    <div className="text-center flex-1">
      <div className="text-[11px] mb-1" style={{ color: 'var(--color-ink-3)' }}>{label}</div>
      <div className="text-[13.5px]" style={{ color: 'var(--color-ink)' }}>{day.text}</div>
      <div className="text-[12px] mt-1" style={{ color: 'var(--color-ink-2)' }}>
        {day.tmax != null ? `${Math.round(day.tmax)}°` : '—'}
        <span style={{ color: 'var(--color-ink-3)' }}> / {day.tmin != null ? `${Math.round(day.tmin)}°` : '—'}</span>
      </div>
      {day.precip_prob != null && day.precip_prob >= 30 &&
        <div className="text-[10.5px] mt-0.5" style={{ color: 'var(--color-gold)' }}>降水 {day.precip_prob}%</div>}
    </div>
  );
}

// 编码 IDE 中央：只读代码查看（行号槽，编辑器感）
function CodeView({ content }: { content?: string }) {
  if (content === undefined) return <div className="p-5 text-[12.5px]" style={{ color: 'var(--color-ink-3)' }}>加载中…</div>;
  const lines = content.split('\n');
  return (
    <div className="h-full overflow-auto no-scrollbar" style={{ background: 'var(--color-panel)' }}>
      <pre className="text-[12px] font-mono leading-[1.6] py-2">
        {lines.map((line, i) => (
          <div key={i} className="flex">
            <span className="select-none text-right shrink-0" style={{ width: 44, paddingRight: 12, color: 'var(--color-ink-3)', opacity: 0.5 }}>{i + 1}</span>
            <span style={{ whiteSpace: 'pre', color: 'var(--color-ink)', paddingRight: 14 }}>{line || ' '}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}

// 工作区文件树：扁平相对路径 → 嵌套可折叠树
type TreeNode = { name: string; path: string; dir: boolean; children: TreeNode[] };
function buildFileTree(files: WorkspaceFile[]): TreeNode[] {
  const root: TreeNode = { name: '', path: '', dir: true, children: [] };
  for (const f of files) {
    const parts = f.path.split('/');
    let cur = root;
    parts.forEach((part, i) => {
      const isFile = i === parts.length - 1;
      let child = cur.children.find((c) => c.name === part && c.dir === !isFile);
      if (!child) { child = { name: part, path: parts.slice(0, i + 1).join('/'), dir: !isFile, children: [] }; cur.children.push(child); }
      cur = child;
    });
  }
  const sortRec = (n: TreeNode) => {
    n.children.sort((a, b) => (a.dir === b.dir ? a.name.localeCompare(b.name) : a.dir ? -1 : 1));
    n.children.forEach(sortRec);
  };
  sortRec(root);
  return root.children;
}

function FileTree({ files, activeTab, changedPaths, onOpen }: {
  files: WorkspaceFile[]; activeTab: string | null; changedPaths: Set<string>; onOpen: (p: string) => void;
}) {
  const tree = useMemo(() => buildFileTree(files), [files]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggle = (p: string) => setCollapsed((s) => { const n = new Set(s); if (n.has(p)) n.delete(p); else n.add(p); return n; });
  const render = (n: TreeNode, depth: number): React.ReactNode => {
    const pad = 10 + depth * 12;
    if (n.dir) {
      const open = !collapsed.has(n.path);
      return (
        <div key={n.path}>
          <button onClick={() => toggle(n.path)} className="w-full flex items-center gap-1.5 py-1 text-left transition-colors hover:bg-[rgba(255,255,255,0.04)]" style={{ paddingLeft: pad, paddingRight: 10 }}>
            <ChevronRight className="w-3 h-3 shrink-0 transition-transform" style={{ color: 'var(--color-ink-3)', transform: open ? 'rotate(90deg)' : 'none' }} />
            {open ? <FolderOpen className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--color-gold)' }} /> : <Folder className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--color-ink-3)' }} />}
            <span className="text-[12.5px] truncate" style={{ color: 'var(--color-ink-2)' }}>{n.name}</span>
          </button>
          {open && n.children.map((c) => render(c, depth + 1))}
        </div>
      );
    }
    const on = activeTab === n.path;
    const changed = changedPaths.has(n.path);
    return (
      <button key={n.path} onClick={() => onOpen(n.path)} className="w-full flex items-center gap-1.5 py-1 text-left transition-colors hover:bg-[rgba(255,255,255,0.04)]"
        style={{ paddingLeft: pad + 16, paddingRight: 10, background: on ? 'var(--color-elevated)' : 'transparent' }}>
        <FileCode2 className="w-3.5 h-3.5 shrink-0" style={{ color: changed ? 'var(--color-gold)' : 'var(--color-ink-3)' }} />
        <span className="font-mono text-[12px] truncate" style={{ color: on ? 'var(--color-ink)' : 'var(--color-ink-2)' }}>{n.name}</span>
        {changed && <span className="ml-auto w-1.5 h-1.5 rounded-full shrink-0" style={{ background: 'var(--color-gold)' }} />}
      </button>
    );
  };
  return <>{tree.map((n) => render(n, 0))}</>;
}

export default function App() {
  const [scene, setScene] = useState<'coding' | 'assistant'>('assistant');
  const [threads, setThreads] = useState<SessionSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [trace, setTrace] = useState<Step[]>([]);
  const [changes, setChanges] = useState<FileChange[]>([]);
  const [input, setInput] = useState('');
  const [running, setRunning] = useState(false);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showAutos, setShowAutos] = useState(false);
  const [pendingReviews, setPendingReviews] = useState(0);
  const [conns, setConns] = useState<Connection[]>([]);
  const [agentName, setAgentName] = useState('Agent Y');
  const [weather, setWeather] = useState<Weather | null>(null);
  const [todos, setTodos] = useState<Todo[]>([]);
  const [folders, setFolders] = useState<FolderT[]>([]);
  const [newTodo, setNewTodo] = useState('');
  const [files, setFiles] = useState<WorkspaceFile[]>([]);     // 编码场景工作区文件树
  const [wsName, setWsName] = useState('');                    // 工作区名（打开的文件夹名）
  const [wsCustom, setWsCustom] = useState(false);             // 是否是「打开的文件夹」
  const [openTabs, setOpenTabs] = useState<string[]>([]);      // 编辑器打开的文件
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [fileCache, setFileCache] = useState<Record<string, string>>({});
  const [navCollapsed, setNavCollapsed] = useState(false);     // 编码模式自动折叠左侧栏
  const scrollRef = useRef<HTMLDivElement>(null);
  const streamId = useRef<string | null>(null);

  const refreshThreads = () => listSessions().then(setThreads).catch(() => {});
  const refreshConfig = () => {
    listProviders().then(setConns).catch(() => {});
    getSettings().then((d) => setAgentName(d.settings.agent_name || 'Agent Y')).catch(() => {});
    listReviews('pending').then((r) => setPendingReviews(r.length)).catch(() => {});
  };
  // 日常面板数据：当天待办 + 天气 + 已授权目录（助手场景用）
  const refreshDaily = () => {
    listTodos().then(setTodos).catch(() => {});
    listFolders().then(setFolders).catch(() => {});
    getWeather().then(setWeather).catch(() => {});
  };
  const refreshFiles = (sid: string | null) => {
    if (!sid) { setFiles([]); setWsName(''); setWsCustom(false); return; }
    listWorkspaceFiles(sid).then((d) => { setFiles(d.files); setWsName(d.name); setWsCustom(d.is_custom); }).catch(() => {});
  };
  useEffect(() => { refreshThreads(); refreshConfig(); refreshDaily(); }, []);
  useEffect(() => { if (scene === 'assistant') refreshDaily(); else refreshFiles(sessionId); }, [scene, sessionId]);
  useEffect(() => { setNavCollapsed(scene === 'coding'); }, [scene]);  // 进编码自动折叠侧栏，回助手展开

  const addNewTodo = async () => {
    const t = newTodo.trim();
    if (!t) return;
    setNewTodo('');
    await addTodo(t).catch(() => {});
    refreshDaily();
  };
  const toggleTodo = async (td: Todo) => { await patchTodo(td.id, { done: !td.done }).catch(() => {}); refreshDaily(); };
  const pickFolder = async () => {
    let path: string | null = null;
    if (hasNativeFolderPick()) path = await pickFolderNative();
    else path = window.prompt('输入要授权助手读取的文件夹绝对路径：');
    if (path && path.trim()) { await addFolder(path.trim()).catch(() => {}); refreshDaily(); }
  };
  const removeFolder = async (id: string) => { await deleteFolder(id).catch(() => {}); refreshDaily(); };
  const openFile = async (path: string) => {
    setOpenTabs((p) => (p.includes(path) ? p : [...p, path]));
    setActiveTab(path);
    if (sessionId && !(path in fileCache)) {
      const r = await readWorkspaceFile(sessionId, path);
      setFileCache((c) => ({ ...c, [path]: r.content }));
    }
  };
  const closeTab = (path: string) => {
    const rest = openTabs.filter((x) => x !== path);
    setOpenTabs(rest);
    if (activeTab === path) setActiveTab(rest[rest.length - 1] ?? null);
  };
  const ensureSession = async (): Promise<string> => {
    if (sessionId) return sessionId;
    const sid = await createSession('编码', 'coding');
    setSessionId(sid);
    return sid;
  };
  const openFolder = async () => {  // IDE「打开文件夹」
    const path = hasNativeFolderPick() ? await pickFolderNative() : window.prompt('输入要打开的项目文件夹绝对路径：');
    if (!path || !path.trim()) return;
    const sid = await ensureSession();
    await setWorkspace(sid, path.trim()).catch(() => {});
    setOpenTabs([]); setActiveTab(null); setFileCache({});
    refreshFiles(sid);
  };
  const createFile = async () => {  // IDE「新建文件」
    const name = window.prompt('新文件路径（相对工作区，可含子目录，如 src/main.py）：');
    if (!name || !name.trim()) return;
    const sid = await ensureSession();
    const r = await newWorkspaceFile(sid, name.trim(), '').catch(() => null);
    refreshFiles(sid);
    const p = r?.path;
    if (p) { setFileCache((c) => ({ ...c, [p]: '' })); setOpenTabs((t) => (t.includes(p) ? t : [...t, p])); setActiveTab(p); }
  };
  const closeFolder = async () => {
    if (!sessionId) return;
    await clearWorkspace(sessionId).catch(() => {});
    setOpenTabs([]); setActiveTab(null); setFileCache({});
    refreshFiles(sessionId);
  };
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
    else if (fr.type === 'file_change') {
      setChanges((p) => [...p.filter((c) => c.path !== fr.path), fr]);
      setOpenTabs((p) => (p.includes(fr.path) ? p : [...p, fr.path]));  // 改动文件自动在编辑器开标签
      setActiveTab(fr.path);
    }
    else if (fr.type === 'done') streamId.current = null;
    else if (fr.type === 'error') setError(fr.message);
  };

  const run = async () => {
    const text = input.trim();
    if (running || !text) return;
    setInput(''); setError(null); setRunning(true); setChanges([]);
    setMessages((p) => [...p, { id: uid(), role: 'user', content: text }]);
    streamId.current = null;
    try {
      let sid = sessionId;
      if (!sid) { sid = await createSession(text.slice(0, 40), scene); setSessionId(sid); }
      for await (const fr of streamMessage(sid, text)) onFrame(fr);
      refreshThreads();
      refreshFiles(sid);  // 跑完刷新工作区文件树
    } catch (e) { setError(String(e)); }
    finally { setRunning(false); setApproval(null); }
  };

  const decide = async (d: 'allow' | 'deny') => { const a = approval; setApproval(null); if (a) await postApproval(a.approval_id, d); };
  const resetWorkspace = () => { setTrace([]); setChanges([]); setError(null); setOpenTabs([]); setActiveTab(null); setFileCache({}); };
  const newThread = () => { setSessionId(null); setMessages([]); resetWorkspace(); setFiles([]); };
  const selectThread = async (id: string) => { setSessionId(id); resetWorkspace(); setMessages(toChat(await getSessionMessages(id))); refreshFiles(id); };
  const keepChange = (path: string) => {
    setChanges((p) => p.filter((c) => c.path !== path));
    if (sessionId) readWorkspaceFile(sessionId, path).then((r) => setFileCache((c) => ({ ...c, [path]: r.content })));
  };
  const revertChange = async (ch: FileChange) => {
    if (sessionId) await revertFile(sessionId, ch.path, ch.old);
    setChanges((p) => p.filter((c) => c.path !== ch.path));
    setFileCache((c) => ({ ...c, [ch.path]: ch.old }));
  };

  // 对话消息流（助手宽版 / 编码窄版共用）
  const renderMessages = (narrow: boolean) => (
    <>
      {messages.length === 0 && (narrow ? (
        <div className="text-[13px] leading-relaxed mt-6 text-center px-2" style={{ color: 'var(--color-ink-3)' }}>
          给我一个编码任务，我会读 / 改 / 跑测试，改动会在左侧编辑器里高亮成 diff。
        </div>
      ) : (
        <div className="mt-20 flex flex-col items-center text-center rise">
          <AgentOrb running={running} size={54} />
          <div className="font-serif text-[40px] leading-tight mt-7 mb-2">{greet()}</div>
          <p className="text-[14px] max-w-sm" style={{ color: 'var(--color-ink-3)' }}>
            {conns.length === 0
              ? '我是你的私人 AI 助手。先配一个模型连接，我们就能开始。'
              : '问我点什么，或让我帮你整理文件、起草、做表格。'}
          </p>
          {conns.length === 0 && (
            <button onClick={() => setShowSettings(true)} className="btn btn-gold mt-6"><KeyRound className="w-4 h-4" /> 配置模型连接</button>
          )}
        </div>
      ))}
      {messages.map((m) => (
        <div key={m.id} className={`rise mb-6 flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
          {m.role === 'user'
            ? <div className="max-w-[85%] px-4 py-2.5 rounded-2xl rounded-tr-md text-[14px] leading-relaxed" style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-line)' }}>{m.content}</div>
            : <div className="max-w-[92%]">
                <div className="text-[12px] font-medium mb-1.5 tracking-wide" style={{ color: 'var(--color-gold)' }}>{agentName}</div>
                <div className="text-[14px] leading-[1.7] whitespace-pre-wrap" style={{ color: 'var(--color-ink)' }}>{m.content}</div>
              </div>}
        </div>
      ))}
      {running && !messages.some((m) => m.id === streamId.current) && (
        <div className="flex gap-1.5 items-center mb-6">
          {[0, 0.2, 0.4].map((d) => <span key={d} className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--color-gold)', animation: `blink 1.4s ${d}s infinite` }} />)}
        </div>
      )}
      {error && <div className="text-[13px] rounded-xl px-4 py-2.5 mb-6" style={{ color: 'var(--color-danger)', background: 'rgba(224,121,106,0.1)', border: '1px solid rgba(224,121,106,0.25)' }}>{error}</div>}
    </>
  );

  // 输入区（showFolders：助手场景才显示选文件夹）
  const composer = (showFolders: boolean) => (
    <>
      {showFolders && (
        <div className="flex flex-wrap items-center gap-1.5 mb-2">
          {folders.map((f) => (
            <span key={f.id} className="inline-flex items-center gap-1 pl-2.5 pr-1.5 py-1 rounded-full text-[11.5px]"
              style={{ background: 'var(--color-panel)', border: '1px solid var(--color-line)', color: 'var(--color-ink-2)' }}>
              <span className="font-mono truncate max-w-[170px]" title={f.path}>{f.path.split('/').filter(Boolean).pop() || f.path}</span>
              <button onClick={() => removeFolder(f.id)} className="opacity-45 hover:opacity-100"><X className="w-3 h-3" /></button>
            </span>
          ))}
          <button onClick={pickFolder} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11.5px] transition-colors"
            style={{ border: '1px dashed var(--color-line-2)', color: 'var(--color-ink-3)' }}>
            <FolderPlus className="w-3.5 h-3.5" /> {folders.length ? '加文件夹' : '选择文件夹读取'}
          </button>
        </div>
      )}
      <div className="flex items-end gap-2 p-2 rounded-2xl" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-line-2)' }}>
        <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={1} disabled={running}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); run(); } }}
          placeholder={scene === 'assistant' ? '问问你的助手…' : '让我改代码 / 修测试…'}
          className="flex-1 bg-transparent outline-none resize-none px-3 py-2.5 text-[14px] max-h-44" style={{ color: 'var(--color-ink)' }} />
        <button onClick={run} disabled={running || !input.trim()} className="btn btn-gold w-10 h-10 p-0 shrink-0"><ArrowUp className="w-[18px] h-[18px]" /></button>
      </div>
    </>
  );

  return (
    <div className={`flex h-screen w-full overflow-hidden ${scene === 'coding' ? 'theme-ide' : ''}`} style={{ color: 'var(--color-ink)' }}>
      {/* SIDEBAR —— 编码模式折叠成图标栏 */}
      {navCollapsed ? (
        <aside className="w-[56px] shrink-0 hidden md:flex flex-col items-center py-3 gap-1" style={{ background: 'var(--color-panel)', borderRight: '1px solid var(--color-line)' }}>
          <button onClick={() => setNavCollapsed(false)} title="展开侧栏" className="btn btn-ghost p-2"><PanelLeftOpen className="w-4 h-4" /></button>
          <div className="my-1"><AgentOrb running={running} size={18} /></div>
          <button onClick={newThread} title="新对话" className="btn btn-ghost p-2"><Plus className="w-4 h-4" style={{ color: 'var(--color-gold)' }} /></button>
          <div className="w-7 h-px my-1" style={{ background: 'var(--color-line)' }} />
          {([['assistant', Briefcase], ['coding', Code2]] as const).map(([s, Icon]) => (
            <button key={s} onClick={() => setScene(s)} title={s === 'assistant' ? '助手' : '编码'} className="btn p-2"
              style={scene === s ? { background: 'var(--color-elevated)', color: 'var(--color-ink)' } : { color: 'var(--color-ink-3)' }}>
              <Icon className="w-4 h-4" />
            </button>
          ))}
          <div className="flex-1" />
          <button onClick={() => setShowAutos(true)} title="自动化" className="btn btn-ghost p-2 relative">
            <Clock className="w-4 h-4" />
            {pendingReviews > 0 && <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full" style={{ background: 'var(--color-gold)' }} />}
          </button>
          <button onClick={() => setShowSettings(true)} title="设置" className="btn btn-ghost p-2"><SettingsIcon className="w-4 h-4" /></button>
        </aside>
      ) : (
      <aside className="w-[258px] shrink-0 hidden md:flex flex-col" style={{ background: 'var(--color-panel)', borderRight: '1px solid var(--color-line)' }}>
        <div className="h-16 flex items-center px-5 gap-3">
          <AgentOrb running={running} size={18} />
          <span className="font-serif text-[22px] leading-none tracking-tight flex-1 truncate">{agentName}</span>
          <button onClick={() => setNavCollapsed(true)} title="折叠侧栏" className="btn btn-ghost p-1.5"><PanelLeftClose className="w-4 h-4" /></button>
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

        <div className="p-3 space-y-0.5" style={{ borderTop: '1px solid var(--color-line)' }}>
          <button onClick={() => setShowAutos(true)} className="btn btn-ghost w-full justify-start">
            <Clock className="w-4 h-4" /> 自动化
            {pendingReviews > 0 && <span className="ml-auto px-1.5 rounded-full text-[10px] font-semibold" style={{ background: 'var(--color-gold)', color: '#fff7f1' }}>{pendingReviews}</span>}
          </button>
          <button onClick={() => setShowSettings(true)} className="btn btn-ghost w-full justify-start"><SettingsIcon className="w-4 h-4" /> 设置</button>
        </div>
      </aside>
      )}

      {/* MAIN */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-16 flex items-center justify-between px-6 shrink-0" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <button onClick={() => setShowSettings(true)} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[13px]"
            style={{ background: 'var(--color-panel)', border: '1px solid var(--color-line)' }}>
            <KeyRound className="w-3.5 h-3.5" style={{ color: active ? 'var(--color-gold)' : 'var(--color-danger)' }} />
            <span style={{ color: 'var(--color-ink-2)' }}>{active ? (active.model_default || active.provider) : '未配置模型'}</span>
          </button>
          <div className="flex items-center gap-2">
            <StatusDot running={running} />
            <span className="text-[12px]" style={{ color: 'var(--color-ink-3)' }}>{running ? '思考中…' : '在线'}</span>
          </div>
        </header>

        <div className="flex flex-1 overflow-hidden">
          {scene === 'assistant' ? (
            <>
              {/* 助手：对话主区 */}
              <div className="flex-1 flex flex-col min-w-0 relative">
                <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 pt-10 pb-44 no-scrollbar">
                  <div className="max-w-2xl mx-auto w-full">
                    {renderMessages(false)}
                    {changes.length > 0 && (
                      <div className="mt-1 mb-8">
                        <div className="label mb-2.5">本次改动 · {changes.length} 个文件</div>
                        {changes.map((ch) => (
                          <div key={ch.path}><DiffCard ch={ch} onKeep={() => keepChange(ch.path)} onRevert={() => revertChange(ch)} /></div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div className="absolute bottom-0 inset-x-0 px-6 pb-6 pt-12 pointer-events-none" style={{ background: 'linear-gradient(to top, var(--color-bg) 55%, transparent)' }}>
                  <div className="max-w-2xl mx-auto pointer-events-auto">{composer(true)}</div>
                </div>
              </div>

              {/* 日常面板：今日天气 + 待办 */}
              <aside className="w-[300px] shrink-0 hidden lg:flex flex-col" style={{ background: 'var(--color-panel)', borderLeft: '1px solid var(--color-line)' }}>
                <div className="h-12 flex items-center px-5" style={{ borderBottom: '1px solid var(--color-line)' }}>
                  <span className="label">今日</span>
                </div>
                <div className="flex-1 overflow-y-auto p-5 no-scrollbar space-y-6">
                  <div>
                    <div className="label mb-2.5 flex items-center gap-2"><CloudSun className="w-3.5 h-3.5" /> 天气{weather?.ok && weather.label ? ` · ${weather.label}` : ''}</div>
                    {weather?.ok ? (
                      <div className="card p-3.5" style={{ background: 'var(--color-elevated)' }}>
                        <div className="flex items-start gap-2">
                          {weather.today && <Wx day={weather.today} label="今天" />}
                          {weather.tomorrow && <><span style={{ width: 1, alignSelf: 'stretch', background: 'var(--color-line)' }} /><Wx day={weather.tomorrow} label="明天" /></>}
                        </div>
                        {weather.advice && (
                          <div className="text-[12px] leading-relaxed mt-3 pt-3" style={{ color: 'var(--color-ink-2)', borderTop: '1px solid var(--color-line)' }}>{weather.advice}</div>
                        )}
                      </div>
                    ) : (
                      <button onClick={() => setShowSettings(true)} className="text-[12.5px] text-left leading-relaxed" style={{ color: 'var(--color-ink-3)' }}>
                        在设置里填写城市，这里就会显示今天 / 明天天气和出行建议 →
                      </button>
                    )}
                  </div>

                  <div>
                    <div className="label mb-2.5">待办</div>
                    <div className="flex items-center gap-1.5 mb-3">
                      <input value={newTodo} onChange={(e) => setNewTodo(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') addNewTodo(); }}
                        placeholder="加一项待办…" className="field py-2 text-[13px]" />
                      <button onClick={addNewTodo} className="btn btn-gold w-9 h-9 p-0 shrink-0"><Plus className="w-4 h-4" /></button>
                    </div>
                    <div className="space-y-0.5">
                      {todos.filter((t) => !t.done).length === 0 && <div className="text-[12.5px] px-1" style={{ color: 'var(--color-ink-3)' }}>没有待办，清爽。</div>}
                      {todos.filter((t) => !t.done).map((t) => (
                        <button key={t.id} onClick={() => toggleTodo(t)} className="w-full flex items-start gap-2 px-1.5 py-1.5 rounded-lg text-left transition-colors hover:bg-[rgba(43,42,39,0.04)]">
                          <Square className="w-4 h-4 mt-0.5 shrink-0" style={{ color: 'var(--color-ink-3)' }} />
                          <span className="text-[13px]" style={{ color: 'var(--color-ink-2)' }}>{t.text}{t.due && <span className="ml-1.5 text-[11px]" style={{ color: 'var(--color-ink-3)' }}>· {t.due}</span>}</span>
                        </button>
                      ))}
                      {todos.some((t) => t.done) && (
                        <div className="pt-1.5 mt-1.5" style={{ borderTop: '1px solid var(--color-line)' }}>
                          {todos.filter((t) => t.done).map((t) => (
                            <button key={t.id} onClick={() => toggleTodo(t)} className="w-full flex items-start gap-2 px-1.5 py-1.5 rounded-lg text-left transition-colors hover:bg-[rgba(43,42,39,0.04)]">
                              <CheckSquare className="w-4 h-4 mt-0.5 shrink-0" style={{ color: 'var(--color-ok)' }} />
                              <span className="text-[13px] line-through" style={{ color: 'var(--color-ink-3)' }}>{t.text}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </aside>
            </>
          ) : (
            <>
              {/* 编码 IDE：(文件树 | 编辑器) 上 / 终端 下；右侧对话全高 */}
              <div className="flex-1 flex flex-col min-w-0">
                <div className="flex flex-1 min-h-0">
                  {/* 文件树 / 资源管理器 */}
                  <aside className="w-[232px] shrink-0 hidden md:flex flex-col" style={{ background: 'var(--color-panel)', borderRight: '1px solid var(--color-line)' }}>
                    <div className="h-9 flex items-center gap-0.5 pl-4 pr-2 shrink-0" style={{ borderBottom: '1px solid var(--color-line)' }}>
                      <span className="label truncate flex-1" title={wsCustom ? wsName : '会话工作区'}>
                        {wsCustom ? wsName : '工作区'}
                      </span>
                      <button onClick={openFolder} title="打开文件夹" className="btn btn-ghost p-1.5"><FolderOpen className="w-3.5 h-3.5" /></button>
                      <button onClick={createFile} title="新建文件" className="btn btn-ghost p-1.5"><FilePlus className="w-3.5 h-3.5" /></button>
                      <button onClick={() => refreshFiles(sessionId)} title="刷新" className="btn btn-ghost p-1.5"><RotateCw className="w-3.5 h-3.5" /></button>
                    </div>
                    <div className="flex-1 overflow-y-auto no-scrollbar py-1.5">
                      {files.length === 0 ? (
                        <div className="px-4 mt-3 text-[12px] leading-[1.9]" style={{ color: 'var(--color-ink-3)' }}>
                          空工作区。
                          <button onClick={openFolder} className="mt-2 flex items-center gap-1.5" style={{ color: 'var(--color-gold)' }}><FolderOpen className="w-3.5 h-3.5" /> 打开文件夹</button>
                          <button onClick={createFile} className="flex items-center gap-1.5" style={{ color: 'var(--color-gold)' }}><FilePlus className="w-3.5 h-3.5" /> 新建文件</button>
                          <span className="block mt-1.5 opacity-80">或在右侧直接给我一个编码任务。</span>
                        </div>
                      ) : (
                        <div key={sessionId || 'none'}><FileTree files={files} activeTab={activeTab} changedPaths={new Set(changes.map((c) => c.path))} onOpen={openFile} /></div>
                      )}
                    </div>
                    {wsCustom && (
                      <button onClick={closeFolder} className="text-[11px] px-4 py-2 text-left shrink-0" style={{ color: 'var(--color-ink-3)', borderTop: '1px solid var(--color-line)' }}>← 关闭文件夹（回默认工作区）</button>
                    )}
                  </aside>

                  {/* 编辑器：标签页 + 内容 */}
                  <div className="flex-1 flex flex-col min-w-0" style={{ background: 'var(--color-bg)' }}>
                    <div className="h-9 flex items-stretch shrink-0 overflow-x-auto no-scrollbar" style={{ borderBottom: '1px solid var(--color-line)', background: 'var(--color-panel)' }}>
                      {openTabs.length === 0 && <div className="flex items-center px-4 text-[12px]" style={{ color: 'var(--color-ink-3)' }}>编辑器</div>}
                      {openTabs.map((t) => {
                        const on = activeTab === t; const changed = changes.some((c) => c.path === t);
                        return (
                          <div key={t} onClick={() => setActiveTab(t)} className="flex items-center gap-1.5 px-3 cursor-pointer text-[12px] font-mono shrink-0"
                            style={{ borderRight: '1px solid var(--color-line)', background: on ? 'var(--color-bg)' : 'transparent', color: on ? 'var(--color-ink)' : 'var(--color-ink-3)' }}>
                            {changed && <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--color-gold)' }} />}
                            {t.split('/').pop()}
                            <button onClick={(e) => { e.stopPropagation(); closeTab(t); }} className="opacity-40 hover:opacity-100 ml-0.5"><X className="w-3 h-3" /></button>
                          </div>
                        );
                      })}
                    </div>
                    {activeTab && (
                      <div className="px-4 py-1 text-[11px] font-mono shrink-0 flex items-center gap-1.5" style={{ color: 'var(--color-ink-3)', borderBottom: '1px solid var(--color-line)', background: 'var(--color-panel)' }}>
                        {changes.some((c) => c.path === activeTab) && <span style={{ color: 'var(--color-gold)' }}>● 未审阅改动</span>}
                        <span className="truncate">{activeTab}</span>
                      </div>
                    )}
                    <div className="flex-1 min-h-0 overflow-hidden">
                      {!activeTab ? (
                        <div className="h-full flex flex-col items-center justify-center text-center px-8 gap-3" style={{ color: 'var(--color-ink-3)' }}>
                          <Code2 className="w-8 h-8" style={{ color: 'var(--color-line-2)' }} />
                          <div className="text-[13px] leading-relaxed">左侧选择文件查看；<br />agent 的改动会自动在这里高亮成 diff。</div>
                        </div>
                      ) : (() => {
                        const ch = changes.find((c) => c.path === activeTab);
                        return ch
                          ? <div className="h-full overflow-auto no-scrollbar p-3"><DiffCard ch={ch} onKeep={() => keepChange(ch.path)} onRevert={() => revertChange(ch)} /></div>
                          : <CodeView content={fileCache[activeTab]} />;
                      })()}
                    </div>
                  </div>
                </div>

                {/* 终端 · 执行轨迹 */}
                <div className="shrink-0 flex flex-col" style={{ height: 188, borderTop: '1px solid var(--color-line)', background: 'var(--color-panel)' }}>
                  <div className="h-9 flex items-center px-4 gap-2 shrink-0" style={{ borderBottom: '1px solid var(--color-line)' }}>
                    <Terminal className="w-3.5 h-3.5" style={{ color: 'var(--color-ink-3)' }} />
                    <span className="label">终端 · 执行轨迹</span>
                  </div>
                  <div className="flex-1 overflow-y-auto no-scrollbar px-4 py-2 font-mono text-[12px] leading-[1.75]">
                    {trace.length === 0 && <div style={{ color: 'var(--color-ink-3)' }}>工具调用会实时出现在这里。</div>}
                    {trace.map((s) => (
                      <div key={s.id} className="flex items-center gap-2 rise">
                        <span className="shrink-0" style={{ color: s.status === 'error' ? 'var(--color-danger)' : s.status === 'done' ? 'var(--color-ok)' : 'var(--color-gold)' }}>
                          {s.status === 'done' ? '✓' : s.status === 'error' ? '✗' : '▸'}
                        </span>
                        <span style={{ color: 'var(--color-ink)' }}>{s.label}</span>
                        {s.target && <span className="truncate" style={{ color: 'var(--color-ink-3)' }}>{s.target}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* 对话面板 */}
              <aside className="w-[360px] shrink-0 hidden lg:flex flex-col" style={{ background: 'var(--color-panel)', borderLeft: '1px solid var(--color-line)' }}>
                <div className="h-9 flex items-center px-4 shrink-0" style={{ borderBottom: '1px solid var(--color-line)' }}>
                  <span className="label flex items-center gap-2"><MessageSquare className="w-3.5 h-3.5" /> 对话</span>
                </div>
                <div ref={scrollRef} className="flex-1 overflow-y-auto no-scrollbar px-4 py-4">{renderMessages(true)}</div>
                <div className="p-3" style={{ borderTop: '1px solid var(--color-line)' }}>{composer(false)}</div>
              </aside>
            </>
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
      <AnimatePresence>
        {showAutos && <AutomationsPanel onClose={() => { setShowAutos(false); refreshConfig(); }} />}
      </AnimatePresence>
    </div>
  );
}
