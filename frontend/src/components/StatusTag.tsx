import { Tag } from 'antd'
import { statusLabel } from '../constants/business'

const colors: Record<string, string> = {
  DRAFT: 'default', PENDING_REVIEW: 'processing', REJECTED: 'error', PENDING_PURCHASE: 'gold',
  PURCHASING: 'cyan', PENDING_WAREHOUSE: 'purple', COMPLETED: 'success', ACTIVE: 'success', BLACKLISTED: 'error',
}

export function StatusTag({ status }: { status: string }) {
  return <Tag color={colors[status] || 'blue'}>{statusLabel(status)}</Tag>
}

export { statusLabel }
