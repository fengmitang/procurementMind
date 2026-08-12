import { HashRouter, Route, Routes } from 'react-router-dom'
import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { appTheme } from '../theme/theme'
import { IdentityProvider } from '../features/identity/IdentityProvider'
import { AppLayout } from '../layouts/AppLayout'
import { DashboardPage } from '../pages/DashboardPage'
import { AssistantPage } from '../pages/assistant/AssistantPage'
import { RequirementListPage } from '../pages/procurement/RequirementListPage'
import { RequirementFormPage } from '../pages/procurement/RequirementFormPage'
import { RequirementDetailPage } from '../pages/procurement/RequirementDetailPage'
import { BuildingRecordsPage, PendingApprovalPage, PendingPurchasePage, PendingWarehousePage, PurchaseRecordsPage, SupplierManagementPage, SupplierRiskPage } from '../pages/role/RolePages'
import { ProfilePage } from '../pages/ProfilePage'
import { AdminDashboardPage, AdminEmployeesPage } from '../pages/admin/AdminPages'
import { useIdentity } from '../features/identity/IdentityProvider'

function RoleDashboard() {
  const { roleCodes } = useIdentity()
  return roleCodes.includes('ADMIN') ? <AdminDashboardPage /> : <DashboardPage />
}

export function App() {
  return <ConfigProvider locale={zhCN} theme={appTheme}><AntApp><HashRouter><IdentityProvider><Routes>
    <Route element={<AppLayout />}>
      <Route index element={<RoleDashboard />} />
      <Route path="assistant" element={<AssistantPage />} />
      <Route path="requirements" element={<RequirementListPage />} />
      <Route path="requirements/new" element={<RequirementFormPage />} />
      <Route path="requirements/:id/edit" element={<RequirementFormPage />} />
      <Route path="requirements/:id" element={<RequirementDetailPage />} />
      <Route path="approval/pending" element={<PendingApprovalPage />} />
      <Route path="approval/records" element={<BuildingRecordsPage />} />
      <Route path="approval/risks" element={<SupplierRiskPage />} />
      <Route path="purchasing/pending" element={<PendingPurchasePage />} />
      <Route path="purchasing/records" element={<PurchaseRecordsPage />} />
      <Route path="suppliers" element={<SupplierManagementPage />} />
      <Route path="warehouse/pending" element={<PendingWarehousePage />} />
      <Route path="warehouse/records" element={<PurchaseRecordsPage warehouse />} />
      <Route path="admin" element={<AdminDashboardPage />} />
      <Route path="admin/employees" element={<AdminEmployeesPage />} />
      <Route path="admin/requirements" element={<RequirementListPage title="采购清单" description="查看全部采购申请，只读访问" view="ADMIN_SCOPE" showCreate={false} />} />
      <Route path="admin/suppliers" element={<SupplierManagementPage title="供应商查询" description="查看全部供应商主档，只读访问" />} />
      <Route path="profile" element={<ProfilePage />} />
      <Route path="*" element={<RoleDashboard />} />
    </Route>
  </Routes></IdentityProvider></HashRouter></AntApp></ConfigProvider>
}
