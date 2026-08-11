import type { ReactNode } from 'react'
import { Alert, Button, Card, Empty, Input, Select, Space, Spin, Typography } from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'

export function PageShell({ title, description, extra, children }: {
  title: string; description?: string; extra?: ReactNode; children: ReactNode
}) {
  return <div className="page-shell">
    <div className="page-heading">
      <div><Typography.Title level={2}>{title}</Typography.Title>{description && <Typography.Text type="secondary">{description}</Typography.Text>}</div>
      {extra && <Space>{extra}</Space>}
    </div>
    {children}
  </div>
}

export function FilterBar({ search, onSearch, status, onStatus, onReset, extra }: {
  search: string; onSearch: (value: string) => void; status?: string; onStatus?: (value?: string) => void;
  onReset: () => void; extra?: ReactNode
}) {
  return <Card className="filter-card" variant="borderless"><Space wrap>
    <Input allowClear prefix={<SearchOutlined />} value={search} onChange={(e) => onSearch(e.target.value)} placeholder="搜索单号或设备" style={{ width: 240 }} />
    {onStatus && <Select allowClear value={status || undefined} onChange={onStatus} placeholder="全部状态" style={{ width: 150 }} options={[
      ['DRAFT','草稿'],['PENDING_REVIEW','待审批'],['REJECTED','已驳回'],['PENDING_PURCHASE','待采购'],
      ['PURCHASING','采购中'],['PENDING_WAREHOUSE','待入库'],['COMPLETED','已完成'],
    ].map(([value,label]) => ({ value, label }))} />}
    {extra}<Button icon={<ReloadOutlined />} onClick={onReset}>重置</Button>
  </Space></Card>
}

export function DataState({ loading, error, empty, onRetry, children }: {
  loading: boolean; error?: string | null; empty?: boolean; onRetry?: () => void; children: ReactNode
}) {
  if (loading) return <Card><div className="center-state"><Spin description="正在加载真实业务数据" /></div></Card>
  if (error) return <Alert type="error" showIcon title="数据加载失败" description={error} action={onRetry && <Button onClick={onRetry}>重试</Button>} />
  if (empty) return <Card><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无符合条件的数据" /></Card>
  return <>{children}</>
}
