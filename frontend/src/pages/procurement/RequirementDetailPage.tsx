import { useEffect, useMemo, useState } from 'react'
import {
  Alert, App, Button, Card, DatePicker, Descriptions, Divider, Form, Input, InputNumber, Modal,
  Radio, Select, Space, Spin, Steps, Timeline, Typography,
} from 'antd'
import { ArrowLeftOutlined, CheckOutlined, EditOutlined, SendOutlined, StopOutlined, ThunderboltOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useNavigate, useParams } from 'react-router-dom'
import { PageShell } from '../../components/PageShell'
import { StatusTag, statusLabel } from '../../components/StatusTag'
import { SupplierSelect } from '../../components/SupplierSelect'
import { ContextAssistantDrawer } from '../../components/ContextAssistantDrawer'
import { actionLabel, enumLabel } from '../../constants/business'
import { useIdentity } from '../../features/identity/IdentityProvider'
import type { AgentFormSuggestion, RequirementDetail, TimelineItem } from '../../types/api'
import './RequirementDetailPage.css'

const actionToken = () => `WEB-${crypto.randomUUID()}`
const steps = ['DRAFT', 'PENDING_REVIEW', 'PENDING_PURCHASE', 'PURCHASING', 'PENDING_WAREHOUSE', 'COMPLETED']
const dateFields = new Set(['created_at', 'reviewed_at', 'purchased_at', 'received_at', 'expected_arrival_date'])
const moneyFields = new Set(['estimated_unit_price', 'estimated_total_price', 'actual_unit_price', 'actual_total_price'])

