import { useMemo, useState } from 'react'
import { Avatar, Badge, Dropdown, Layout, Menu, Select, Space, Typography, type MenuProps } from 'antd'
import {
  ApartmentOutlined, AuditOutlined, DashboardOutlined, DatabaseOutlined, InboxOutlined, MenuFoldOutlined,
  MenuUnfoldOutlined, MessageOutlined, ProfileOutlined, SafetyCertificateOutlined, ShopOutlined,
  TeamOutlined, UserOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { demoIdentities, useIdentity } from '../features/identity/IdentityProvider'

const { Header, Sider, Content } = Layout

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const { user, roleCodes, platformUserId, switchIdentity, taskCount } = useIdentity()
  const navigate = useNavigate(); const location = useLocation()
  const menuItems = useMemo<MenuProps['items']>(() => {
    if (roleCodes.includes('ADMIN')) return [
      { key: '/admin', icon: <DashboardOutlined />, label: '工作台' },
      { key: '/assistant', icon: <MessageOutlined />, label: '智能助手' },
      { key: '/admin/employees', icon: <TeamOutlined />, label: '员工管理' },
      { type: 'group', label: '采购数据', children: [
        { key: '/admin/requirements', icon: <ProfileOutlined />, label: '采购清单' },
      ] },
      { type: 'group', label: '供应商数据', children: [
        { key: '/admin/suppliers', icon: <DatabaseOutlined />, label: '供应商查询' },
      ] },
    ]
    const items: MenuProps['items'] = [
      { key: '/', icon: <DashboardOutlined />, label: '工作台' },
      { key: '/assistant', icon: <MessageOutlined />, label: '智能助手' },
      { type: 'group', label: '我的采购', children: [{ key: '/requirements', icon: <ProfileOutlined />, label: '我的采购申请' }] },
    ]
    if (roleCodes.includes('BUILDING_MANAGER')) items.push({ type: 'group', label: '审批工作', children: [
      { key: '/approval/pending', icon: <AuditOutlined />, label: <Badge count={taskCount} size="small" offset={[12, 0]}>待我审批</Badge> },
      { key: '/approval/records', icon: <ApartmentOutlined />, label: '楼宇采购记录' },
      { key: '/approval/risks', icon: <SafetyCertificateOutlined />, label: '供应商风险' },
    ] })
    if (roleCodes.includes('PURCHASER')) items.push({ type: 'group', label: '采购工作', children: [
      { key: '/purchasing/pending', icon: <ShopOutlined />, label: <Badge count={taskCount} size="small" offset={[12, 0]}>待采购</Badge> },
      { key: '/purchasing/records', icon: <ProfileOutlined />, label: '采购记录' },
      { key: '/suppliers', icon: <TeamOutlined />, label: '供应商管理' },
    ] })
    if (roleCodes.includes('WAREHOUSE_MANAGER')) items.push({ type: 'group', label: '入库工作', children: [
      { key: '/warehouse/pending', icon: <InboxOutlined />, label: <Badge count={taskCount} size="small" offset={[12, 0]}>待入库</Badge> },
      { key: '/warehouse/records', icon: <ProfileOutlined />, label: '入库记录' },
    ] })
    return items
  }, [roleCodes, taskCount])
  const selected = '/' + location.pathname.split('/').filter(Boolean).slice(0, location.pathname.includes('/requirements/') ? 1 : 2).join('/')
  const userMenu: MenuProps['items'] = [
    { key: 'profile', icon: <UserOutlined />, label: '个人信息', onClick: () => navigate('/profile') },
    { type: 'divider' }, { key: 'logout', label: '退出登录（开发环境）', disabled: true },
  ]
  return <Layout className="app-layout">
    <Sider width={252} collapsedWidth={76} collapsed={collapsed} className="app-sider" trigger={null}>
      <div className="brand-block"><div className="brand-mark">采</div>{!collapsed && <div><strong>采购智能协同</strong><span>Procurement Mind</span></div>}</div>
      <Menu mode="inline" selectedKeys={[selected]} items={menuItems} onClick={({ key }) => navigate(key)} />
      {!collapsed && <div className="sider-foot"><span className="live-dot" />Backend 与 Agent 联调环境</div>}
    </Sider>
    <Layout>
      <Header className="app-header">
        <button className="collapse-button" aria-label="折叠菜单" onClick={() => setCollapsed((value) => !value)}>{collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}</button>
        <div className="header-spacer" />
        {import.meta.env.DEV && <Select className="identity-switch" value={platformUserId} onChange={switchIdentity} options={[
          { label: 'Full Demo', options: demoIdentities.filter((item) => item.description === 'Full Demo').map((item) => ({ value: item.id, label: `${item.label}（Full Demo）` })) },
          { label: 'Legacy TEST', options: demoIdentities.filter((item) => item.description === 'TEST Fixture').map((item) => ({ value: item.id, label: `${item.label}（TEST Fixture）` })) },
        ]} />}
        <Dropdown menu={{ items: userMenu }} placement="bottomRight"><Space className="user-trigger">
          <Avatar style={{ background: '#1677ff' }}>{user.name.slice(0, 1)}</Avatar>
          <div className="user-copy"><Typography.Text strong>{user.name}</Typography.Text><span>{user.roles.map((role) => role.role_name).join(' / ')}</span></div>
        </Space></Dropdown>
      </Header>
      <Content className="app-content"><Outlet /></Content>
    </Layout>
  </Layout>
}
