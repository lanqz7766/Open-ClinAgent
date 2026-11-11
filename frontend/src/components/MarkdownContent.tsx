type MarkdownContentProps = {
  content: string
  className?: string
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;")
}

function renderInline(line: string) {
  return escapeHtml(line)
    .replace(
      /\[([^\]]+)\]\(((?:https?:\/\/|\/)[^)]+)\)/g,
      (_match, label: string, href: string) =>
        `<a class="break-all text-[hsl(var(--primary))] underline underline-offset-2" href="${href}"${href.startsWith("/") ? "" : ' target="_blank" rel="noreferrer"'}>${label}</a>`,
    )
    .replace(/`([^`]+)`/g, '<code class="break-all rounded bg-[hsl(var(--muted))] px-1 py-0.5 font-mono text-[11px] text-[hsl(var(--foreground))]">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/(https?:\/\/[^\s<]+)/g, '<a class="break-all text-[hsl(var(--primary))] underline underline-offset-2" href="$1" target="_blank" rel="noreferrer">$1</a>')
}

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  const lines = content.split("\n")
  const blocks: string[] = []
  let paragraphBuffer: string[] = []
  let orderedListBuffer: string[] = []
  let unorderedListBuffer: string[] = []

  const flushParagraphs = () => {
    if (!paragraphBuffer.length) {
      return
    }
    blocks.push(`<p>${paragraphBuffer.map(renderInline).join("<br/>")}</p>`)
    paragraphBuffer = []
  }

  const flushOrdered = () => {
    if (!orderedListBuffer.length) {
      return
    }
    blocks.push(`<ol>${orderedListBuffer.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ol>`)
    orderedListBuffer = []
  }

  const flushUnordered = () => {
    if (!unorderedListBuffer.length) {
      return
    }
    blocks.push(`<ul>${unorderedListBuffer.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`)
    unorderedListBuffer = []
  }

  const flushAll = () => {
    flushParagraphs()
    flushOrdered()
    flushUnordered()
  }

  lines.forEach((rawLine) => {
    const line = rawLine.trim()
    if (!line) {
      flushAll()
      return
    }

    const orderedMatch = line.match(/^\d+\.\s+(.+)$/)
    if (orderedMatch) {
      flushParagraphs()
      flushUnordered()
      orderedListBuffer.push(orderedMatch[1])
      return
    }

    const unorderedMatch = line.match(/^[-*]\s+(.+)$/)
    if (unorderedMatch) {
      flushParagraphs()
      flushOrdered()
      unorderedListBuffer.push(unorderedMatch[1])
      return
    }

    if (line.startsWith("### ")) {
      flushAll()
      blocks.push(`<h3>${renderInline(line.slice(4))}</h3>`)
      return
    }

    if (line.startsWith("## ")) {
      flushAll()
      blocks.push(`<h2>${renderInline(line.slice(3))}</h2>`)
      return
    }

    if (line.startsWith("# ")) {
      flushAll()
      blocks.push(`<h1>${renderInline(line.slice(2))}</h1>`)
      return
    }

    flushOrdered()
    flushUnordered()
    paragraphBuffer.push(line)
  })

  flushAll()

  return (
    <div
      className={["prose-clinagent min-w-0 text-[13px] leading-6 text-[hsl(var(--foreground))] [overflow-wrap:anywhere]", className].filter(Boolean).join(" ")}
      dangerouslySetInnerHTML={{ __html: blocks.join("") }}
    />
  )
}
