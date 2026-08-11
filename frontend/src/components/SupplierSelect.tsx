import { useEffect, useRef, useState } from 'react'
import { Select, Tag, Typography } from 'antd'
import { useIdentity } from '../features/identity/IdentityProvider'
import type { SupplierSummary } from '../types/api'

interface SupplierSelectProps {
  value?: number
  onChange?: (value: number | undefined, supplier?: SupplierSummary) => void
  disabled?: boolean
  placeholder?: string
}

export function SupplierSelect({ value, onChange, disabled, placeholder = '搜索供应商名称' }: SupplierSelectProps) {
  const { backend } = useIdentity()
  const [items, setItems] = useState<SupplierSummary[]>([])
  const [loading, setLoading] = useState(false)
  const sequence = useRef(0)
  const searchTimer = useRef<number | undefined>(undefined)

  const load = async (keyword?: string) => {
    const current = ++sequence.current
    setLoading(true)
    try {
      const data = await backend.suppliers({ keyword, page_size: 30, status: 'ACTIVE' })
      if (current === sequence.current) setItems(data.items)
    } catch {
      if (current === sequence.current) setItems([])
    } finally {
      if (current === sequence.current) setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    return () => window.clearTimeout(searchTimer.current)
  }, [backend])

  return <Select
    showSearch
    allowClear
    value={value}
    disabled={disabled}
    placeholder={placeholder}
    filterOption={false}
    loading={loading}
    onSearch={(keyword) => {
      window.clearTimeout(searchTimer.current)
      searchTimer.current = window.setTimeout(() => void load(keyword.trim() || undefined), 300)
    }}
    onChange={(next) => onChange?.(next, items.find((item) => item.supplier_id === next))}
    options={items.map((item) => ({
      value: item.supplier_id,
      label: <div><Typography.Text>{item.supplier_name}</Typography.Text>{item.blacklist_status === 'BLACKLISTED' && <Tag color="error" style={{ marginLeft: 8 }}>存在有效风险</Tag>}</div>,
    }))}
    notFoundContent={loading ? '正在查询供应商…' : '没有匹配的供应商'}
  />
}
