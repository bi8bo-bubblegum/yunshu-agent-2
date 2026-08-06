// frontend/src/api/chat.ts —— SSE 流式消费
import client from './client'

export type SSEEvent = {
  event: string
  content?: string
  trace_id?: string
  tool?: string
  args?: Record<string, unknown>
  reason?: string
  approval_id?: string
  stage?: string
  [k: string]: unknown
}

/**
 * 消费 /api/chat/completions 的 SSE 流。
 * 返回 Promise，结束时 resolve；通过 onEvent 回调接收每个事件。
 */
export async function streamChat(
  conversationId: string,
  message: string,
  onEvent: (e: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch('/api/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem('token') ?? ''}`,
    },
    body: JSON.stringify({ conversation_id: conversationId, message }),
    signal,
  })
  if (!resp.ok || !resp.body) throw new Error(`chat 请求失败: ${resp.status}`)
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? ''
    for (const part of parts) {
      const line = part.split('\n').find(l => l.startsWith('data: '))
      if (line) {
        try {
          onEvent(JSON.parse(line.slice(6)) as SSEEvent)
        } catch { /* 忽略坏帧 */ }
      }
    }
  }
}

/** high 风险工具即时确认后恢复图执行 */
export async function resumeChat(conversationId: string, approved: boolean) {
  return client.post('/chat/resume', { conversation_id: conversationId, approved })
}
