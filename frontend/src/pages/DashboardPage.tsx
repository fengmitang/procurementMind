import { useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Row, Space, Statistic, Typography } from 'antd'
import { ArrowRightOutlined, AuditOutlined, FormOutlined, MessageOutlined, ShopOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { PageShell } from '../components/PageShell'
import { RequirementTable } from '../components/RequirementTable'
import { useIdentity } from '../features/identity/IdentityProvider'
import type { RequirementListItem } from '../types/api'

export function DashboardPage() {
  const { user, backend, roleCodes, taskCount } = useIdentity(); const navigate = useNavigate()
  const [mine, setMine] = useState<RequirementListItem[]>([]); const [pending, setPending] = useState<RequirementListItem[]>([])
  const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(true)
  const load = async () => {
    setLoading(true); setError(null)
    try {
      const [created, tasks] = await Promise.all([backend.requirements('CREATED_BY_ME', { page_size: 6 }), backend.requirements('PENDING_FOR_ME', { page_size: 6 })])
      setMine(created.items); setPending(tasks.items)
    } catch (err) { setError(err instanceof Error ? err.message : '工作台加载失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [backend])
  const inProgress = mine.filter((item) => !['DRAFT', 'REJECTED', 'COMPLETED'].includes(item.status)).length
  const completed = mine.filter((item) => item.status === 'COMPLETED').length
  return <PageShell title="工作台" description="关注与你直接相关的采购进度和岗位待办">
    <Card className="welcome-card" variant="borderless"><div>
      <Typography.Text className="welcome-kicker">PROCUREMENT COLLABORATION</Typography.Text>
      <Typography.Title level={2}>您好，{user.name}</Typography.Title>
      <Typography.Paragraph>欢迎使用数据中心采购智能协同平台。今天有 <strong>{taskCount}</strong> 项岗位任务等待你处理。</Typography.Paragraph>
      <Space wrap><Button type="primary" size="large" icon={<FormOutlined />} onClick={() => navigate('/requirements/new')}>手动新建采购申请</Button>
        {roleCodes.includes('BUILDING_MANAGER')&&<Button size="large" icon={<AuditOutlined />} onClick={()=>navigate('/approval/pending')}>审批申请</Button>}
        {roleCodes.includes('PURCHASER')&&<Button size="large" icon={<ShopOutlined />} onClick={()=>navigate('/purchasing/pending')}>采购</Button>}
        <Button size="large" icon={<MessageOutlined />} onClick={() => navigate('/assistant')}>咨询智能助手</Button></Space>
    </div><div className="welcome-orbit"><span>AI</span><small>知识 + 业务事实</small></div></Card>
    {error && <Alert type="error" showIcon title={error} action={<Button onClick={load}>重试</Button>} />}
    <Row gutter={[16,16]} className="metric-row">
      <Col xs={24} md={8}><Card><Statistic title="待我处理" value={taskCount} suffix="项" /><Typography.Text type="secondary">岗位任务与待继续申请</Typography.Text></Card></Col>
      <Col xs={24} md={8}><Card><Statistic title="进行中" value={inProgress} suffix="项" /><Typography.Text type="secondary">我发起且正在流转</Typography.Text></Card></Col>
      <Col xs={24} md={8}><Card><Statistic title="已完成" value={completed} suffix="项" /><Typography.Text type="secondary">我发起的已完成申请</Typography.Text></Card></Col>
    </Row>
    <Row gutter={[18,18]}>
      <Col xs={24} xl={12}><Card title="我的待办" extra={<Button type="link" onClick={() => navigate('/requirements')}>查看全部 <ArrowRightOutlined /></Button>}>
        <RequirementTable items={pending.slice(0,5)} loading={loading} />
      </Card></Col>
      <Col xs={24} xl={12}><Card title="最近采购申请" extra={<Button type="link" onClick={() => navigate('/requirements')}>查看全部 <ArrowRightOutlined /></Button>}>
        <RequirementTable items={mine.slice(0,5)} loading={loading} />
      </Card></Col>
    </Row>
  </PageShell>
}
