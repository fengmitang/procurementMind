export const DEVICE_PROFESSIONS = [
  '10kV开关柜',
  '变压器',
  '400V配电柜',
  'UPS',
  '高压直流',
  '蓄电池',
  '监控',
  '冷水机组',
  'SHU',
  '冷却塔',
  '冷却泵',
  '机房环境',
  '水系统',
  '传输',
  '服务器',
  '运维工具',
  '列间空调',
] as const

export const statusLabels: Record<string, string> = {
  DRAFT: '草稿',
  PENDING_REVIEW: '待审批',
  REJECTED: '已驳回',
  PENDING_PURCHASE: '待采购',
  PURCHASING: '采购中',
  PENDING_WAREHOUSE: '待入库',
  COMPLETED: '已完成',
  APPROVED: '已通过',
  ACTIVE: '生效中',
  RELEASED: '已解除',
  NORMAL: '正常',
  HISTORY: '有历史记录',
  BLACKLISTED: '黑名单生效中',
  INACTIVE: '已停用',
  PERMANENT: '长期有效',
  LIMITED: '限期有效',
}

export const fieldLabels: Record<string, string> = {
  device_profession: '设备类型', device_name: '设备名称', brand: '品牌', model: '规格型号',
  quantity: '申请数量', unit: '单位', application_reason: '申请原因', applicant_remark: '补充说明',
  review_round: '审批轮次', review_status: '审批状态', review_result: '审批结果',
  review_opinion: '审批意见', review_remark: '审批意见', proposed_supplier: '建议供应商',
  proposed_supplier_name: '建议供应商', supplier_contact_name: '供应商联系人',
  supplier_contact_info: '联系方式', supplier_link: '供应商资料链接',
  estimated_unit_price: '参考单价', estimated_total_price: '预计总价',
  need_contract: '是否需要合同', contract_type: '合同类型', payment_method: '付款方式',
  expected_arrival_date: '预计到货日期', warranty_info: '质保信息', reviewed_at: '审批时间',
  supplier_name: '供应商', supplier_tax_number: '统一社会信用代码', bank_name: '开户银行',
  bank_account: '银行账号', registered_address: '注册地址', contract_contact_info: '合同联系方式',
  actual_unit_price: '实际单价', actual_total_price: '实际总价', tax_rate: '税率',
  purchased_at: '采购时间', purchase_remark: '采购备注', warehouse_location: '入库位置',
  received_quantity: '实际入库数量', receipt_remark: '入库备注', received_at: '入库时间',
}

export const enumLabels: Record<string, string> = {
  ...statusLabels,
  TRUE: '是', FALSE: '否',
}

export const actionLabels: Record<string, string> = {
  CREATE_DRAFT: '创建采购申请草稿',
  SAVE_APPLICANT_FIELDS: '保存申请信息',
  SUBMIT: '提交采购申请',
  RESUBMIT: '重新提交采购申请',
  REJECT: '驳回采购申请',
  SUBMIT_PURCHASER: '审批通过并交采购',
  START_PURCHASE: '开始采购',
  SAVE_PURCHASE_FIELDS: '登记采购结果',
  SUBMIT_WAREHOUSE: '提交仓库入库',
  SAVE_WAREHOUSE_FIELDS: '登记入库结果',
  COMPLETE: '完成采购流程',
}

export const statusLabel = (value: string) => statusLabels[value] || value
export const fieldLabel = (value: string) => fieldLabels[value] || '相关信息'
export const actionLabel = (value: string) => actionLabels[value] || '采购流程操作'
export const enumLabel = (value: unknown) => {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value !== 'string') return value
  return enumLabels[value] || value
}

export function localizeBusinessText(value: string): string {
  let localized = value
  for (const [code, label] of Object.entries(statusLabels)) {
    localized = localized.replace(new RegExp(`\\b${code}\\b`, 'g'), label)
  }
  for (const [field, label] of Object.entries(fieldLabels)) {
    localized = localized.replace(new RegExp(`\\b${field}\\b`, 'g'), label)
  }
  for (const [action, label] of Object.entries(actionLabels)) {
    localized = localized.replace(new RegExp(`\\b${action}\\b`, 'g'), label)
  }
  return localized
}

const errorMessages: Record<string, string> = {
  CONCURRENT_MODIFICATION: '该采购申请已被其他人更新，请刷新页面后重试。',
  PERMISSION_DENIED: '你没有执行此操作的权限。',
  INVALID_STATUS: '当前采购状态不允许执行此操作，请刷新页面确认最新状态。',
  SUPPLIER_NOT_FOUND: '当前选择的供应商无效或已停用，请重新选择供应商。',
  SUPPLIER_MATCH_CONFLICT: '已存在相同或相似供应商，请先核对现有供应商主档。',
  REQUIREMENT_NOT_FOUND: '采购申请不存在或已不可访问。',
  REQUEST_TIMEOUT: '请求处理时间较长且已超时，请稍后重试。',
  NETWORK_ERROR: '服务暂时不可用，请稍后重试。',
  INTERNAL_ERROR: '系统暂时无法完成操作，请稍后重试。',
}

export function businessErrorMessage(code: string | undefined, message: string | undefined, data: unknown): string {
  if (code && errorMessages[code]) return errorMessages[code]
  const details = data && typeof data === 'object' ? data as Record<string, unknown> : null
  const fields = Array.isArray(details?.fields) ? details.fields.filter((item): item is string => typeof item === 'string') : []
  if (code === 'MISSING_REQUIRED_FIELDS' && fields.length) {
    return `信息尚未填写完整，请补充${fields.map(fieldLabel).join('、')}后再提交。`
  }
  const validationErrors = Array.isArray(details?.errors) ? details.errors as Record<string, unknown>[] : []
  if (code === 'VALIDATION_ERROR' && validationErrors.length) {
    const location = validationErrors[0].loc
    const field = Array.isArray(location) ? [...location].reverse().find((item) => typeof item === 'string') : null
    return field ? `请检查${fieldLabel(String(field))}，填写内容不符合要求。` : '提交内容不完整或格式不正确，请检查后重试。'
  }
  if (message && !/\b[a-z]+_[a-z_]+\b/.test(message) && !/Traceback|HTTP\s*\d|pydantic|sql/i.test(message)) return message
  return '操作未能完成，请检查填写内容后重试。'
}
