import { ApiError, requestEventStream, requestJson, type ServerSentEvent } from './http'
import type { AgentChatData, AgentUIContext } from '../types/api'

export class AgentClient {
  constructor(private readonly getUserId: () => string) {}

  chat(message: string, externalConversationId: string, externalMessageId: string) {
    return requestJson<AgentChatData>('/demo-api/agent-chat', {
      method: 'POST',
      body: JSON.stringify({
        platform_user_id: this.getUserId(), message,
        external_conversation_id: externalConversationId,
        external_message_id: externalMessageId,
      }),
    }, 320000)
  }

  async chatStream(
    message: string,
    externalConversationId: string,
    externalMessageId: string,
    onEvent: (event: ServerSentEvent) => void,
    signal?: AbortSignal,
    uiContext?: AgentUIContext,
  ): Promise<AgentChatData> {
    let completed: AgentChatData | null = null
    let streamError: ApiError | null = null
    await requestEventStream('/demo-api/agent-chat/stream', {
      method: 'POST',
      body: JSON.stringify({
        platform_user_id: this.getUserId(), message,
        external_conversation_id: externalConversationId,
        external_message_id: externalMessageId,
        ui_context: uiContext,
      }),
    }, (event) => {
      onEvent(event)
      const payload = event.data as Record<string, any>
      if (event.event === 'completed') completed = payload.data as AgentChatData
      if (event.event === 'error') {
        streamError = new ApiError(String(payload.message || '智能助手暂时不可用'), String(payload.code || 'AGENT_ERROR'), 0, payload.trace_id)
      }
    }, 340000, signal)
    if (streamError) throw streamError
    if (!completed) throw new ApiError('智能助手连接提前结束，请重试', 'STREAM_INCOMPLETE')
    return completed
  }

  decide(action: 'confirm' | 'cancel', conversationId: number, actionId: string, confirmationToken: string) {
    return requestJson<Record<string, any>>(`/demo-api/agent-actions/${action}`, {
      method: 'POST',
      body: JSON.stringify({
        platform_user_id: this.getUserId(), conversation_id: conversationId,
        action_id: actionId, confirmation_token: confirmationToken,
      }),
    }, 60000)
  }
}
