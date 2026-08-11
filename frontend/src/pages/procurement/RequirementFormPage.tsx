import { useEffect, useState } from 'react'
import { Alert, App, Button, Card, Form, Input, InputNumber, Select, Space } from 'antd'
import { ArrowLeftOutlined, SaveOutlined, SendOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { PageShell } from '../../components/PageShell'
import { useIdentity } from '../../features/identity/IdentityProvider'
import type { ApplicantFields } from '../../types/api'

const deviceTypes=['电气','暖通','弱电','机房环境','工器具','算力服务器','IDC网络','其他']
const actionToken=()=>`WEB-${crypto.randomUUID()}`

export function RequirementFormPage(){
  const {id}=useParams();const editingId=id?Number(id):null;const {user,roleCodes,backend}=useIdentity();const navigate=useNavigate();const{message}=App.useApp();const[form]=Form.useForm<ApplicantFields&{building_id:number}>();const[requirementId,setRequirementId]=useState<number|null>(editingId);const[version,setVersion]=useState(0);const[status,setStatus]=useState('DRAFT');const[loading,setLoading]=useState(Boolean(editingId));const[saving,setSaving]=useState(false)
  const canCreate=roleCodes.includes('APPLICANT')&&user.buildings.length>0
  useEffect(()=>{if(!editingId){if(user.buildings[0])form.setFieldValue('building_id',user.buildings.find((b)=>b.is_primary)?.building_id||user.buildings[0].building_id);return}setLoading(true);backend.requirement(editingId).then((data)=>{form.setFieldsValue({...data.applicant_fields,building_id:Number(data.building.building_id)});setVersion(data.version);setStatus(data.status)}).catch((err)=>message.error(err.message)).finally(()=>setLoading(false))},[editingId,backend,form,user.buildings,message])
  const persist=async()=>{const values=await form.validateFields();setSaving(true);try{let currentId=requirementId;let currentVersion=version;if(!currentId){const created=await backend.createRequirement(values.building_id);currentId=created.requirement_id;currentVersion=created.version;setRequirementId(currentId)}const {building_id,...fields}=values;void building_id;const saved=await backend.saveApplicantFields(currentId,currentVersion,fields);setVersion(saved.version);message.success(saved.fields_complete?'草稿已保存，必填字段完整':`草稿已保存，仍缺少 ${saved.missing_fields.length} 项`);return{currentId,version:saved.version,complete:saved.fields_complete}}finally{setSaving(false)}}
  const save=async()=>{try{await persist()}catch(err){message.error(err instanceof Error?err.message:'保存失败')}}
  const submit=async()=>{try{const saved=await persist();if(!saved.complete){message.warning('请先补齐所有必填字段');return}const candidates=await backend.handlerCandidates(saved.currentId,'BUILDING_MANAGER');const assignee=candidates.auto_selected_employee_id||candidates.items[0]?.employee_id;if(!assignee){message.error('当前楼宇没有可分配的楼长');return}const action=status==='REJECTED'?'resubmit-review':'submit-review';await backend.action(saved.currentId,action,{expected_version:saved.version,assigned_to_employee_id:assignee,action_token:actionToken()});message.success('采购申请已提交楼长审核');navigate(`/requirements/${saved.currentId}`)}catch(err){message.error(err instanceof Error?err.message:'提交失败')}}
  return <PageShell title={editingId?'继续处理采购申请':'新建采购申请'} description="字段严格对应当前 Backend ApplicantFields Schema" extra={<Button icon={<ArrowLeftOutlined/>} onClick={()=>navigate('/requirements')}>返回列表</Button>}>
    {!canCreate&&!editingId&&<Alert type="warning" showIcon title="当前身份无法创建采购申请" description="真实后端要求 APPLICANT 角色并归属具体楼宇。当前测试身份不满足该条件；前端不会绕过权限或伪造保存结果。"/>}
    <Form form={form} layout="vertical" disabled={loading||(!canCreate&&!editingId)}>
      <Card title="基础信息" className="form-card"><Form.Item name="building_id" label="所属楼宇" rules={[{required:true,message:'请选择所属楼宇'}]}><Select options={user.buildings.map((b)=>({value:b.building_id,label:b.building_name}))}/></Form.Item></Card>
      <Card title="设备信息" className="form-card"><div className="form-grid"><Form.Item name="device_profession" label="设备类型" rules={[{required:true,message:'请选择设备类型'}]}><Select options={deviceTypes.map((value)=>({value,label:value}))}/></Form.Item><Form.Item name="device_name" label="设备名称" rules={[{required:true,message:'请输入设备名称'}]}><Input maxLength={200}/></Form.Item><Form.Item name="brand" label="品牌"><Input maxLength={100}/></Form.Item><Form.Item name="model" label="规格型号"><Input maxLength={150}/></Form.Item><Form.Item name="quantity" label="数量" rules={[{required:true,message:'请输入数量'}]}><InputNumber min={0.001} precision={3} style={{width:'100%'}}/></Form.Item><Form.Item name="unit" label="单位" rules={[{required:true,message:'请输入单位'}]}><Input maxLength={30}/></Form.Item></div></Card>
      <Card title="采购需求说明" className="form-card"><Form.Item name="application_reason" label="申请原因" rules={[{required:true,message:'请说明申请原因'}]}><Input.TextArea rows={5}/></Form.Item><Form.Item name="applicant_remark" label="补充说明"><Input.TextArea rows={3}/></Form.Item></Card>
      <div className="form-actions"><Space><Button onClick={()=>navigate('/requirements')}>取消</Button><Button icon={<SaveOutlined/>} loading={saving} onClick={save}>保存草稿</Button><Button type="primary" icon={<SendOutlined/>} loading={saving} onClick={submit}>提交楼长审核</Button></Space></div>
    </Form>
  </PageShell>
}
