import type { ApiEnvelope } from '../types/api'
import { businessErrorMessage } from '../constants/business'

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code = 'REQUEST_FAILED',
    public readonly status = 0,
    public readonly traceId?: string,
  ) { super(message) }
}

export async function requestJson<T>(url: string, init: RequestInit, timeoutMs = 30000): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    })
    const payload = await response.json().catch(() => null) as ApiEnvelope<T> | null
    if (!response.ok || !payload || payload.success === false) {
      throw new ApiError(
        businessErrorMessage(payload?.code, payload?.message, payload?.data),
        payload?.code,
        response.status,
        payload?.trace_id,
      )
    }
    return payload.data
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('请求超时，请稍后重试', 'REQUEST_TIMEOUT')
    }
    throw new ApiError('服务暂时不可用，请检查本地服务状态', 'NETWORK_ERROR')
  } finally {
    window.clearTimeout(timer)
  }
}

export interface ServerSentEvent<T = unknown> {
  event: string
  data: T
}

export async function requestEventStream(
  url: string,
  init: RequestInit,
  onEvent: (event: ServerSentEvent) => void,
  timeoutMs = 340000,
  externalSignal?: AbortSignal,
): Promise<void> {
  const controller = new AbortController()
  let timedOut = false
  const abortFromExternal = () => controller.abort()
  externalSignal?.addEventListener('abort', abortFromExternal, { once: true })
  const timer = window.setTimeout(() => { timedOut = true; controller.abort() }, timeoutMs)
  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...init.headers },
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as ApiEnvelope<unknown> | null
      throw new ApiError(
        businessErrorMessage(payload?.code, payload?.message, payload?.data),
        payload?.code,
        response.status,
        payload?.trace_id,
      )
    }
    if (!response.body) throw new ApiError('智能助手未返回流式响应', 'STREAM_UNAVAILABLE')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    const dispatch = (block: string) => {
      let eventName = 'message'
      const dataLines: string[] = []
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim()
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
      }
      if (!dataLines.length) return
      const raw = dataLines.join('\n')
      let data: unknown
      try { data = JSON.parse(raw) } catch { throw new ApiError('智能助手返回了无效流式事件', 'STREAM_PROTOCOL_ERROR') }
      onEvent({ event: eventName, data })
    }
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() || ''
      blocks.forEach(dispatch)
    }
    buffer += decoder.decode()
    if (buffer.trim()) dispatch(buffer)
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (timedOut) throw new ApiError('智能助手处理超时，请缩小问题范围后重试', 'REQUEST_TIMEOUT')
      throw new ApiError('本次回答已取消', 'REQUEST_CANCELLED')
    }
    throw new ApiError('智能助手连接中断，请稍后重试', 'NETWORK_ERROR')
  } finally {
    window.clearTimeout(timer)
    externalSignal?.removeEventListener('abort', abortFromExternal)
  }
}
