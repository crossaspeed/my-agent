import { useMemo, type ReactNode } from 'react'

interface Props {
  text: string
  className?: string
}

type Block =
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'code'; lang: string; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'quote'; text: string }
  | { kind: 'table'; header: string[]; rows: string[][] }
  | { kind: 'divider' }

const FENCE = /^```(\w*)\s*$/

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function parse(src: string): Block[] {
  const lines = src.replace(/\r\n/g, '\n').split('\n')
  const blocks: Block[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) {
      i += 1
      continue
    }
    const fence = line.match(FENCE)
    if (fence) {
      const lang = fence[1] ?? ''
      const buf: string[] = []
      i += 1
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        buf.push(lines[i])
        i += 1
      }
      i += 1
      blocks.push({ kind: 'code', lang, text: buf.join('\n') })
      continue
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2].trim() })
      i += 1
      continue
    }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      blocks.push({ kind: 'divider' })
      i += 1
      continue
    }
    if (/^\s*>/.test(line)) {
      const buf: string[] = []
      while (i < lines.length && /^\s*>/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ''))
        i += 1
      }
      blocks.push({ kind: 'quote', text: buf.join(' ') })
      continue
    }
    if (/^\s*\|.+\|\s*$/.test(line) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] ?? '')) {
      const header = splitRow(line)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && /^\s*\|.+\|\s*$/.test(lines[i])) {
        rows.push(splitRow(lines[i]))
        i += 1
      }
      blocks.push({ kind: 'table', header, rows })
      continue
    }
    const listMatch = line.match(/^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$/)
    if (listMatch) {
      const ordered = Boolean(listMatch[2])
      const items: string[] = []
      while (i < lines.length) {
        const m = lines[i].match(/^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$/)
        if (!m || Boolean(m[2]) !== ordered) break
        items.push(m[3])
        i += 1
      }
      blocks.push({ kind: 'list', ordered, items })
      continue
    }
    const buf: string[] = []
    while (
      i < lines.length &&
      lines[i].trim() &&
      !FENCE.test(lines[i]) &&
      !/^(#{1,6})\s+/.test(lines[i]) &&
      !/^\s*>/.test(lines[i]) &&
      !/^\s*(?:([-*+])|(\d+)[.)])\s+/.test(lines[i])
    ) {
      buf.push(lines[i])
      i += 1
    }
    blocks.push({ kind: 'paragraph', text: buf.join(' ') })
  }
  return blocks
}

/** 行内语法：**粗体**、*斜体*、`代码`、$公式$ 保留原样 */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const regex = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g
  let last = 0
  let match: RegExpExecArray | null
  let idx = 0
  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    const token = match[0]
    const key = `${keyPrefix}-i${idx++}`
    if (token.startsWith('**')) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('`')) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>)
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>)
    }
    last = match.index + token.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

/** 轻量 Markdown 渲染（不引入额外依赖，禁止 dangerouslySetInnerHTML） */
export default function MarkdownView({ text, className }: Props) {
  const blocks = useMemo(() => parse(text ?? ''), [text])
  return (
    <div className={`md-view${className ? ` ${className}` : ''}`}>
      {blocks.map((block, index) => {
        const key = `b${index}`
        switch (block.kind) {
          case 'heading': {
            const Tag = `h${Math.min(block.level + 1, 6)}` as 'h2'
            return (
              <Tag key={key} className="md-heading">
                {inline(block.text, key)}
              </Tag>
            )
          }
          case 'code':
            return (
              <pre key={key} className="md-code">
                <code>{block.text}</code>
              </pre>
            )
          case 'list': {
            const ListTag = block.ordered ? 'ol' : 'ul'
            return (
              <ListTag key={key} className="md-list">
                {block.items.map((item, i) => (
                  <li key={`${key}-${i}`}>{inline(item, `${key}-${i}`)}</li>
                ))}
              </ListTag>
            )
          }
          case 'quote':
            return (
              <blockquote key={key} className="md-quote">
                {inline(block.text, key)}
              </blockquote>
            )
          case 'table':
            return (
              <table key={key} className="md-table">
                <thead>
                  <tr>
                    {block.header.map((cell, i) => (
                      <th key={`${key}-h${i}`}>{cell}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, ri) => (
                    <tr key={`${key}-r${ri}`}>
                      {row.map((cell, ci) => (
                        <td key={`${key}-r${ri}c${ci}`}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          case 'divider':
            return <hr key={key} className="md-divider" />
          default:
            return (
              <p key={key} className="md-paragraph">
                {inline(block.text, key)}
              </p>
            )
        }
      })}
    </div>
  )
}
