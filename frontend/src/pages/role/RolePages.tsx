import { useEffect, useState } from 'react'
import { Button, Card, Descriptions, Input, Modal, Space, Table, Tag, Typography, type TableProps } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { DataState, PageShell } from '../../components/PageShell'
import { RequirementListPage } from '../procurement/RequirementListPage'
import { StatusTag } from '../../components/StatusTag'
import { useIdentity } from '../../features/identity/IdentityProvider'
import type { PurchaseRecord, SupplierDetail, SupplierRisk, SupplierSummary } from '../../types/api'

export const PendingApprovalPage = () => <RequirementListPage title="待审批" description="需要你审核的采购申请" view="PENDING_FOR_ME" fixedStatus="PENDING_REVIEW" showCreate={false} />
export const BuildingRecordsPage = () => <RequirementListPage title="楼宇采购记录" description="你负责楼宇范围内的真实采购记录" view="BUILDING_SCOPE" showCreate={false} />
export const PendingPurchasePage = () => <RequirementListPage title="待采购" description="已通过审批并分配给你的采购任务" view="PENDING_FOR_ME" showCreate={false} />
export const PendingWarehousePage = () => <RequirementListPage title="待入库" description="等待你登记收货和入库的采购单" view="PENDING_FOR_ME" fixedStatus="PENDING_WAREHOUSE" showCreate={false} />

export function PurchaseRecordsPage({ warehouse = false }: { warehouse?: boolean }) {
  const { backend } = useIdentity(); const navigate = useNavigate()
  const [data, setData] = useState<{ items: PurchaseRecord[]; total: number }>({ items: [], total: 0 })
  const [loading,setLoading]=useState(true); const [error,setError]=useState<string|null>(null)
  const load=async()=>{setLoading(true);setError(null);try{setData(await backend.purchaseRecords(warehouse ? { status:'COMPLETED' } : {}))}catch(err){setError(err instanceof Error?err.message:'记录加载失败')}finally{setLoading(false)}}
  useEffect(()=>{void load()},[backend,warehouse])
  const columns: TableProps<PurchaseRecord>['columns']=[
    {title:'采购单号',dataIndex:'requirement_no',render:(v)=><Typography.Text strong>{v}</Typography.Text>},
    {title:'设备',dataIndex:'device_name',render:(v)=>v||'—'}, {title:'数量',render:(_,r)=>`${r.quantity||'—'} ${r.unit||''}`},
    {title:'供应商',dataIndex:'supplier_name',render:(v)=>v||'—'}, {title:'状态',dataIndex:'status',render:(v)=><StatusTag status={v}/>},
    {title:warehouse?'入库时间':'采购时间',render:(_,r)=>new Date((warehouse?r.received_at:r.purchased_at)||r.created_at).toLocaleString('zh-CN')},
    {title:'操作',render:(_,r)=><Button type="link" onClick={()=>navigate(`/requirements/${r.requirement_id}`)}>查看详情</Button>},
  ]
  return <PageShell title={warehouse?'入库记录':'采购记录'} description={warehouse?'已完成的真实入库记录':'采购岗位相关的执行记录'}>
    <DataState loading={loading} error={error} empty={!data.items.length} onRetry={load}><Card className="table-card"><Table rowKey="requirement_id" columns={columns} dataSource={data.items} pagination={{pageSize:20,total:data.total,showTotal:(v)=>`共 ${v} 条`}} scroll={{x:800}}/></Card></DataState>
  </PageShell>
}

