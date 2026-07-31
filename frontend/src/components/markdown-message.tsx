import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"

/**
 * Shared markdown renderer for assistant messages and scan-detail
 * explanations. Renders via React elements (no innerHTML/XSS surface),
 * with GFM support for tables/strikethrough/task-lists. Raw HTML from
 * model output is rendered as inert text (no rehype-raw).
 *
 * Every style token is reused from the existing design system — no new
 * design language is introduced.
 */

const components: Components = {
  h1: ({ children }) => (
    <h1 className="mb-3 mt-5 text-heading-md text-ink first:mt-0">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2 mt-4 text-heading-sm text-ink first:mt-0">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-3 font-medium text-body-md text-ink first:mt-0">{children}</h3>
  ),
  p: ({ children }) => (
    <p className="mb-2 last:mb-0">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li>{children}</li>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-link underline underline-offset-2 hover:text-accent-blue"
    >
      {children}
    </a>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-ink">{children}</strong>
  ),
  em: ({ children }) => <em>{children}</em>,
  blockquote: ({ children }) => (
    <blockquote className="mb-2 border-l-2 border-hairline-strong pl-3 text-charcoal last:mb-0">
      {children}
    </blockquote>
  ),
  code: ({ className, children }) => {
    // Fenced code blocks get a `language-*` className from react-markdown.
    const isFenced = typeof className === "string" && className.startsWith("language-")
    if (isFenced) {
      return (
        <code className="block text-code-md">{children}</code>
      )
    }
    // Inline code
    return (
      <code className="rounded bg-surface-elevated px-1.5 py-0.5 text-code-md text-charcoal">
        {children}
      </code>
    )
  },
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded-lg border border-hairline bg-surface-elevated p-3 last:mb-0">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto last:mb-0">
      <table className="w-full border-collapse text-body-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="border-b border-hairline-strong">{children}</thead>
  ),
  th: ({ children }) => (
    <th className="px-3 py-2 text-left text-caption font-medium text-charcoal">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-t border-hairline px-3 py-2">{children}</td>
  ),
  hr: () => <hr className="my-4 border-hairline" />,
}

export function MarkdownMessage({ content }: { content: string }) {
  if (!content) return null
  return (
    <div className="prose-wardress text-body-md leading-relaxed text-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
