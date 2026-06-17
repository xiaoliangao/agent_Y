import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  MessageSquare, Sparkles, Plus, Settings, ChevronDown,
  Code2, Briefcase, Play, CircleDot, Check, Terminal,
  Box, Cpu, FileCode2, History, Database, ArrowRight,
  TrendingUp, Circle, CheckCircle2, ChevronRight
} from 'lucide-react';

// --- MOCK DATA ---
const INITIAL_THREADS = [
  { id: '1', title: 'Fix login state persistence bug', isActive: true },
  { id: '2', title: 'Refactor payment gateway', isActive: false },
  { id: '3', title: 'Daily report automation', isActive: false },
];

const INITIAL_MESSAGES = [
  { 
    id: '1', 
    role: 'user', 
    content: '修复在移动端登录时状态丢失的测试 (Fix mobile login state loss test)' 
  },
  { 
    id: '2', 
    role: 'assistant', 
    content: 'I have analyzed the mobile login flow test failures. The issue stems from `sessionStorage` being cleared prematurely during the OAuth redirect sequence. I will write a patch to preserve the authentication token flag, and then run the regression test suite to ensure the problem is resolved.' 
  },
];

const INITIAL_TRACE = [
  { id: 't1', type: 'plan', label: 'Analyze execution plan', tokens: 142, latency: 45, status: 'done' },
  { id: 't2', type: 'tool', label: 'read_file', target: 'src/auth/session.ts', tokens: 312, latency: 120, status: 'done' },
];

