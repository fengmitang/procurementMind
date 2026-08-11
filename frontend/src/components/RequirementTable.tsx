import { Button, Table, Typography, type TableProps } from 'antd'
import { EyeOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { RequirementListItem } from '../types/api'
import { StatusTag } from './StatusTag'

export function RequirementTable({ items, loading = false, total, page = 1, pageSize = 20, onPage }: {
  items: RequirementListItem[]; loading?: boolean; total?: number; page?: number; pageSize?: number; onPage?: (page: number) => void
}) {
  const navigate = useNavigate()
  const columns: TableProps<RequirementListItem>['columns'] = [
    { title: '采购单号', dataIndex: 'requirement_no', render: (value) => <Typography.Text strong>{value}</Typography.Text> },
    { title: '设备名称', dataIndex: 'device_name', render: (value) => value || '待完善' },
    { title: '当前状态', dataIndex: 'status', render: (value) => <StatusTag status={value} /> },
    { title: '当前处理人', dataIndex: 'current_handler_name', render: (value) => value || '—' },
    { title: '操作', width: 110, render: (_, row) => <Button type="link" icon={<EyeOutlined />} onClick={() => navigate(`/requirements/${row.requirement_id}`)}>查看详情</Button> },
  ]
  return <Table rowKey="requirement_id" columns={columns} dataSource={items} loading={loading} scroll={{ x: 700 }} pagination={total === undefined ? false : {
    current: page, pageSize, total, showSizeChanger: false, showTotal: (value) => `共 ${value} 条`, onChange: onPage,
  }} />
}