export function SupplierManagementPage({ title = '供应商管理', description = '查看、搜索并分页浏览真实供应商主档' }: { title?: string; description?: string }) {
  const { backend }=useIdentity(); const [keyword,setKeyword]=useState(''); const [activeKeyword,setActiveKeyword]=useState('')
  const [data,setData]=useState<{items:SupplierSummary[];total:number}>({items:[],total:0});const[page,setPage]=useState(1);const[loading,setLoading]=useState(false);const[error,setError]=useState<string|null>(null)
  const [detail,setDetail]=useState<SupplierDetail|null>(null);const[detailLoading,setDetailLoading]=useState(false)
  const load=async(nextPage=page,nextKeyword=activeKeyword)=>{setLoading(true);setError(null);try{const result=await backend.suppliers({keyword:nextKeyword||undefined,page:nextPage,page_size:20});setData(result)}catch(err){setError(err instanceof Error?err.message:'供应商查询失败')}finally{setLoading(false)}}
  useEffect(()=>{void load()},[backend,page,activeKeyword])
  const search=()=>{setPage(1);setActiveKeyword(keyword.trim())}
  const columns:TableProps<SupplierSummary>['columns']=[
    {title:'供应商名称',dataIndex:'supplier_name',render:(v)=><Typography.Text strong>{v}</Typography.Text>},
    {title:'统一社会信用代码',dataIndex:'unified_social_credit_code',render:(v)=>v||'—'},
    {title:'主档状态',render:(_,r)=><Tag color={r.status?'success':'default'}>{r.status?'正常启用':'已停用'}</Tag>},
    {title:'风险状态',render:(_,r)=><StatusTag status={r.blacklist_status}/>},
    {title:'操作',render:(_,r)=><Button type="link" onClick={async()=>{setDetailLoading(true);try{setDetail(await backend.supplier(r.supplier_id))}finally{setDetailLoading(false)}}}>查看详情</Button>},
  ]
  return <PageShell title={title} description={description}>
    <Card className="filter-card"><Space.Compact style={{width:420,maxWidth:'100%'}}><Input value={keyword} onChange={(e)=>setKeyword(e.target.value)} onPressEnter={search} placeholder="输入供应商名称或关键字"/><Button type="primary" icon={<SearchOutlined/>} onClick={search}>查询</Button></Space.Compact></Card>
    <DataState loading={loading} error={error} empty={!data.items.length} onRetry={()=>load()}><Card className="table-card"><Table rowKey="supplier_id" columns={columns} dataSource={data.items} pagination={{current:page,pageSize:20,total:data.total,onChange:setPage,showTotal:(total)=>`共 ${total} 家供应商`}}/></Card></DataState>
    <Modal open={detailLoading||Boolean(detail)} loading={detailLoading} title="供应商详情" footer={null} onCancel={()=>setDetail(null)}>{detail&&<Descriptions column={1} items={[
      {key:'name',label:'供应商名称',children:detail.supplier_name},{key:'credit',label:'统一社会信用代码',children:detail.unified_social_credit_code||'—'},{key:'bank',label:'开户银行',children:detail.bank_name||'—'},{key:'account',label:'银行账号',children:detail.bank_account||'—'},{key:'address',label:'注册地址',children:detail.registered_address||'—'},{key:'contact',label:'合同联系方式',children:detail.contract_contact_info||'—'},{key:'risk',label:'风险状态',children:<StatusTag status={detail.blacklist.status}/>}]} />}</Modal>
  </PageShell>
}

export function SupplierRiskPage(){
  const {backend}=useIdentity();const navigate=useNavigate();const[data,setData]=useState<{items:SupplierRisk[];total:number}>({items:[],total:0});const[page,setPage]=useState(1);const[loading,setLoading]=useState(true);const[error,setError]=useState<string|null>(null)
  const load=async()=>{setLoading(true);setError(null);try{setData(await backend.supplierRisks({page,page_size:20}))}catch(err){setError(err instanceof Error?err.message:'供应商风险加载失败')}finally{setLoading(false)}}
  useEffect(()=>{void load()},[backend,page])
  const columns:TableProps<SupplierRisk>['columns']=[
    {title:'供应商',dataIndex:'supplier_name',render:(value)=><Typography.Text strong>{value}</Typography.Text>},
    {title:'当前状态',render:(_,item)=>item.is_effective?<Tag color="error">风险生效中</Tag>:<Tag>已失效或解除</Tag>},
    {title:'风险类型',dataIndex:'blacklist_type'},
    {title:'风险原因',dataIndex:'risk_reason',ellipsis:true},
    {title:'生效时间',dataIndex:'start_at',render:(value)=>new Date(value).toLocaleString('zh-CN')},
    {title:'到期 / 解除时间',render:(_,item)=>item.released_at?new Date(item.released_at).toLocaleString('zh-CN'):item.end_at?new Date(item.end_at).toLocaleString('zh-CN'):'长期有效'},
    {title:'风险来源',render:(_,item)=><Button type="link" onClick={()=>navigate(`/requirements/${item.source_requirement_id}`)}>{item.source_requirement_no}</Button>},
  ]
  return <PageShell title="供应商风险" description="你负责楼宇范围内的真实供应商风险与黑名单记录"><DataState loading={loading} error={error} empty={!data.items.length} onRetry={load}><Card className="table-card"><Table rowKey="blacklist_id" columns={columns} dataSource={data.items} pagination={{current:page,pageSize:20,total:data.total,onChange:setPage,showTotal:(total)=>`共 ${total} 条风险记录`}} scroll={{x:1100}}/></Card></DataState></PageShell>
}