function displayValue(key: string, value: unknown) {
  if (value == null || value === '') return '—'
  if (dateFields.has(key)) return dayjs(String(value)).format(key === 'expected_arrival_date' ? 'YYYY-MM-DD' : 'YYYY-MM-DD HH:mm')
  if (moneyFields.has(key)) return `¥ ${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
  if (key === 'tax_rate') return `${value}%`
  return String(enumLabel(value))
}

type DetailItem = { key: string; label: string; value: unknown; span?: number }

function InfoDescriptions({ items }: { items: DetailItem[] }) {
  return <Descriptions column={{ xs: 1, md: 2, xl: 3 }} items={items.map((item) => ({
    key: item.key,
    label: item.label,
    children: displayValue(item.key, item.value),
  }))} />
}

function ReviewRoundCard({ record }: { record: Record<string, any> }) {
  return <Card size="small" className="record-round-card" title={`第 ${record.review_round} 次审批`} extra={<StatusTag status={record.review_result || record.review_status} />}>
    <Typography.Title level={5}>审批记录</Typography.Title>
    <InfoDescriptions items={[
      { key: 'reviewer_name', label: '审批人', value: record.reviewer_name },
      { key: 'reviewer_mobile_masked', label: '联系方式', value: record.reviewer_mobile_masked },
      { key: 'reviewed_at', label: '审批时间', value: record.reviewed_at },
      { key: 'review_status', label: '审批状态', value: enumLabel(record.review_status) },
      { key: 'review_result', label: '审批结果', value: enumLabel(record.review_result) },
      { key: 'review_opinion', label: '审批意见', value: record.review_opinion || record.review_remark, span: 3 },
    ]} />
    <Divider />
    <Typography.Title level={5}>审批方案</Typography.Title>
    <InfoDescriptions items={[
      { key: 'proposed_supplier_name', label: '建议供应商', value: record.proposed_supplier_name },
      { key: 'supplier_contact_name', label: '供应商联系人', value: record.supplier_contact_name },
      { key: 'supplier_contact_info', label: '供应商联系方式', value: record.supplier_contact_info },
      { key: 'estimated_unit_price', label: '参考单价', value: record.estimated_unit_price },
      { key: 'estimated_total_price', label: '预计总价', value: record.estimated_total_price },
      { key: 'need_contract', label: '是否需要合同', value: record.need_contract == null ? null : record.need_contract ? '是' : '否' },
      { key: 'contract_type', label: '合同类型', value: record.contract_type },
      { key: 'payment_method', label: '付款方式', value: record.payment_method },
      { key: 'expected_arrival_date', label: '预计到货时间', value: record.expected_arrival_date },
      { key: 'warranty_info', label: '质保', value: record.warranty_info, span: 3 },
    ]} />
  </Card>
}

type ModalType = 'reject' | 'review' | 'purchase' | 'warehouse'

export function RequirementDetailPage() {
  const { id } = useParams()
  const requirementId = Number(id)
  const { backend, refreshTaskCount, roleCodes } = useIdentity()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [data, setData] = useState<RequirementDetail | null>(null)
  const [timeline, setTimeline] = useState<TimelineItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState<ModalType | null>(null)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [form] = Form.useForm()
  const needContract = Form.useWatch('need_contract', form)
  const unitPrice = Form.useWatch(modal === 'purchase' ? 'actual_unit_price' : 'estimated_unit_price', form)
  const receivedQuantity = Form.useWatch('received_quantity', form)

  const requestedQuantity = Number(data?.applicant_fields.quantity || 0)
  const calculatedTotal = useMemo(
    () => unitPrice == null ? null : Number((requestedQuantity * Number(unitPrice)).toFixed(2)),
    [requestedQuantity, unitPrice],
  )

  const load = async () => {
    setError(null)
    try {
      const [detail, history] = await Promise.all([
        backend.requirement(requirementId),
        backend.timeline(requirementId),
      ])
      setData(detail)
      setTimeline(history.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : '详情加载失败')
    }
  }
  useEffect(() => { void load() }, [backend, requirementId])

  const openModal = (type: ModalType) => {
    form.resetFields()
    if (type === 'review') {
      const review = [...(data?.review_records || [])].reverse().find((item) => item.review_status === 'DRAFT')
      form.setFieldsValue({
        ...review,
        need_contract: review?.need_contract ?? false,
        expected_arrival_date: review?.expected_arrival_date ? dayjs(review.expected_arrival_date) : undefined,
      })
    }
    if (type === 'warehouse') form.setFieldsValue({ received_quantity: requestedQuantity })
    setModal(type)
  }

  const runAction = async (action: string, targetRole?: string) => {
    if (!data || busy) return
    setBusy(true)
    try {
      const body: Record<string, unknown> = { expected_version: data.version, action_token: actionToken() }
      if (targetRole) {
        const candidates = await backend.handlerCandidates(requirementId, targetRole)
        const assignee = candidates.auto_selected_employee_id || candidates.items[0]?.employee_id
        if (!assignee) throw new Error('当前没有可分配的岗位处理人，请联系管理员检查人员配置。')
        body.assigned_to_employee_id = assignee
      }
      await backend.action(requirementId, action, body)
      message.success('操作已完成')
      await load()
      await refreshTaskCount()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '操作失败')
    } finally {
      setBusy(false)
    }
  }

  const approve = () => {
    if (!data) return
    if (data.missing_fields.length) {
      message.info('请先补充完整审批方案，再审批通过。')
      openModal('review')
      return
    }
    void runAction('submit-purchaser', 'PURCHASER')
  }

  const assistantRole = roleCodes.includes('BUILDING_MANAGER')
    ? 'BUILDING_MANAGER'
    : roleCodes.includes('PURCHASER')
      ? 'PURCHASER'
      : roleCodes.includes('WAREHOUSE_MANAGER')
        ? 'WAREHOUSE_MANAGER'
        : 'APPLICANT'

  const applySuggestion = (suggestion: AgentFormSuggestion) => {
    if (assistantRole === 'BUILDING_MANAGER') {
      openModal('review')
      form.setFieldsValue({
        proposed_supplier_id: suggestion.supplier_id,
        estimated_unit_price: suggestion.unit_price,
      })
    } else if (assistantRole === 'PURCHASER') {
      openModal('purchase')
      form.setFieldsValue({
        supplier_id: suggestion.supplier_id,
        actual_unit_price: suggestion.unit_price,
      })
    } else {
      message.info('该岗位当前仅提供查询辅助，不会自动修改业务表单。')
      return
    }
    message.success('建议已填入当前表单，请核对后再提交。')
  }

  const submitModal = async () => {
    if (!data || !modal || busy) return
    try {
      const values = await form.validateFields()
      setBusy(true)
      if (modal === 'reject') {
        await backend.action(requirementId, 'reject', {
          expected_version: data.version, action_token: actionToken(), reason: values.reason,
        })
      }
      if (modal === 'review') {
        await backend.saveReviewFields(requirementId, data.version, {
          ...values,
          expected_arrival_date: values.expected_arrival_date.format('YYYY-MM-DD'),
          estimated_total_price: calculatedTotal,
          contract_type: values.need_contract ? values.contract_type : null,
        })
      }
      if (modal === 'purchase') {
        await backend.savePurchaseFields(requirementId, data.version, {
          ...values,
          actual_total_price: calculatedTotal,
          purchased_at: new Date().toISOString(),
        })
      }
      if (modal === 'warehouse') await backend.saveWarehouseFields(requirementId, data.version, values)
      message.success(modal === 'reject' ? '申请已驳回' : '阶段信息已保存')
      setModal(null)
      form.resetFields()
      await load()
      await refreshTaskCount()
    } catch (err) {
      if (err && typeof err === 'object' && 'errorFields' in err) return
      message.error(err instanceof Error ? err.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  if (error) return <PageShell title="采购申请详情"><Alert type="error" showIcon title={error} action={<Button onClick={load}>重试</Button>} /></PageShell>
  if (!data) return <div className="center-state"><Spin description="正在加载采购详情" /></div>

  const current = Math.max(0, steps.indexOf(data.status))
  const applicant = data.applicant_fields
  return <PageShell title={data.requirement_no} description="采购申请详情与流程操作" extra={<Space>
    <Button icon={<ThunderboltOutlined />} onClick={() => setAssistantOpen(true)}>智能辅助</Button>
    <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button>
  </Space>}>
    <Card className="detail-hero"><div><Typography.Text type="secondary">当前唯一状态</Typography.Text><div className="detail-status"><StatusTag status={data.status} /><Typography.Text>{data.current_handler?.name ? `当前处理人：${data.current_handler.name}${data.current_handler.mobile_masked ? `（${data.current_handler.mobile_masked}）` : ''}` : '流程暂无处理人'}</Typography.Text></div></div><Space wrap>
      {data.allowed_actions.includes('SAVE_APPLICANT_FIELDS') && <Button icon={<EditOutlined />} onClick={() => navigate(`/requirements/${requirementId}/edit`)}>修改申请</Button>}
      {data.allowed_actions.includes('START_PURCHASE') && <Button type="primary" loading={busy} onClick={() => runAction('start-purchase')}>开始采购</Button>}
      {data.allowed_actions.includes('SAVE_REVIEW_FIELDS') && <Button onClick={() => openModal('review')}>填写审批方案</Button>}
      {data.allowed_actions.includes('REJECT') && <Button danger icon={<StopOutlined />} onClick={() => openModal('reject')}>驳回</Button>}
      {data.allowed_actions.includes('SUBMIT_PURCHASER') && <Button type="primary" icon={<SendOutlined />} loading={busy} onClick={approve}>审批通过并交采购</Button>}
      {data.allowed_actions.includes('SAVE_PURCHASE_FIELDS') && <Button onClick={() => openModal('purchase')}>登记采购结果</Button>}
      {data.allowed_actions.includes('SUBMIT_WAREHOUSE') && <Button type="primary" icon={<SendOutlined />} loading={busy} onClick={() => runAction('submit-warehouse', 'WAREHOUSE_MANAGER')}>提交仓库</Button>}
      {data.allowed_actions.includes('SAVE_WAREHOUSE_FIELDS') && <Button onClick={() => openModal('warehouse')}>登记入库</Button>}
      {data.allowed_actions.includes('COMPLETE') && <Button type="primary" icon={<CheckOutlined />} loading={busy} onClick={() => runAction('complete')}>确认完成</Button>}
    </Space></Card>
    <Card title="当前状态与流程" className="detail-card"><Steps current={current} status={data.status === 'REJECTED' ? 'error' : 'process'} items={steps.map((status) => ({ title: statusLabel(status) }))} />{data.status === 'REJECTED' && <Alert type="error" showIcon title="申请已驳回" description="请修改申请信息后重新提交审批。" style={{ marginTop: 20 }} />}</Card>
    <Card title="发起信息" className="detail-card"><InfoDescriptions items={[
      { key: 'initiator_name', label: '需求发起人', value: data.initiator.name },
      { key: 'initiator_mobile', label: '联系方式', value: data.initiator.mobile_masked },
      { key: 'initiator_building', label: '所属楼宇/部门', value: data.initiator.building_name || data.building.building_name },
      { key: 'created_at', label: '发起时间', value: data.initiator.created_at },
      ...(data.initiator.is_delegated ? [{ key: 'operator_name', label: '实际操作人', value: data.initiator.operator_name }] : []),
    ]} /></Card>
    <Card title="需求与设备信息" className="detail-card"><InfoDescriptions items={[
      { key: 'building', label: '所属楼宇', value: data.building.building_name },
      { key: 'profession', label: '设备类型', value: applicant.device_profession },
      { key: 'name', label: '设备名称', value: applicant.device_name },
      { key: 'brand', label: '品牌', value: applicant.brand },
      { key: 'model', label: '规格型号', value: applicant.model },
      { key: 'quantity', label: '数量', value: applicant.quantity ? `${applicant.quantity} ${applicant.unit || ''}` : null },
      { key: 'reason', label: '申请原因', value: applicant.application_reason, span: 3 },
      { key: 'remark', label: '补充说明', value: applicant.applicant_remark, span: 3 },
    ]} /></Card>
    <Card title="审批记录" className="detail-card">{data.review_records.length ? <div className="record-round-list">{data.review_records.map((item) => <ReviewRoundCard key={item.review_round} record={item} />)}</div> : <Typography.Text type="secondary">暂无审批记录</Typography.Text>}</Card>
    <Card title="采购执行" className="detail-card">{data.purchase_execution ? <div className="detail-section-grid">
      <section><Typography.Title level={5}>采购执行信息</Typography.Title><InfoDescriptions items={[
        { key: 'purchaser_name', label: '采购员', value: data.purchase_execution.purchaser_name },
        { key: 'purchaser_mobile', label: '联系方式', value: data.purchase_execution.purchaser_mobile_masked },
        { key: 'purchased_at', label: '操作时间', value: data.purchase_execution.purchased_at },
        { key: 'execution_status', label: '当前执行状态', value: statusLabel(data.status) },
      ]} /></section>
      <section><Typography.Title level={5}>供应商信息</Typography.Title><InfoDescriptions items={[
        { key: 'supplier_name', label: '供应商', value: data.purchase_execution.supplier_name },
        { key: 'contract_contact_info', label: '联系人/联系方式', value: data.purchase_execution.contract_contact_info },
        { key: 'supplier_tax_number', label: '统一社会信用代码', value: data.purchase_execution.supplier_tax_number },
        { key: 'registered_address', label: '注册地址', value: data.purchase_execution.registered_address, span: 2 },
      ]} /></section>
      <section><Typography.Title level={5}>价格与合同</Typography.Title><InfoDescriptions items={[
        { key: 'actual_unit_price', label: '实际单价', value: data.purchase_execution.actual_unit_price },
        { key: 'actual_total_price', label: '实际总价', value: data.purchase_execution.actual_total_price },
        { key: 'tax_rate', label: '税率', value: data.purchase_execution.tax_rate },
        { key: 'bank_name', label: '开户行', value: data.purchase_execution.bank_name },
        { key: 'bank_account', label: '银行账号', value: data.purchase_execution.bank_account },
        { key: 'purchase_remark', label: '采购备注', value: data.purchase_execution.purchase_remark, span: 3 },
      ]} /></section>
    </div> : <Typography.Text type="secondary">暂无采购执行记录</Typography.Text>}</Card>
    <Card title="入库记录" className="detail-card">{data.warehouse_receipt ? <div className="detail-section-grid">
      <section><Typography.Title level={5}>入库执行</Typography.Title><InfoDescriptions items={[
        { key: 'warehouse_name', label: '入库人员', value: data.warehouse_receipt.warehouse_name },
        { key: 'warehouse_mobile', label: '联系方式', value: data.warehouse_receipt.warehouse_mobile_masked },
        { key: 'received_at', label: '入库时间', value: data.warehouse_receipt.received_at },
        { key: 'warehouse_location', label: '入库位置', value: data.warehouse_receipt.warehouse_location },
      ]} /></section>
      <section><Typography.Title level={5}>验收结果</Typography.Title><InfoDescriptions items={[
        { key: 'requested_quantity', label: '申请数量', value: `${applicant.quantity || '—'} ${applicant.unit || ''}` },
        { key: 'received_quantity', label: '实际数量', value: `${data.warehouse_receipt.received_quantity || '—'} ${applicant.unit || ''}` },
        { key: 'acceptance_result', label: '验收结果', value: Number(data.warehouse_receipt.received_quantity) >= Number(applicant.quantity) ? '数量符合' : '存在数量差异' },
        { key: 'receipt_remark', label: '异常或备注', value: data.warehouse_receipt.receipt_remark, span: 3 },
      ]} /></section>
    </div> : <Typography.Text type="secondary">暂无入库记录</Typography.Text>}</Card>
    <Card title="流程历史" className="detail-card"><Typography.Paragraph type="secondary">以下均为历史动作；页面顶部状态为当前唯一状态。</Typography.Paragraph><Timeline items={timeline.map((item) => ({ color: item.to_status === 'REJECTED' ? 'red' : 'blue', content: <div className="timeline-history-item"><strong>{item.operation_summary && !/^[A-Z_]+$/.test(item.operation_summary) ? item.operation_summary : actionLabel(item.action_type)}</strong><p>{item.operator_name} · {item.operator_role_name} · {dayjs(item.operated_at).format('YYYY-MM-DD HH:mm')}</p><Typography.Text>{item.from_status ? `${statusLabel(item.from_status)} → ` : ''}{item.to_status ? statusLabel(item.to_status) : '状态未变化'}{item.assigned_to_name ? ` · 交由 ${item.assigned_to_name} 处理` : ''}</Typography.Text></div> }))} /></Card>
    <Modal open={Boolean(modal)} width={680} title={{ reject: '驳回采购申请', review: '填写审批方案', purchase: '登记采购结果', warehouse: '登记入库' }[modal || 'review']} onCancel={() => setModal(null)} onOk={submitModal} confirmLoading={busy} destroyOnHidden><Form form={form} layout="vertical">
      {modal === 'reject' && <Form.Item name="reason" label="驳回原因" rules={[{ required: true, message: '请填写驳回原因' }]}><Input.TextArea rows={4} /></Form.Item>}
      {modal === 'review' && <>
        <Form.Item name="proposed_supplier_id" label="建议供应商" rules={[{ required: true, message: '请选择建议供应商' }]}><SupplierSelect /></Form.Item>
        <Space.Compact block><Form.Item name="supplier_contact_name" label="联系人" style={{ width: '40%' }}><Input /></Form.Item><Form.Item name="supplier_contact_info" label="联系方式" style={{ width: '60%' }}><Input /></Form.Item></Space.Compact>
        <Form.Item name="supplier_link" label="供应商资料链接"><Input /></Form.Item>
        <Space.Compact block><Form.Item name="estimated_unit_price" label="参考单价" rules={[{ required: true, message: '请填写参考单价' }]} style={{ width: '50%' }}><InputNumber min={0} precision={2} prefix="¥" style={{ width: '100%' }} /></Form.Item><Form.Item label="预计总价" style={{ width: '50%' }}><InputNumber value={calculatedTotal} disabled prefix="¥" style={{ width: '100%' }} /></Form.Item></Space.Compact>
        <Form.Item name="need_contract" label="是否需要合同" rules={[{ required: true, message: '请选择是否需要合同' }]}><Radio.Group options={[{ value: true, label: '是' }, { value: false, label: '否' }]} /></Form.Item>
        {needContract && <Form.Item name="contract_type" label="合同类型" rules={[{ required: true, message: '请选择合同类型' }]}><Select options={['设备采购合同', '框架采购合同', '服务合同', '其他'].map((value) => ({ value, label: value }))} /></Form.Item>}
        <Form.Item name="payment_method" label="付款方式" rules={[{ required: true, message: '请选择付款方式' }]}><Select options={['对公转账', '银行承兑', '分期付款', '其他'].map((value) => ({ value, label: value }))} /></Form.Item>
        <Form.Item name="expected_arrival_date" label="预计到货日期" rules={[{ required: true, message: '请选择预计到货日期' }]}><DatePicker style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="warranty_info" label="质保信息" rules={[{ required: true, message: '请填写质保信息' }]}><Input placeholder="例如：整机三年质保" /></Form.Item>
        <Form.Item name="review_remark" label="审批意见"><Input.TextArea rows={3} /></Form.Item>
      </>}
      {modal === 'purchase' && <>
        <Form.Item name="supplier_id" label="供应商" rules={[{ required: true, message: '请选择供应商' }]}><SupplierSelect /></Form.Item>
        <Space.Compact block><Form.Item name="actual_unit_price" label="实际单价" rules={[{ required: true, message: '请填写实际单价' }]} style={{ width: '50%' }}><InputNumber min={0} precision={2} prefix="¥" style={{ width: '100%' }} /></Form.Item><Form.Item label="实际总价" style={{ width: '50%' }}><InputNumber value={calculatedTotal} disabled prefix="¥" style={{ width: '100%' }} /></Form.Item></Space.Compact>
        <Form.Item name="tax_rate" label="税率"><InputNumber min={0} max={100} precision={2} suffix="%" style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="contract_contact_info" label="合同联系方式"><Input /></Form.Item>
        <Form.Item name="purchase_remark" label="采购备注"><Input.TextArea rows={3} /></Form.Item>
      </>}
      {modal === 'warehouse' && <>
        <Alert type={Number(receivedQuantity) < requestedQuantity ? 'warning' : 'info'} showIcon title={`申请数量：${requestedQuantity} ${data.applicant_fields.unit || ''}`} description={Number(receivedQuantity) < requestedQuantity ? '实际入库数量较少，请在入库备注中说明原因。' : '实际入库数量达到申请数量。'} style={{ marginBottom: 16 }} />
        <Form.Item name="warehouse_location" label="入库位置" rules={[{ required: true, message: '请填写入库位置' }]}><Input /></Form.Item>
        <Form.Item name="received_quantity" label="实际入库数量" rules={[{ required: true, message: '请填写实际入库数量' }]}><InputNumber min={0.001} precision={3} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="receipt_remark" label="入库备注" dependencies={['received_quantity']} rules={[({ getFieldValue }) => ({ validator: (_, value) => Number(getFieldValue('received_quantity')) < requestedQuantity && !String(value || '').trim() ? Promise.reject(new Error('实际入库数量少于申请数量，请说明差异原因')) : Promise.resolve() })]}><Input.TextArea rows={3} /></Form.Item>
      </>}
    </Form></Modal>
    <ContextAssistantDrawer
      open={assistantOpen}
      onClose={() => setAssistantOpen(false)}
      requirementId={requirementId}
      requirementNo={data.requirement_no}
      pageType={assistantRole === 'BUILDING_MANAGER' ? 'REQUIREMENT_REVIEW' : assistantRole === 'PURCHASER' ? 'PURCHASE_EXECUTION' : assistantRole === 'WAREHOUSE_MANAGER' ? 'WAREHOUSE_RECEIPT' : 'REQUIREMENT_DETAIL'}
      role={assistantRole}
      getUserDraft={() => modal ? form.getFieldsValue(true) : undefined}
      onApplySuggestion={data.allowed_actions.some((action) => ['SAVE_REVIEW_FIELDS', 'SAVE_PURCHASE_FIELDS'].includes(action)) ? applySuggestion : undefined}
    />
  </PageShell>
}
