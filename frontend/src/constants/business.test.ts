import { describe, expect, it } from 'vitest'

import { businessErrorMessage, localizeBusinessText, statusLabel } from './business'

describe('business presentation mapping', () => {
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
