import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { App, Spin } from 'antd'
import { BackendClient } from '../../services/backendClient'
import { AgentClient } from '../../services/agentClient'
import type { CurrentUser, RoleCode } from '../../types/api'

export const demoIdentities = [
  { id: 'demo_user_001', label: '演示需求人', description: 'Full Demo' },
  { id: 'demo_user_002', label: '演示楼长', description: 'Full Demo' },
  { id: 'demo_user_003', label: '演示采购员', description: 'Full Demo' },
  { id: 'demo_user_004', label: '演示仓管员', description: 'Full Demo' },
  { id: 'demo_user_005', label: '演示管理员', description: 'Full Demo' },
  { id: 'demo_user_006', label: '演示需求人兼楼长', description: 'Full Demo' },
  { id: 'demo_user_007', label: '演示楼长兼采购员', description: 'Full Demo' },
  { id: 'demo_user_008', label: '演示采购员兼仓管', description: 'Full Demo' },
  { id: 'test-user-01', label: '测试需求人', description: 'TEST Fixture' },
  { id: 'test-user-02', label: '一号楼楼长', description: 'TEST Fixture' },
  { id: 'test-user-03', label: '测试采购员', description: 'TEST Fixture' },
  { id: 'test-user-04', label: '仓库管理员', description: 'TEST Fixture' },
  { id: 'test-user-05', label: '系统管理员', description: 'TEST Fixture' },
  { id: 'test-user-07', label: '二号楼楼长', description: 'TEST Fixture' },
] as const

interface IdentityValue {
  platformUserId: string
  user: CurrentUser
  roleCodes: RoleCode[]
  backend: BackendClient
  agent: AgentClient
  switchIdentity: (id: string) => void
  reload: () => Promise<void>
  taskCount: number
  refreshTaskCount: () => Promise<void>
}

const IdentityContext = createContext<IdentityValue | null>(null)

export function IdentityProvider({ children }: { children: ReactNode }) {
  const { message } = App.useApp()
  const [platformUserId, setPlatformUserId] = useState(() => localStorage.getItem('pm-demo-user') || 'test-user-01')
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [taskCount, setTaskCount] = useState(0)
  const backend = useMemo(() => new BackendClient(() => platformUserId), [platformUserId])
  const agent = useMemo(() => new AgentClient(() => platformUserId), [platformUserId])

  const reload = async () => {
    try { setUser(await backend.me()) }
    catch (error) { message.error(error instanceof Error ? error.message : '身份加载失败') }
  }

  const refreshTaskCount = async () => {
    if (!user) return
    const roleCodes = user.roles.map((role) => role.role_code)
    const status = roleCodes.includes('BUILDING_MANAGER') ? 'PENDING_REVIEW' : roleCodes.includes('WAREHOUSE_MANAGER') ? 'PENDING_WAREHOUSE' : undefined
    if (!roleCodes.some((role) => ['BUILDING_MANAGER', 'PURCHASER', 'WAREHOUSE_MANAGER'].includes(role))) { setTaskCount(0); return }
    try { setTaskCount((await backend.requirements('PENDING_FOR_ME', { page: 1, page_size: 1, status })).total) }
    catch { setTaskCount(0) }
  }

  useEffect(() => { void reload() }, [backend])
  useEffect(() => { void refreshTaskCount() }, [backend, user])

  const switchIdentity = (id: string) => {
    localStorage.setItem('pm-demo-user', id)
    setUser(null)
    setTaskCount(0)
    setPlatformUserId(id)
  }

  if (!user) return <div className="app-loading"><Spin size="large" description="正在载入身份与权限" /></div>

  return (
    <IdentityContext.Provider value={{
      platformUserId, user, backend, agent, switchIdentity, reload, taskCount, refreshTaskCount,
      roleCodes: user.roles.map((role) => role.role_code),
    }}>
      {children}
    </IdentityContext.Provider>
  )
}

export function useIdentity() {
  const value = useContext(IdentityContext)
  if (!value) throw new Error('IdentityProvider is missing')
  return value
}
