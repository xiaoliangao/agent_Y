import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// 助手回复按 Markdown 渲染（标题/列表/代码/表格/链接…）。样式见 index.css 的 .md。
export default function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ a: (props) => <a {...props} target="_blank" rel="noreferrer" /> }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
