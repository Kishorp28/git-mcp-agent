"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

interface MarkdownRendererProps {
  content: string;
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || "");
          const code = String(children).replace(/\n$/, "");
          if (match) {
            return (
              <SyntaxHighlighter
                style={oneDark}
                language={match[1]}
                PreTag="div"
                customStyle={{
                  margin: "0.5rem 0",
                  borderRadius: "0.5rem",
                  fontSize: "0.85rem",
                }}
              >
                {code}
              </SyntaxHighlighter>
            );
          }
          return (
            <code
              className="rounded bg-slate-800 px-1.5 py-0.5 text-sm text-blue-300"
              {...props}
            >
              {children}
            </code>
          );
        },
        p({ children }) {
          return <p className="mb-2 leading-relaxed last:mb-0">{children}</p>;
        },
        ul({ children }) {
          return <ul className="mb-2 list-disc pl-5">{children}</ul>;
        },
        ol({ children }) {
          return <ol className="mb-2 list-decimal pl-5">{children}</ol>;
        },
        h1({ children }) {
          return <h1 className="mb-2 text-xl font-bold">{children}</h1>;
        },
        h2({ children }) {
          return <h2 className="mb-2 text-lg font-semibold">{children}</h2>;
        },
        h3({ children }) {
          return <h3 className="mb-1 text-base font-semibold">{children}</h3>;
        },
        a({ href, children }) {
          return (
            <a
              href={href}
              className="text-blue-400 underline hover:text-blue-300"
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
