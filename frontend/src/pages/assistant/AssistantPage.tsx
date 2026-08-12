import { useEffect, useMemo, useRef, useState } from 'react'
import { Actions, Bubble, Conversations, Prompts, Sender, Sources, Welcome } from '@ant-design/x'
import { Alert, App, Avatar, Button, Card, Descriptions, Space, Tag, Typography } from 'antd'
import { CopyOutlined, FileTextOutlined, MessageOutlined, PlusOutlined, RobotOutlined, ToolOutlined, UserOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { useIdentity } from '../../features/identity/IdentityProvider'
import { enumLabel, fieldLabel, localizeBusinessText } from '../../constants/business'
import type { AgentChatData, AgentMessage, Citation, PendingAction } from '../../types/api'

interface Conversation { key: string; label: string; externalId: string; backendId?: number; messages: AgentMessage[] }
const initialConversation = (): Conversation => ({ key: crypto.randomUUID(), label: '新会话', externalId: `web-${crypto.randomUUID()}`, messages: [] })
const prompts = [
  { key: 'knowledge', icon: <FileTextOutlined />, label: '采购申请被驳回后应该怎么办？', description: '查询制度与流程规则' },
  { key: 'realtime', icon: <ToolOutlined />, label: '帮我查一下采购单 91003 现在到哪个环节了？', description: '读取实时采购数据' },
  { key: 'hybrid', icon: <MessageOutlined />, label: '采购单 91003 被驳回了，我接下来应该怎么处理？', description: '结合状态与业务规则' },
]

function citationItems(data?: AgentChatData): Citation[] { return data?.knowledge?.citations || data?.knowledge?.evidence || [] }

const toolLabels: Record<string, string> = {
  get_purchase_request: '采购单实时信息',
  get_similar_cases: '历史采购记录',
  get_supplier_performance: '供应商履约记录',
  get_requirement_risk_signals: '采购风险信息',
  query_purchase_analytics: '采购统计数据',
}

function BusinessFields({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value).filter(([, item]) => item == null || ['string', 'number', 'boolean'].includes(typeof item))
  if (!entries.length) return <Typography.Text type="secondary">已完成结构化分析，结论已写入回答。</Typography.Text>
  return <Descriptions size="small" column={1} items={entries.map(([key, item]) => ({ key, label: fieldLabel(key), children: String(enumLabel(item) ?? '—') }))} />
}

function HitlCard({ action, conversationId, onDone }: { action: PendingAction; conversationId: number; onDone: (text: string) => void }) {
  const { agent } = useIdentity(); const { message } = App.useApp(); const [loading,setLoading]=useState(false)
  const decide=async(type:'confirm'|'cancel')=>{setLoading(true);try{await agent.decide(type,conversationId,action.action_id,action.confirmation_token);const text=type==='confirm'?'已确认执行，正式结果已由后端校验。':'已取消本次操作。';message.success(text);onDone(text)}catch(err){message.error(err instanceof Error?err.message:'操作失败')}finally{setLoading(false)}}
  return <Card className="hitl-card" title="需要你确认的正式操作" size="small"><Typography.Paragraph>{action.title || action.summary || `动作：${action.action_type || '业务状态变更'}`}</Typography.Paragraph>
    {action.draft && <BusinessFields value={action.draft}/>}<Space><Button type="primary" loading={loading} onClick={()=>decide('confirm')}>确认执行</Button><Button disabled={loading} onClick={()=>decide('cancel')}>取消</Button></Space></Card>
}

function AssistantContent({ message, onHitlDone }: { message: AgentMessage; onHitlDone: (text: string) => void }) {
  const data=message.data; const citations=citationItems(data); const tools=data?.execution?.tools || []
  if(message.status==='loading') return <div className="assistant-answer">{message.content&&<ReactMarkdown>{localizeBusinessText(message.content)}</ReactMarkdown>}<Typography.Text type="secondary">{message.streamStatus||'正在理解你的问题'}</Typography.Text></div>
  if(message.status==='error') return <Alert type="error" showIcon title="本次回答失败" description={message.error}/>
  return <div className="assistant-answer"><ReactMarkdown>{localizeBusinessText(message.content)}</ReactMarkdown>
    {(data?.tool_call_count||0)>0&&<Card size="small" className="tool-card" title={<Space><ToolOutlined/>已查询业务系统 <Tag color="blue">{data?.tool_call_count} 次</Tag></Space>}>
      {tools.length ? tools.map((tool,index)=>{const name=String(tool.tool_name||tool.name||'');return <div className="tool-row" key={index}><strong>{toolLabels[name]||`业务查询 ${index+1}`}</strong><span>已完成</span></div>}) : <Typography.Text type="secondary">查询结果已作为实时业务事实用于本次回答。</Typography.Text>}
    </Card>}
    {citations.length>0&&<Sources title={`知识来源（${citations.length}）`} defaultExpanded items={citations.map((item,index)=>({key:item.citation_id||index,title:item.title||`来源 ${index+1}`,description:Array.isArray(item.section_path)?item.section_path.join(' / '):item.section_path||item.source_path||'知识库文档'}))}/>}
    {data?.analysis&&<Card size="small" title="分析结果" className="tool-card"><BusinessFields value={(data.analysis.summary as Record<string,unknown>)||{}}/></Card>}
    {data?.pending_action&&<HitlCard action={data.pending_action} conversationId={data.conversation_id} onDone={onHitlDone}/>}
    <Actions items={[{key:'copy',label:'复制回答',icon:<CopyOutlined/>,onItemClick:()=>void navigator.clipboard.writeText(message.content)}]} />
  </div>
}

export function AssistantPage(){
  const {agent,user}=useIdentity();const {message:toast}=App.useApp();const[first]=useState(initialConversation);const[conversations,setConversations]=useState<Conversation[]>([first]);const[activeKey,setActiveKey]=useState(first.key);const[busy,setBusy]=useState(false);const[input,setInput]=useState('')
  const active=conversations.find((item)=>item.key===activeKey)||conversations[0];const activeRequest=useRef<AbortController|null>(null)
  useEffect(()=>()=>activeRequest.current?.abort(),[])
  const update=(fn:(value:Conversation)=>Conversation)=>setConversations((list)=>list.map((item)=>item.key===active.key?fn(item):item))
  const newChat=()=>{const next=initialConversation();setConversations((list)=>[next,...list]);setActiveKey(next.key)}
  const submit=async(value:string)=>{const content=value.trim();if(!content||busy)return;setInput('');const userMessage:AgentMessage={id:crypto.randomUUID(),role:'user',content,createdAt:new Date().toISOString(),status:'success'};const loadingId=crypto.randomUUID();update((value)=>({...value,label:value.messages.length?value.label:content.slice(0,18),messages:[...value.messages,userMessage,{id:loadingId,role:'assistant',content:'',createdAt:new Date().toISOString(),status:'loading',originalPrompt:content}]}));setBusy(true)
    try{const controller=new AbortController();activeRequest.current=controller;const result=await agent.chatStream(content,active.externalId,`web-${crypto.randomUUID()}`,(event)=>{const payload=event.data as Record<string,any>;if(event.event==='conversation_started')update((value)=>({...value,backendId:Number(payload.conversation_id),messages:value.messages}));if(['thinking','retrieving_knowledge','querying_business_data','analyzing'].includes(event.event))update((value)=>({...value,messages:value.messages.map((item)=>item.id===loadingId?{...item,streamStatus:String(payload.message||'正在处理')}:item)}));if(event.event==='answer_delta')update((value)=>({...value,messages:value.messages.map((item)=>item.id===loadingId?{...item,content:item.content+String(payload.delta||''),streamStatus:'正在核对回答依据'}:item)}))},controller.signal);update((value)=>({...value,backendId:result.conversation_id,messages:value.messages.map((item)=>item.id===loadingId?{...item,content:result.reply,status:'success',streamStatus:undefined,data:result}:item)}))}
    catch(err){const error=err instanceof Error?err.message:'Agent 暂时不可用';update((value)=>({...value,messages:value.messages.map((item)=>item.id===loadingId?{...item,status:'error',error}:item)}));if(error!=='本次回答已取消')toast.error(error)}finally{activeRequest.current=null;setBusy(false)}}
  const bubbleItems=useMemo(()=>active.messages.map((item)=>({key:item.id,role:item.role==='assistant'?'ai':'user',status:item.status,content:item.content||'处理中',extraInfo:{item}})),[active.messages])
  return <div className="assistant-page"><aside className="conversation-panel"><div className="conversation-brand"><RobotOutlined/><div><strong>智能采购助手</strong><span>规则与实时事实协同</span></div></div><Conversations creation={{label:'新建会话',icon:<PlusOutlined/>,onClick:newChat}} activeKey={activeKey} onActiveChange={(key)=>setActiveKey(String(key))} items={conversations.map((item,index)=>({key:item.key,label:item.label,group:index===0?'今天':'最近'}))} groupable /></aside>
    <section className="chat-panel"><div className="chat-header"><div><strong>智能采购助手</strong><span>{active.backendId?`会话 #${active.backendId}`:'新会话'} · {user.name}</span></div><Tag color="processing">Agent 在线</Tag></div>
      <div className="message-scroll">{!active.messages.length?<div className="assistant-welcome"><Welcome icon={<Avatar size={50} icon={<RobotOutlined/>}/>} title="你好，我是采购智能助手" description="我可以查询采购制度、读取真实采购状态，并把两类证据结合起来回答。正式业务动作会先向你确认。"/><Prompts title="你可以这样问" items={prompts} wrap onItemClick={({data})=>submit(String(data.label))}/></div>:<Bubble.List autoScroll items={bubbleItems} role={{user:{placement:'end',avatar:<Avatar icon={<UserOutlined/>}/>,variant:'filled'},ai:{placement:'start',avatar:<Avatar icon={<RobotOutlined/>}/>,variant:'outlined',contentRender:(_,info)=>{const item=info.extraInfo?.item as AgentMessage;return <AssistantContent message={item} onHitlDone={(text)=>update((value)=>({...value,messages:[...value.messages,{id:crypto.randomUUID(),role:'assistant',content:text,createdAt:new Date().toISOString(),status:'success'}]}))}/>}}}} />}</div>
      <div className="sender-wrap"><Sender value={input} onChange={setInput} loading={busy} placeholder="询问采购规则、采购单状态或综合分析…" onSubmit={submit}/><Typography.Text type="secondary">回答基于可见知识与业务接口，请在正式操作前核对关键信息。</Typography.Text></div>
    </section></div>
}