export default function App() {
  const [scene, setScene] = useState<'coding' | 'assistant'>('coding');
  const [messages, setMessages] = useState(INITIAL_MESSAGES);
  const [traceState, setTraceState] = useState(INITIAL_TRACE);
  const [inputValue, setInputValue] = useState('');
  const [simStatus, setSimStatus] = useState<'idle' | 'running' | 'approval'>('idle');

  const handleRun = () => {
    if (simStatus !== 'idle' || (!inputValue.trim() && simStatus !== 'idle')) return;
    
    const text = inputValue || '应用修复并运行测试';
    setInputValue('');
    setSimStatus('running');
    setMessages(prev => [...prev, { id: Date.now().toString(), role: 'user', content: text }]);
    
    setTimeout(() => {
      setTraceState(prev => [...prev, { id: 't3', type: 'tool', label: 'edit_file', target: 'src/auth/session.ts', tokens: 840, latency: 400, status: 'running' } as any]);
      
      setTimeout(() => {
        setSimStatus('approval');
      }, 1500);
    }, 600);
  };

  const handleApprove = () => {
    setSimStatus('idle');
    setTraceState(prev => prev.map(t => t.id === 't3' ? { ...t, status: 'done', latency: 850 } : t));
    
    setTimeout(() => {
      setTraceState(prev => [...prev, { id: 't4', type: 'cmd', label: 'run_tests', target: 'pass', tokens: 120, latency: 2600, status: 'done' } as any]);
      setMessages(prev => [
        ...prev,
        { id: Date.now().toString(), role: 'assistant', content: '测试已通过。Bug 修复完毕 ✅' }
      ]);
    }, 1000);
  };

  return (
    <div className="flex h-screen w-full bg-[#FAFAFC] font-sans overflow-hidden text-gray-900 selection:bg-gray-200">
      
      {/* 
        ================================================================
        THREADS SIDEBAR
        ================================================================
      */}
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
          <button className="w-full flex items-center gap-2 px-3 py-2 text-[13px] font-medium text-gray-700 bg-white border border-gray-200/80 rounded shadow-[0_1px_2px_rgb(0,0,0,0.02)] hover:shadow-sm hover:border-gray-300 transition-all">
            <Plus className="w-4 h-4 text-gray-400" />
            New Thread
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-2 no-scrollbar">
          <div className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest mb-3 px-2">
            Active Threads
          </div>
          <div className="space-y-0.5">
            {INITIAL_THREADS.map(th => (
              <button 
                key={th.id} 
                className={`w-full flex items-center text-left px-3 py-2 rounded-md transition-colors ${
                  th.isActive 
                    ? 'bg-white shadow-[0_1px_3px_rgb(0,0,0,0.04)] border border-gray-200/60' 
                    : 'border border-transparent hover:bg-gray-200/40 text-gray-500 hover:text-gray-900'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <MessageSquare className={`w-3.5 h-3.5 shrink-0 ${th.isActive ? 'text-gray-900' : 'text-gray-400'}`} />
                  <span className={`text-[13px] truncate ${th.isActive ? 'font-medium text-gray-900' : 'text-gray-600'}`}>
                    {th.title}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="p-4 border-t border-gray-200/50">
           <button className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-200/40 rounded transition-colors border border-transparent">
             <Settings className="w-4 h-4 text-gray-400" />
             Settings
           </button>
        </div>
      </aside>

      {/* 
        ================================================================
        MAIN CONTENT + TRACE SPLIT VIEW
        ================================================================
      */}
      <main className="flex-1 flex flex-col min-w-0 bg-white">
        
        {/* Top App Header */}
        <header className="h-14 flex items-center justify-between px-6 border-b border-gray-200/60 shrink-0 bg-white z-10">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-gray-200 bg-gray-50/50 shadow-sm hover:bg-gray-100 transition-colors cursor-pointer group">
              <Sparkles className="w-3.5 h-3.5 text-gray-600 group-hover:text-gray-900" />
              <span className="text-[13px] font-medium text-gray-700 group-hover:text-gray-900">Claude Opus 4.8</span>
              <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
            </div>
            
            {/* Context Breadcrumb / Status */}
            <div className="hidden lg:flex items-center gap-2 text-[13px] text-gray-400 font-medium tracking-wide">
              <span>coding-v1</span>
              <ChevronRight className="w-3 h-3 text-gray-300" />
              <span className="text-gray-600">auth module</span>
            </div>
          </div>

          <div className="flex items-center gap-4">
             {/* Scene Switcher */}
             <div className="flex bg-gray-100/80 p-0.5 rounded-md border border-gray-200/50">
               <button 
                 onClick={() => setScene('coding')} 
                 className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-[12px] font-medium transition-all ${scene === 'coding' ? 'bg-white text-gray-900 shadow-[0_1px_2px_rgb(0,0,0,0.06)]' : 'text-gray-500 hover:text-gray-700'}`}
               >
                 <Code2 className="w-3.5 h-3.5" /> Code
               </button>
               <button 
                 onClick={() => setScene('assistant')} 
                 className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-[12px] font-medium transition-all ${scene === 'assistant' ? 'bg-white text-gray-900 shadow-[0_1px_2px_rgb(0,0,0,0.06)]' : 'text-gray-500 hover:text-gray-700'}`}
               >
                 <Briefcase className="w-3.5 h-3.5" /> Assist
               </button>
             </div>
          </div>
        </header>

        <div className="flex flex-1 overflow-hidden">
          
          {/* == CHAT AREA == */}
          <div className="flex flex-1 flex-col relative min-w-0">
             <div className="flex-1 overflow-y-auto w-full pt-10 pb-40 px-6 no-scrollbar">
                <div className="max-w-3xl mx-auto w-full">
                  {messages.map((msg) => (
                    <motion.div 
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      key={msg.id} 
                      className={`flex gap-5 mb-10 group ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                      {msg.role === 'assistant' && (
                        <div className="shrink-0 pt-0.5 select-none">
                          <div className="w-7 h-7 rounded border border-gray-200 bg-gray-50 flex items-center justify-center text-gray-600 shadow-[0_1px_2px_rgb(0,0,0,0.02)]">
                            <Box className="w-4 h-4" />
                          </div>
                        </div>
                      )}
                      
                      <div className={`max-w-[85%] ${msg.role === 'user' ? 'bg-gray-100 rounded-[18px] rounded-tr-sm px-5 py-3.5 border border-gray-200/50 shadow-sm' : 'pt-0.5'}`}>
                        {msg.role === 'assistant' && (
                          <div className="font-semibold text-gray-900 text-sm mb-1.5 tracking-wide">
                            Agent Y
                          </div>
                        )}
                        <div className={`text-[14px] leading-relaxed whitespace-pre-wrap ${msg.role === 'user' ? 'text-gray-800' : 'text-gray-700 font-normal'} tracking-wide`}>
                          {msg.content}
                        </div>
                      </div>
                    </motion.div>
                  ))}

                  <AnimatePresence>
                    {simStatus === 'running' && (
                      <motion.div 
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.95 }}
                        className="flex gap-5 mb-10 justify-start"
                      >
                         <div className="shrink-0 pt-0.5 select-none opacity-50">
                            <div className="w-7 h-7 rounded border border-gray-200 bg-gray-50 flex items-center justify-center text-gray-600 shadow-sm">
                              <Box className="w-4 h-4" />
                            </div>
                         </div>
                         <div className="pt-1.5">
                            <div className="flex gap-1.5 items-center">
                              <motion.div animate={{ opacity: [0.3, 1, 0.3] }} transition={{ repeat: Infinity, duration: 1.5, delay: 0 }} className="w-1.5 h-1.5 rounded-full bg-gray-500"></motion.div>
                              <motion.div animate={{ opacity: [0.3, 1, 0.3] }} transition={{ repeat: Infinity, duration: 1.5, delay: 0.2 }} className="w-1.5 h-1.5 rounded-full bg-gray-500"></motion.div>
                              <motion.div animate={{ opacity: [0.3, 1, 0.3] }} transition={{ repeat: Infinity, duration: 1.5, delay: 0.4 }} className="w-1.5 h-1.5 rounded-full bg-gray-500"></motion.div>
                            </div>
                         </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
             </div>

             {/* Input Container */}
             <div className="absolute bottom-0 w-full bg-gradient-to-t from-white via-white/95 to-transparent pt-12 pb-6 px-6 z-10 pointer-events-none">
                <div className="max-w-3xl mx-auto relative pointer-events-auto shadow-sm">
                  <div className="bg-white border border-gray-200/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-[16px] p-1.5 flex items-end transition-all duration-300 focus-within:border-gray-300 focus-within:shadow-[0_8px_30px_rgb(0,0,0,0.08)] relative overflow-hidden">
                    <div className="absolute top-0 left-0 w-1 p-0 h-full bg-gray-900 border-l border-gray-900 rounded-l-[16px]"></div>
                    <div className="p-3 pl-4">
                      <Terminal className="w-[18px] h-[18px] text-gray-400" />
                    </div>
                    <textarea 
                      value={inputValue}
                      onChange={(e) => setInputValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault();
                          handleRun();
                        }
                      }}
                      className="flex-1 max-h-48 bg-transparent py-3 px-1 outline-none resize-none text-[14px] text-gray-800 placeholder-gray-400 tracking-wide"
                      rows={1}
                      placeholder={scene === 'coding' ? "Instruct the agent to modify code..." : "Ask your assistant..."}
                      disabled={simStatus !== 'idle'}
                    />
                    <button 
                      onClick={handleRun}
                      disabled={simStatus !== 'idle'}
                      className={`p-2.5 m-1 rounded-[10px] transition-all shrink-0 outline-none flex items-center justify-center
                        ${simStatus === 'idle' 
                          ? 'bg-gray-900 text-white hover:bg-gray-800 shadow-[0_2px_4px_rgb(0,0,0,0.1)]' 
                          : 'bg-gray-100 text-gray-400 cursor-not-allowed'}`}
                    >
                       <Play className="w-[14px] h-[14px] fill-current" />
                    </button>
                  </div>
                </div>
             </div>
          </div>

          {/* == EXECUTION TRACE AREA (Right Panel) == */}
          <aside className={`w-[360px] shrink-0 border-l border-gray-200/60 bg-[#FAFAFC] flex flex-col hidden lg:flex ${scene === 'assistant' ? 'hidden lg:hidden block' : ''}`}>
             <div className="h-12 border-b border-gray-200/60 flex items-center px-5 shrink-0 bg-white">
                <h3 className="text-[11px] font-semibold text-gray-500 uppercase tracking-widest flex items-center gap-2">
                  <Database className="w-3.5 h-3.5" /> Execution Trace
                </h3>
             </div>
             
             <div className="flex-1 overflow-y-auto p-6 relative no-scrollbar">
                <div className="absolute left-[34px] top-8 bottom-8 w-[1px] bg-gray-200"></div>
                <div className="space-y-6 relative">
                  {traceState.map((step, idx) => (
                    <motion.div layout key={step.id} className="flex items-start gap-4 z-10 relative">
                       <div className="mt-0.5 bg-[#FAFAFC]">
                         {step.status === 'done' ? (
                           <div className="w-[18px] h-[18px] rounded-full border border-gray-300 flex items-center justify-center bg-white shadow-sm">
                             <Check className="w-2.5 h-2.5 text-gray-700" strokeWidth={3} />
                           </div>
                         ) : (
                           <div className="w-[18px] h-[18px] flex items-center justify-center">
                             <div className="w-2 h-2 rounded-full bg-gray-900 animate-pulse"></div>
                           </div>
                         )}
                       </div>
                       <div className="flex-1 min-w-0 font-mono text-[13px] pt-px">
                          <div className={`flex justify-between items-baseline ${step.status === 'done' ? 'text-gray-700' : 'text-gray-900 font-semibold'}`}>
                            <span className="truncate pr-2">{step.label}</span>
                            {step.status === 'done' && <span className="text-[11px] text-gray-400 shrink-0">{step.latency}ms</span>}
                          </div>
                          {step.target && (
                            <div className="text-[11px] text-gray-500 mt-0.5 truncate pr-2">
                              {step.target}
                            </div>
                          )}
                       </div>
                    </motion.div>
                  ))}
                </div>
             </div>

             <div className="p-5 border-t border-gray-200/60 bg-white shrink-0 shadow-[0_-2px_10px_rgb(0,0,0,0.02)] z-10">
                <div className="flex items-center justify-between font-mono text-[12px] tracking-wide">
                  <span className="text-gray-500">Eval pass@1</span>
                  <span className="flex items-center gap-2 font-medium text-gray-800">
                    62% <ArrowRight className="w-3.5 h-3.5 text-gray-400" /> <span className="text-gray-900 bg-gray-100 px-1.5 py-0.5 rounded shadow-sm">81%</span>
                  </span>
                </div>
             </div>
          </aside>

          {/* == ASSISTANT PANEL (Right Panel alternate view) == */}
          {scene === 'assistant' && (
            <aside className="w-[360px] shrink-0 border-l border-gray-200/60 bg-[#FAFAFC] flex flex-col hidden lg:flex">
               <div className="h-12 border-b border-gray-200/60 flex items-center px-5 shrink-0 bg-white">
                  <h3 className="text-[11px] font-semibold text-gray-500 uppercase tracking-widest flex items-center gap-2">
                    <CheckCircle2 className="w-3.5 h-3.5" /> To-Do & Skills
                  </h3>
               </div>
               
               <div className="flex-1 overflow-y-auto p-5 space-y-6 text-[14px]">
                 <div>
                   <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3 ml-1">Tasks</div>
                   <div className="space-y-1">
                     <div className="flex items-start gap-3 p-2.5 hover:bg-gray-100/70 rounded-md cursor-pointer transition-colors group">
                       <div className="mt-0.5 w-4 h-4 rounded border border-gray-300 group-hover:border-gray-500 bg-white shadow-sm shrink-0"></div>
                       <span className="text-gray-700 group-hover:text-gray-900 leading-snug">Prepare Q3 strategy slide deck</span>
                     </div>
                     <div className="flex items-start gap-3 p-2.5 rounded-md cursor-pointer opacity-50">
                       <div className="mt-0.5 w-4 h-4 rounded border border-gray-900 bg-gray-900 text-white flex items-center justify-center shrink-0">
                         <Check className="w-3 h-3" />
                       </div>
                       <span className="text-gray-500 line-through leading-snug">Update payment API docs</span>
                     </div>
                   </div>
                 </div>

                 <div>
                   <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3 ml-1">Automations</div>
                   <div className="bg-white border border-gray-200/80 rounded-[12px] p-4 shadow-[0_2px_8px_rgb(0,0,0,0.02)] relative overflow-hidden group hover:border-gray-300 transition-colors cursor-pointer">
                      <div className="absolute left-0 top-0 bottom-0 w-1 bg-gray-900"></div>
                      <div className="flex items-center justify-between mb-1 text-[13px] font-medium text-gray-900 pr-1 pl-2">
                        <span>Daily Report Draft</span>
                        <div className="w-[30px] h-4 bg-gray-900 rounded-full relative shadow-inner">
                           <div className="absolute top-[2px] right-[2px] w-3 h-3 bg-white rounded-full"></div>
                        </div>
                      </div>
                      <div className="text-[12px] text-gray-500 pl-2">Sync repository commits at 08:00 AM</div>
                   </div>
                 </div>
               </div>
            </aside>
          )}

        </div>
      </main>

      {/* 
        ================================================================
        APPROVAL MODAL
        ================================================================
      */}
      <AnimatePresence>
        {simStatus === 'approval' && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[100] flex items-center justify-center bg-gray-900/20 backdrop-blur-sm px-4"
          >
             <motion.div 
                initial={{ opacity: 0, scale: 0.97, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.97, y: 10 }}
                transition={{ type: "spring", bounce: 0, duration: 0.4 }}
                className="w-full max-w-xl bg-white border border-gray-200 rounded-[20px] shadow-2xl flex flex-col overflow-hidden"
             >
                <div className="p-5 border-b border-gray-100 flex items-center gap-3">
                   <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 shrink-0">
                     <Settings className="w-4 h-4" />
                   </div>
                   <div className="font-semibold text-gray-900">Permission Required</div>
                </div>

                <div className="p-6 space-y-6">
                   <div className="flex gap-4 font-mono text-[13px]">
                      <div className="flex-1 bg-[#FAFAFC] border border-gray-200/80 p-3 rounded-xl shadow-sm">
                        <div className="text-[10px] uppercase text-gray-400 tracking-wider mb-1 font-sans font-semibold">Tool</div>
                        <div className="text-gray-900 font-semibold">write_file</div>
                      </div>
                      <div className="flex-[2] bg-[#FAFAFC] border border-gray-200/80 p-3 rounded-xl shadow-sm overflow-hidden">
                        <div className="text-[10px] uppercase text-gray-400 tracking-wider mb-1 font-sans font-semibold">Target File</div>
                        <div className="truncate text-gray-800">src/auth/session.ts</div>
                      </div>
                   </div>

                   <div>
                     <div className="text-[10px] uppercase text-gray-400 tracking-wider mb-2 font-sans font-semibold ml-1">Diff Preview</div>
                     <div className="bg-[#1E1E1E] rounded-xl overflow-hidden font-mono text-[13px] shadow-[inset_0_2px_10px_rgb(0,0,0,0.2)]">
                        <div className="px-4 py-2 border-b border-[#2D2D2D] bg-[#252526] text-gray-400 flex items-center gap-2">
                          <FileCode2 className="w-4 h-4" /> session.ts
                        </div>
                        <div className="p-4 overflow-x-auto leading-relaxed">
                          <div className="text-[#D4D4D4] pl-2">{'  '}// preserve token flag</div>
                          <div className="text-[#F14C4C] bg-[#F14C4C]/10 px-2 -mx-2">{'  '}- sessionStorage.clear();</div>
                          <div className="text-[#23D18B] bg-[#23D18B]/10 px-2 -mx-2">{'  '}+ sessionStorage.removeItem('auth_cache');</div>
                          <div className="text-[#D4D4D4] pl-2">{'  '}return true;</div>
                        </div>
                     </div>
                   </div>

                   <div className="flex gap-2 p-1.5 bg-gray-100 rounded-xl">
                      <label className="flex-1 text-center py-2 px-2 rounded-lg hover:bg-white/50 cursor-pointer text-[13px] font-medium text-gray-500 transition-colors">
                        <input type="radio" name="perm" className="hidden" /> Deny (Read Only)
                      </label>
                      <label className="flex-1 text-center py-2 px-2 rounded-lg bg-white shadow-[0_1px_3px_rgb(0,0,0,0.06)] border border-gray-200/50 cursor-pointer text-[13px] font-medium text-gray-900 transition-colors">
                        <input type="radio" name="perm" className="hidden" defaultChecked /> Ask Confirmation
                      </label>
                      <label className="flex-1 text-center py-2 px-2 rounded-lg hover:bg-white/50 cursor-pointer text-[13px] font-medium text-gray-500 transition-colors">
                        <input type="radio" name="perm" className="hidden" /> Accept All
                      </label>
                   </div>
                </div>

                <div className="p-4 px-6 border-t border-gray-100 bg-[#FAFAFC] flex justify-end gap-3">
                   <button 
                     onClick={() => setSimStatus('idle')} 
                     className="px-5 py-2.5 rounded-[12px] font-medium text-gray-600 hover:bg-gray-200 transition-colors text-[13px]"
                   >
                     Reject
                   </button>
                   <button 
                     onClick={handleApprove} 
                     className="px-6 py-2.5 rounded-[12px] font-medium bg-gray-900 border border-transparent shadow-[0_2px_4px_rgb(0,0,0,0.1)] hover:bg-gray-800 text-white transition-all text-[13px] flex items-center gap-2"
                   >
                     Approve Once
                   </button>
                </div>
             </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
