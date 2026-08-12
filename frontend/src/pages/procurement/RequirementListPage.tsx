import { useEffect, useState } from 'react'
import { Button, Card } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { DataState, FilterBar, PageShell } from '../../components/PageShell'
import { RequirementTable } from '../../components/RequirementTable'
import { useIdentity } from '../../features/identity/IdentityProvider'
import type { RequirementListData, RequirementListItem, RequirementView } from '../../types/api'

export function RequirementListPage({ title = '我的采购申请', description = '查看你发起的全部采购申请', view = 'CREATED_BY_ME', fixedStatus, showCreate = true }:
  { title?: string; description?: string; view?: RequirementView; fixedStatus?: string; showCreate?: boolean }) {
  const { backend } = useIdentity(); const navigate = useNavigate()
  const [data, setData] = useState<RequirementListData>({ items: [], page: 1, page_size: 20, total: 0 })
  const [search, setSearch] = useState(''); const [status, setStatus] = useState<string | undefined>(fixedStatus)
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null)
  const load = async (page = 1) => { setLoading(true); setError(null); try { setData(await backend.requirements(view, { page, status: fixedStatus || status, keyword: search.trim() || undefined })) }
    catch (err) { setError(err instanceof Error ? err.message : '采购申请加载失败') } finally { setLoading(false) } }
  useEffect(() => { const timer = window.setTimeout(() => { void load(1) }, 350); return () => window.clearTimeout(timer) }, [backend, view, status, fixedStatus, search])
  const items: RequirementListItem[] = data.items
  return <PageShell title={title} description={description} extra={showCreate && <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/requirements/new')}>新建采购申请</Button>}>
    <FilterBar search={search} onSearch={setSearch} status={status} onStatus={fixedStatus ? undefined : setStatus} onReset={() => { setSearch(''); setStatus(fixedStatus) }} />
    <DataState loading={loading} error={error} empty={!items.length} onRetry={() => load(data.page)}>
      <Card className="table-card"><RequirementTable items={items} total={data.total} page={data.page} pageSize={data.page_size} onPage={load} /></Card>
    </DataState>
  </PageShell>
}
