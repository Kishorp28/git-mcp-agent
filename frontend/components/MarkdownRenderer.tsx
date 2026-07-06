"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";

interface MarkdownRendererProps {
  content: string;
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  if (!content) return null;

  return (
    <div className="prose-chat">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // ── Code blocks ────────────────────────────────────────────────
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || "");
            const code = String(children).replace(/\n$/, "");

            if (match) {
              return (
                <SyntaxHighlighter
                  style={vscDarkPlus}
                  language={match[1]}
                  PreTag="div"
                  customStyle={{
                    margin: "0.5rem 0",
                    borderRadius: "0.5rem",
                    fontSize: "0.82rem",
                    lineHeight: "1.6",
                    border: "1px solid #1e293b",
                  }}
                  wrapLongLines={false}
                >
                  {code}
                </SyntaxHighlighter>
              );
            }
            // Inline code
            return (
              <code className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-sm text-blue-300" {...props}>
                {children}
              </code>
            );
          },

          // ── Paragraphs ─────────────────────────────────────────────────
          p({ children }) {
            return <p className="mb-2 leading-relaxed last:mb-0">{children}</p>;
          },

          // ── Lists ──────────────────────────────────────────────────────
          ul({ children }) {
            return <ul className="mb-2 list-disc pl-5 space-y-0.5">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="mb-2 list-decimal pl-5 space-y-0.5">{children}</ol>;
          },
          li({ children }) {
            return <li className="leading-relaxed">{children}</li>;
          },

          // ── Headings ───────────────────────────────────────────────────
          h1({ children }) {
            return <h1 className="mb-2 mt-1 text-lg font-bold text-slate-100">{children}</h1>;
          },
          h2({ children }) {
            return <h2 className="mb-1.5 mt-1 text-base font-semibold text-slate-100">{children}</h2>;
          },
          h3({ children }) {
            return <h3 className="mb-1 mt-1 text-sm font-semibold text-slate-200">{children}</h3>;
          },

          // ── Links ──────────────────────────────────────────────────────
          a({ href, children }) {
            return (
              <a
                href={href}
                className="text-blue-400 underline decoration-blue-400/40 underline-offset-2 hover:text-blue-300 hover:decoration-blue-300/60"
                target="_blank"
                rel="noopener noreferrer"
              >
                {children}
              </a>
            );
          },

          // ── Blockquote ────────────────────────────────────────────────
          blockquote({ children }) {
            return (
              <blockquote className="my-2 border-l-2 border-slate-600 pl-3 text-slate-400 italic">
                {children}
              </blockquote>
            );
          },

          // ── Table ─────────────────────────────────────────────────────
          table({ children }) {
            return (
              <div className="my-2 overflow-x-auto rounded-lg border border-slate-700">
                <table className="min-w-full text-xs">{children}</table>
              </div>
            );
          },
          thead({ children }) {
            return <thead className="bg-slate-800/80">{children}</thead>;
          },
          th({ children }) {
            return (
              <th className="border-b border-slate-700 px-3 py-1.5 text-left font-semibold text-slate-200">
                {children}
              </th>
            );
          },
          td({ children }) {
            return (
              <td className="border-b border-slate-800 px-3 py-1.5 text-slate-300">
                {children}
              </td>
            );
          },

          // ── Horizontal rule ───────────────────────────────────────────
          hr() {
            return <hr className="my-3 border-slate-700" />;
          },

          // ── Strong / Em ───────────────────────────────────────────────
          strong({ children }) {
            return <strong className="font-semibold text-slate-100">{children}</strong>;
          },
          em({ children }) {
            return <em className="italic text-slate-300">{children}</em>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
