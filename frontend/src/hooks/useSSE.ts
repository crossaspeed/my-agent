// 导学 SSE：后端是 POST + Authorization，EventSource 无法带 Header，故用 fetch + 手工解析帧
import { useCallback, useRef } from 'react'
import { API_BASE, tokenStore } from '@/api/client'
import type { SSEHandlers } from '@/api/types'

function parseFrame(frame: string): { event: string; data: string } | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const rawLine of frame.split('\n')) {
    const line = rawLine.trimEnd()
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return null
  return { event, data: dataLines.join('\n') }
}

export function useSSEStream() {
  const abortRef = useRef<AbortController | null>(null)

  const send = useCallback(
    async (sessionId: number, content: string, handlers: SSEHandlers) => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      const token = tokenStore.get()
      const resp = await fetch(`${API_BASE}/tutor/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ content }),
        signal: controller.signal,
      })
      if (!resp.ok || !resp.body) {
        handlers.onError?.({ code: resp.status, message: `流式请求失败（HTTP ${resp.status}）` })
        return
      }
      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      try {
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let idx = buffer.indexOf('\n\n')
          while (idx >= 0) {
            const frame = buffer.slice(0, idx)
            buffer = buffer.slice(idx + 2)
            const parsed = parseFrame(frame)
            if (parsed) {
              const payload = safeParse(parsed.data)
              if (payload) dispatch(parsed.event, payload, handlers)
            }
            idx = buffer.indexOf('\n\n')
          }
        }
      } catch (error) {
        if ((error as Error).name !== 'AbortError') {
          handlers.onError?.({ code: 5000, message: (error as Error).message })
        }
      }
    },
    [],
  )

  const abort = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  return { send, abort }
}

function safeParse(text: string): Record<string, unknown> | null {
  try {
    return JSON.parse(text) as Record<string, unknown>
  } catch {
    return null
  }
}

function dispatch(event: string, data: Record<string, unknown>, handlers: SSEHandlers) {
  switch (event) {
    case 'meta':
      handlers.onMeta?.(data as never)
      break
    case 'token':
      handlers.onToken?.(String(data.delta ?? ''))
      break
    case 'refs':
      handlers.onRefs?.(data as never)
      break
    case 'done':
      handlers.onDone?.(data as never)
      break
    case 'error':
      handlers.onError?.(data as never)
      break
    default:
      break
  }
}
