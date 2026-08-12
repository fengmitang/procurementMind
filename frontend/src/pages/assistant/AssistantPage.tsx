import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Actions, Bubble, Conversations, Prompts, Sender, Sources, Welcome } from '@ant-design/x'
import { Alert, App, Avatar, Button, Card, Descriptions, Space, Spin, Tag, Typography } from 'antd'
import { CopyOutlined, FileTextOutlined, MessageOutlined, PlusOutlined, RobotOutlined, ToolOutlined, UserOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import ReactMarkdown from 'react-markdown'
import { useNavigate } from 'react-router-dom'
import { useIdentity } from '../../features/identity/IdentityProvider'
import { enumLabel, fieldLabel, localizeBusinessText } from '../../constants/business'
import type { AgentChatData, AgentMessage, BusinessResult, KnowledgeSource, PendingAction } from '../../types/api'
import './AssistantPage.css'

interface Conversation {
  key: string
  label: string
  externalId: string
  backendId?: number
  messages: AgentMessage[]
  loaded: boolean
}

const newConversation = (): Conversation => ({
  key: crypto.randomUUID(), label: '新会话', externalId: `web-${crypto.randomUUID()}`, messages: [], loaded: true,
})

const prompts = [
  { key: 'knowledge', icon: <FileTextOutlined />, label: '采购申请被驳回后应该怎么办？', description: '查询制度与流程规则' },
  { key: 'realtime', icon: <ToolOutlined />, label: '我的采购申请目前进展怎么样？', description: '读取实时采购数据' },
  { key: 'draft', icon: <MessageOutlined />, label: '我要采购一批浪潮服务器', description: '创建采购申请草稿' },
]

const toolLabels: Record<string, string> = {
  get_purchase_request: '采购单实时信息', search_purchase_records: '采购申请查询',
  get_similar_cases: '历史采购记录', get_supplier_performance: '供应商履约记录',
  get_requirement_risk_signals: '采购风险信息', query_purchase_analytics: '采购统计数据',
}

function BusinessFields({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value).filter(([key, item]) =>
    !key.endsWith('_id') && !['status', 'source_message'].includes(key) && item != null
    && ['string', 'number', 'boolean'].includes(typeof item),
  )
  if (!entries.length) return <Typography.Text type="secondary">暂无已填写字段</Typography.Text>
  return <Descriptions size="small" column={1} items={entries.map(([key, item]) => ({
    key, label: fieldLabel(key), children: String(enumLabel(item) ?? '—'),
  }))} />
}

function HitlCard({ action, conversationId, onDone }: { action: PendingAction; conversationId: number; onDone: (text: string) => void }) {
  const { agent } = useIdentity(); const { message } = App.useApp(); const [loading, setLoading] = useState(false)
  const isDraft = action.action_type === 'CREATE_PURCHASE_DRAFT'
  const decide = async (type: 'confirm' | 'cancel') => {
    setLoading(true)
    try {
      const result = await agent.decide(type, conversationId, action.action_id, action.confirmation_token)
      const detail = result.result as Record<string, unknown> | undefined
      const text = type === 'confirm'
        ? isDraft ? `采购申请草稿已创建${detail?.requirement_no ? `：${detail.requirement_no}` : ''}，尚未提交审批。` : '操作已确认，正式结果已由后端校验。'
        : '已取消本次操作。'
      message.success(text); onDone(text)
    } catch (err) { message.error(err instanceof Error ? err.message : '操作失败') } finally { setLoading(false) }
  }
  return <Card className="hitl-card" title={isDraft ? '待确认的采购申请草稿' : '需要你确认的正式操作'} size="small">
    <Typography.Paragraph>{isDraft ? '请核对以下内容。确认后只创建草稿，不会提交审批。' : action.title || action.summary || '请核对后确认。'}</Typography.Paragraph>
    {action.draft && <BusinessFields value={action.draft as Record<string, unknown>} />}
    <Space><Button type="primary" loading={loading} onClick={() => decide('confirm')}>{isDraft ? '创建草稿' : '确认执行'}</Button><Button disabled={loading} onClick={() => decide('cancel')}>取消</Button></Space>
  </Card>
}

function BusinessResultCards({ groups }: { groups: BusinessResult[] }) {
  const navigate = useNavigate()
  return <>{groups.map((group, groupIndex) => <Card key={`${group.kind}-${groupIndex}`} size="small" className="business-result-card" title={`${group.title}${group.total != null ? `（${group.total}）` : ''}`}>
    <div className="business-result-list">{group.items.map((item, index) => {
      if (group.kind === 'PURCHASE_REQUIREMENTS' || group.kind === 'PURCHASE_HISTORY') return <button className="business-result-item" key={String(item.requirement_no || index)} onClick={() => navigate(`/requirements/${item.requirement_id}`)}>
        <div className="business-result-heading"><strong>{item.requirement_no}</strong><Tag color="blue">{String(enumLabel(item.status) || '—')}</Tag></div>
        <div className="business-result-grid"><span>设备：{item.device_name || '—'}{item.brand ? ` · ${item.brand}` : ''}</span><span>数量：{item.quantity ?? '—'} {item.unit || ''}</span><span>发起时间：{item.created_at ? dayjs(item.created_at).format('YYYY-MM-DD HH:mm') : '—'}</span><span>当前处理人：{item.current_handler_name || '暂无'}</span></div>
        <Typography.Text type="secondary">点击查看采购详情</Typography.Text>
      </button>
      return <div className="business-result-item static" key={String(item.supplier_id || index)}><strong>{item.supplier_name || `供应商 ${index + 1}`}</strong></div>
    })}</div>
  </Card>)}</>
}

function AssistantContent({ message, onHitlDone }: { message: AgentMessage; onHitlDone: (text: string) => void }) {
  const data = message.data; const sources = data?.knowledge_sources || []; const tools = data?.execution?.tools || []
  if (message.status === 'loading') return <div className="assistant-answer">{message.content && <ReactMarkdown>{localizeBusinessText(message.content)}</ReactMarkdown>}<Typography.Text type="secondary">{message.streamStatus || '正在理解你的问题'}</Typography.Text></div>
  if (message.status === 'error') return <Alert type="error" showIcon title="本次回答失败" description={message.error} />
  return <div className="assistant-answer"><ReactMarkdown>{localizeBusinessText(message.content)}</ReactMarkdown>
    {(data?.business_results?.length || 0) > 0 && <BusinessResultCards groups={data!.business_results!} />}
    {data?.form_draft && !data.pending_action && <Card size="small" className="draft-progress-card" title="采购申请草稿（未提交）"><BusinessFields value={data.form_draft} /></Card>}
    {(data?.tool_call_count || 0) > 0 && <Card size="small" className="tool-card" title={<Space><ToolOutlined />已查询业务系统 <Tag color="blue">{data?.tool_call_count} 次</Tag></Space>}>
      {tools.length ? tools.map((tool, index) => { const name = String(tool.tool_name || tool.name || ''); return <div className="tool-row" key={index}><strong>{toolLabels[name] || `业务查询 ${index + 1}`}</strong><span>已完成</span></div> }) : <Typography.Text type="secondary">查询结果已用于本次回答。</Typography.Text>}
    </Card>}
    {sources.length > 0 && <Sources title={`参考来源（${sources.length}）`} defaultExpanded items={sources.map((item: KnowledgeSource, index: number) => ({ key: index, title: item.title || `来源 ${index + 1}`, description: item.section_path?.join(' / ') || '采购制度' }))} />}
    {data?.pending_action && <HitlCard action={data.pending_action} conversationId={data.conversation_id} onDone={onHitlDone} />}
    <Actions items={[{ key: 'copy', label: '复制回答', icon: <CopyOutlined />, onItemClick: () => void navigator.clipboard.writeText(message.content) }]} />
  </div>
}

export function AssistantPage() {
  const { agent, backend, user, platformUserId } = useIdentity(); const { message: toast } = App.useApp()
  const [conversations, setConversations] = useState<Conversation[]>([]); const [activeKey, setActiveKey] = useState('')
  const [loadingHistory, setLoadingHistory] = useState(true); const [busy, setBusy] = useState(false); const [input, setInput] = useState('')
  const activeRequest = useRef<AbortController | null>(null); const scrollRef = useRef<HTMLDivElement | null>(null); const stickToBottom = useRef(true)
  const active = conversations.find((item) => item.key === activeKey) || conversations[0]

  const updateConversation = useCallback((key: string, fn: (value: Conversation) => Conversation) => {
    setConversations((list) => list.map((item) => item.key === key ? fn(item) : item))
  }, [])

  const loadMessages = useCallback(async (conversation: Conversation) => {
    if (!conversation.backendId || conversation.loaded) return
    try {
      const response = await backend.agentMessages(conversation.backendId)
      const messages: AgentMessage[] = response.items.filter((item) => item.sender_type !== 'SYSTEM').map((item) => ({
        id: `stored-${item.message_id}`, role: item.sender_type === 'USER' ? 'user' : 'assistant', content: item.content,
        createdAt: item.created_at, status: 'success', data: item.message_data as AgentChatData | undefined,
      }))
      updateConversation(conversation.key, (value) => ({ ...value, messages, loaded: true }))
      stickToBottom.current = true
    } catch (err) { toast.error(err instanceof Error ? err.message : '历史消息加载失败') }
  }, [backend, toast, updateConversation])

  useEffect(() => {
    let canceled = false
    setLoadingHistory(true)
    void backend.agentConversations().then((response) => {
      if (canceled) return
      if (!response.items.length) {
        const first = newConversation(); setConversations([first]); setActiveKey(first.key); return
      }
      const items = response.items.map((item): Conversation => ({
        key: String(item.conversation_id), label: item.title, externalId: item.external_conversation_id || `web-restored-${item.conversation_id}`,
        backendId: item.conversation_id, messages: [], loaded: false,
      }))
      const saved = sessionStorage.getItem(`assistant-active:${platformUserId}`)
      const selected = items.find((item) => item.key === saved) || items[0]
      setConversations(items); setActiveKey(selected.key)
    }).catch((err) => toast.error(err instanceof Error ? err.message : '会话列表加载失败')).finally(() => { if (!canceled) setLoadingHistory(false) })
    return () => { canceled = true; activeRequest.current?.abort() }
  }, [backend, platformUserId, toast])

  useEffect(() => { if (active) { sessionStorage.setItem(`assistant-active:${platformUserId}`, active.key); void loadMessages(active) } }, [active, loadMessages, platformUserId])
  useEffect(() => {
    const element = scrollRef.current
    if (element && stickToBottom.current) element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' })
  }, [active?.messages])

  const newChat = () => { const next = newConversation(); setConversations((list) => [next, ...list]); setActiveKey(next.key); stickToBottom.current = true }
  const submit = async (raw: string) => {
    const content = raw.trim(); if (!content || busy || !active) return
    const conversationKey = active.key; setInput(''); stickToBottom.current = true
    const userMessage: AgentMessage = { id: crypto.randomUUID(), role: 'user', content, createdAt: new Date().toISOString(), status: 'success' }
    const loadingId = crypto.randomUUID()
    updateConversation(conversationKey, (value) => ({ ...value, label: value.messages.length ? value.label : content.slice(0, 30), messages: [...value.messages, userMessage, { id: loadingId, role: 'assistant', content: '', createdAt: new Date().toISOString(), status: 'loading', originalPrompt: content }] }))
    setBusy(true)
    try {
      const controller = new AbortController(); activeRequest.current = controller
      const result = await agent.chatStream(content, active.externalId, `web-${crypto.randomUUID()}`, (event) => {
        const payload = event.data as Record<string, any>
        if (event.event === 'conversation_started') updateConversation(conversationKey, (value) => ({ ...value, backendId: Number(payload.conversation_id) }))
        if (['thinking', 'retrieving_knowledge', 'querying_business_data', 'analyzing'].includes(event.event)) updateConversation(conversationKey, (value) => ({ ...value, messages: value.messages.map((item) => item.id === loadingId ? { ...item, streamStatus: String(payload.message || '正在处理') } : item) }))
        if (event.event === 'answer_delta') updateConversation(conversationKey, (value) => ({ ...value, messages: value.messages.map((item) => item.id === loadingId ? { ...item, content: item.content + String(payload.delta || ''), streamStatus: '正在核对回答依据' } : item) }))
      }, controller.signal)
      updateConversation(conversationKey, (value) => ({ ...value, backendId: result.conversation_id, messages: value.messages.map((item) => item.id === loadingId ? { ...item, content: result.reply, status: 'success', streamStatus: undefined, data: result } : item) }))
    } catch (err) {
      const error = err instanceof Error ? err.message : '智能助手暂时不可用'
      updateConversation(conversationKey, (value) => ({ ...value, messages: value.messages.map((item) => item.id === loadingId ? { ...item, status: 'error', error } : item) }))
      if (error !== '本次回答已取消') toast.error(error)
    } finally { activeRequest.current = null; setBusy(false) }
  }

  const bubbleItems = useMemo(() => (active?.messages || []).map((item) => ({ key: item.id, role: item.role === 'assistant' ? 'ai' : 'user', status: item.status, content: item.content || '处理中', extraInfo: { item } })), [active?.messages])
  if (loadingHistory) return <div className="assistant-page assistant-loading"><Spin description="正在恢复会话" /></div>
  return <div className="assistant-page"><aside className="conversation-panel"><div className="conversation-brand"><RobotOutlined /><div><strong>智能采购助手</strong><span>会话由业务系统保存</span></div></div><Conversations creation={{ label: '新建会话', icon: <PlusOutlined />, onClick: newChat }} activeKey={activeKey} onActiveChange={(key) => setActiveKey(String(key))} items={conversations.map((item, index) => ({ key: item.key, label: item.label, group: index === 0 ? '最近' : '历史会话' }))} groupable /></aside>
    <section className="chat-panel"><div className="chat-header"><div><strong>智能采购助手</strong><span>{active?.label || '新会话'} · {user.name}</span></div><Tag color="processing">在线</Tag></div>
      <div className="message-scroll" ref={scrollRef} onScroll={(event) => { const target = event.currentTarget; stickToBottom.current = target.scrollHeight - target.scrollTop - target.clientHeight < 100 }}>
        {!active?.loaded ? <div className="center-state"><Spin description="正在加载消息" /></div> : !active.messages.length ? <div className="assistant-welcome"><Welcome icon={<Avatar size={50} icon={<RobotOutlined />} />} title="你好，我是采购智能助手" description="我可以查询采购规则和真实业务进度，也可以协助整理采购申请草稿。正式操作都会先请你确认。" /><Prompts title="你可以这样问" items={prompts} wrap onItemClick={({ data }) => submit(String(data.label))} /></div> : <Bubble.List items={bubbleItems} role={{ user: { placement: 'end', avatar: <Avatar icon={<UserOutlined />} />, variant: 'filled' }, ai: { placement: 'start', avatar: <Avatar icon={<RobotOutlined />} />, variant: 'outlined', contentRender: (_, info) => { const item = info.extraInfo?.item as AgentMessage; return <AssistantContent message={item} onHitlDone={(text) => updateConversation(active.key, (value) => ({ ...value, messages: [...value.messages, { id: crypto.randomUUID(), role: 'assistant', content: text, createdAt: new Date().toISOString(), status: 'success' }] }))} /> } } }} />}
      </div>
      <div className="sender-wrap"><Sender value={input} onChange={setInput} loading={busy} placeholder="询问采购规则、采购单进度，或描述采购需求…" onSubmit={submit} /><Typography.Text type="secondary">正式业务操作会在你确认后执行。</Typography.Text></div>
    </section></div>
}
