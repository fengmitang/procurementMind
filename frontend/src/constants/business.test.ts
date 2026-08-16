import { describe, expect, it } from 'vitest'

import {
  businessErrorMessage,
  DEVICE_PROFESSIONS,
  localizeBusinessText,
  statusLabel,
} from './business'

describe('business presentation mapping', () => {
  it('uses the formal device profession catalog', () => {
    expect(DEVICE_PROFESSIONS).toEqual([
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
    ])
  })

  it('localizes workflow states and backend field names', () => {
    expect(statusLabel('PENDING_WAREHOUSE')).toBe('待入库')
    expect(localizeBusinessText('review_status=COMPLETED, review_result=APPROVED')).toBe(
      '审批状态=已完成, 审批结果=已通过',
    )
  })

  it('does not expose backend field identifiers in validation errors', () => {
    const message = businessErrorMessage(
      'MISSING_REQUIRED_FIELDS',
      'expected_arrival_date, warranty_info required',
      { fields: ['expected_arrival_date', 'warranty_info'] },
    )
    expect(message).toContain('预计到货日期')
    expect(message).toContain('质保信息')
    expect(message).not.toContain('expected_arrival_date')
  })

  it('returns an actionable supplier selection error', () => {
    expect(businessErrorMessage('SUPPLIER_NOT_FOUND', 'supplier_id invalid', null)).toBe(
      '当前选择的供应商无效或已停用，请重新选择供应商。',
    )
  })
})
