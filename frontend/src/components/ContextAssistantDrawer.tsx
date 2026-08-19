import { useEffect, useRef, useState } from 'react'
import { Bubble, Prompts, Sender, Sources } from '@ant-design/x'
import { Alert, Avatar, Button, Card, Drawer, Space, Tag, Typography } from 'antd'
import {
  FileSearchOutlined,
  HistoryOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  ShopOutlined,
  UserOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { useIdentity } from '../features/identity/IdentityProvider'
import { localizeBusinessText } from '../constants/business'
import type {
  AgentChatData,
  AgentFormSuggestion,
  AgentMessage,
  AgentUIContext,
  KnowledgeSource,
} from '../types/api'
import './ContextAssistantDrawer.css'

interface ContextAssistantDrawerProps {
  open: boolean
  onClose: () => void
  requirementId: number
  requirementNo: string
  pageType: string
  role: 'BUILDING_MANAGER' | 'PURCHASER' | 'WAREHOUSE_MANAGER' | 'APPLICANT'
  getUserDraft?: () => Record<string, unknown> | undefined
  onApplySuggestion?: (suggestion: AgentFormSuggestion) => void
}

const rolePrompts = {
  BUILDING_MANAGER: [
    ['history', '查看当前采购单的相似案例和历史价格', '查询相似设备的真实采购记录', <HistoryOutlined />],
    ['supplier', '推荐供应商', '依据历史履约和当前风险给出建议', <ShopOutlined />],
    ['price', '查询当前采购单相似案例的历史价格', '查看相似采购的真实成交价格', <FileSearchOutlined />],
    ['risk', '检查供应商风险', '核对有效黑名单和风险信号', <SafetyCertificateOutlined />],
    ['review', '帮我检查审批方案', '结合制度检查当前未提交草稿', <RobotOutlined />],
  ],
  PURCHASER: [
    ['recommendation', '推荐历史税率和合同联系方式', '参考该供应商的真实历史采购执行记录', <HistoryOutlined />],
    ['review', '查看审批建议', '读取当前采购单的审批信息', <FileSearchOutlined />],
    ['history', '查询当前采购单相似案例的供应商历史', '查询供应商历史履约记录', <HistoryOutlined />],
    ['compare', '比较供应商', '比较候选供应商的真实数据', <ShopOutlined />],
    ['price', '查询当前采购单相似案例的历史成交价格', '查看相似设备历史价格', <FileSearchOutlined />],
  ],
  WAREHOUSE_MANAGER: [
    ['recommendation', '推荐历史入库位置', '参考同类设备的真实历史入库记录', <HistoryOutlined />],
    ['status', '核对入库要求', '查询当前采购单和入库规则', <FileSearchOutlined />],
  ],
  APPLICANT: [
    ['recommendation', '推荐历史品牌和型号', '参考同类设备的真实历史采购记录', <HistoryOutlined />],
    ['status', '查看当前进度', '查询当前采购单实时状态', <FileSearchOutlined />],
  ],
} as const

function citations(data?: AgentChatData): KnowledgeSource[] {
  return data?.knowledge_sources || []
}

function candidateSuggestions(data?: AgentChatData): AgentFormSuggestion[] {
  const candidates = Array.isArray(data?.analysis?.candidates)
    ? data.analysis.candidates as Record<string, unknown>[]
    : []
  const seen = new Set<string>()
  return candidates.flatMap((candidate) => {
    const supplierId = Number(candidate.supplier_id)
    const supplierName = String(candidate.supplier_name || '')
    const priceValue = candidate.actual_unit_price ?? candidate.estimated_unit_price ?? candidate.unit_price
    const total = Number(candidate.actual_total_price)
    const quantity = Number(candidate.quantity)
    const unitPrice = priceValue == null && Number.isFinite(total) && quantity > 0
      ? Number((total / quantity).toFixed(2))
      : Number(priceValue)
    const suggestion: AgentFormSuggestion = { source: '采购后端分析结果' }
    if (Number.isInteger(supplierId) && supplierId > 0) suggestion.supplier_id = supplierId
    if (supplierName) suggestion.supplier_name = supplierName
    if (Number.isFinite(unitPrice) && unitPrice >= 0) suggestion.unit_price = unitPrice
    if (!suggestion.supplier_id && suggestion.unit_price === undefined) return []
    const key = `${suggestion.supplier_id || ''}:${suggestion.unit_price ?? ''}`
    if (seen.has(key)) return []
    seen.add(key)
    return [suggestion]
  }).slice(0, 4)
}

export function ContextAssistantDrawer({
  open,
  onClose,
  requirementId,
  requirementNo,
  pageType,
  role,
  getUserDraft,
  onApplySuggestion,
}: ContextAssistantDrawerProps) {
  const { agent } = useIdentity()
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const conversationId = useRef(`context-${pageType}-${requirementId}-${crypto.randomUUID()}`)
  const activeRequest = useRef<AbortController | null>(null)

  useEffect(() => () => activeRequest.current?.abort(), [])

  const submit = async (value: string) => {
    const content = value.trim()
    if (!content || busy) return
    setInput('')
    const loadingId = crypto.randomUUID()
    setMessages((items) => [...items,
      { id: crypto.randomUUID(), role: 'user', content, createdAt: new Date().toISOString(), status: 'success' },
      { id: loadingId, role: 'assistant', content: '', createdAt: new Date().toISOString(), status: 'loading' },
    ])
    setBusy(true)
    const controller = new AbortController()
    activeRequest.current = controller
    const uiContext: AgentUIContext = {
      page_type: pageType,
      requirement_id: requirementId,
      user_draft: getUserDraft?.(),
    }
    try {
      const result = await agent.chatStream(
        content,
        conversationId.current,
        `context-${crypto.randomUUID()}`,
        (event) => {
          const payload = event.data as Record<string, unknown>
          setMessages((items) => items.map((item) => {
            if (item.id !== loadingId) return item
            if (event.event === 'answer_delta') return {
              ...item,
              content: item.content + String(payload.delta || ''),
              streamStatus: '正在核对回答依据',
            }
            if (['thinking', 'retrieving_knowledge', 'querying_business_data', 'analyzing'].includes(event.event)) {
              return { ...item, streamStatus: String(payload.message || '正在处理') }
            }
            return item
          }))
        },
        controller.signal,
        uiContext,
      )
      setMessages((items) => items.map((item) => item.id === loadingId
        ? { ...item, content: result.reply, data: result, status: 'success', streamStatus: undefined }
        : item))
    } catch (error) {
      if (controller.signal.aborted) return
      setMessages((items) => items.map((item) => item.id === loadingId
        ? { ...item, status: 'error', error: error instanceof Error ? error.message : '智能辅助暂时不可用' }
        : item))
    } finally {
      activeRequest.current = null
      setBusy(false)
    }
  }

  return <Drawer
    open={open}
    onClose={onClose}
    size={520}
    destroyOnHidden={false}
    title={<div><strong>智能辅助</strong><div className="context-subtitle">当前采购申请：{requirementNo}</div></div>}
    extra={<Tag color="blue">业务上下文已关联</Tag>}
  >
    <Alert
      type="info"
      showIcon
      title="采购事实将从业务系统重新查询"
      description="已关联当前采购单上下文；未提交草稿会明确作为草稿处理。"
    />
    {!messages.length && <Prompts
      title="快捷问题"
      wrap
      items={rolePrompts[role].map(([key, label, description, icon]) => ({ key, label, description, icon }))}
      onItemClick={({ data }) => void submit(String(data.label))}
    />}
    <div className="context-message-list">
      {messages.map((item) => <div key={item.id} className={`context-message ${item.role}`}>
        <Avatar icon={item.role === 'user' ? <UserOutlined /> : <RobotOutlined />} />
        <div className="context-message-body">
          {item.status === 'error'
            ? <Alert type="error" showIcon title="本次辅助失败" description={item.error} />
            : <Bubble content={<div>
              {item.content ? <ReactMarkdown>{localizeBusinessText(item.content)}</ReactMarkdown> : null}
              {item.status === 'loading' && <Typography.Text type="secondary">{item.streamStatus || '正在理解你的问题'}</Typography.Text>}
            </div>} />}
          {item.status === 'success' && item.data && <>
            {item.data.tool_call_count > 0 && <Tag color="processing">已查询业务系统 {item.data.tool_call_count} 次</Tag>}
            {citations(item.data).length > 0 && <Sources
              title={`知识来源（${citations(item.data).length}）`}
              items={citations(item.data).map((source, index) => ({
                key: index,
                title: source.title || `来源 ${index + 1}`,
                description: source.section_path.join(' / '),
              }))}
            />}
            {candidateSuggestions(item.data).map((suggestion, index) => <Card
              size="small"
              className="agent-suggestion-card"
              key={`${item.id}-${index}`}
              title="可应用的业务建议"
            >
              {suggestion.supplier_name && <p>推荐供应商：<strong>{suggestion.supplier_name}</strong></p>}
              {suggestion.unit_price !== undefined && <p>历史参考单价：<strong>¥ {suggestion.unit_price.toLocaleString('zh-CN')}</strong></p>}
              <Typography.Text type="secondary">来源：{suggestion.source}</Typography.Text>
              {onApplySuggestion && <div><Space wrap>
                {suggestion.supplier_id && <Button size="small" onClick={() => onApplySuggestion({ ...suggestion, unit_price: undefined })}>应用供应商</Button>}
                {suggestion.unit_price !== undefined && <Button size="small" onClick={() => onApplySuggestion({ ...suggestion, supplier_id: undefined })}>应用参考价格</Button>}
                {suggestion.supplier_id && suggestion.unit_price !== undefined && <Button type="primary" size="small" onClick={() => onApplySuggestion(suggestion)}>应用到当前方案</Button>}
              </Space></div>}
            </Card>)}
          </>}
        </div>
      </div>)}
    </div>
    <div className="context-sender"><Sender
      value={input}
      onChange={setInput}
      onSubmit={submit}
      loading={busy}
      placeholder="询问当前采购单的历史、价格、供应商或规则…"
    /></div>
  </Drawer>
}
