import { requestJson } from './http'
import type {
  AdminEmployee, AdminOverview, AdminReferences, AgentConversationSummary, AgentStoredMessage, ApplicantFields, CurrentUser, PagedData, PurchaseRecord, RequirementDetail,
  RequirementListData, RequirementMutation, RequirementView, SupplierDetail, SupplierRisk, SupplierSummary, TimelineItem,
} from '../types/api'

type Query = Record<string, string | number | boolean | null | undefined>

export class BackendClient {
  constructor(private readonly getUserId: () => string) {}

  private proxy<T>(method: string, path: string, query: Query = {}, body?: Record<string, any>): Promise<T> {
    return requestJson<T>('/demo-api/proxy', {
      method: 'POST',
      body: JSON.stringify({
        platform_user_id: this.getUserId(), method, path,
        query: Object.fromEntries(Object.entries(query).filter(([, value]) => value !== undefined && value !== null && value !== '')),
        body: body ?? null,
      }),
    })
  }

  me = () => this.proxy<CurrentUser>('GET', '/api/v1/users/me')
  requirements = (view: RequirementView, params: Query = {}) =>
    this.proxy<RequirementListData>('GET', '/api/v1/requirements', { view, page: 1, page_size: 20, ...params })
  requirement = (id: number) => this.proxy<RequirementDetail>('GET', `/api/v1/requirements/${id}`)
  timeline = (id: number) => this.proxy<{ items: TimelineItem[] }>('GET', `/api/v1/requirements/${id}/timeline`)
  agentConversations = () => this.proxy<PagedData<AgentConversationSummary>>('GET', '/api/v1/agent/conversations', { page: 1, page_size: 50 })
  agentMessages = (conversationId: number) => this.proxy<PagedData<AgentStoredMessage>>('GET', `/api/v1/agent/conversations/${conversationId}/messages`, { page: 1, page_size: 200 })
  createRequirement = (buildingId: number) =>
    this.proxy<RequirementMutation>('POST', '/api/v1/requirements', {}, { building_id: buildingId })
  saveApplicantFields = (id: number, version: number, fields: ApplicantFields) =>
    this.proxy<{ requirement_id: number; version: number; fields_complete: boolean; missing_fields: string[] }>(
      'PATCH', `/api/v1/requirements/${id}/applicant-fields`, {}, { expected_version: version, fields },
    )
  handlerCandidates = (id: number, role: string) =>
    this.proxy<{ items: { employee_id: number; name: string; mobile: string | null }[]; auto_selected_employee_id: number | null }>(
      'GET', `/api/v1/requirements/${id}/handler-candidates`, { target_role: role },
    )
  action = (id: number, action: string, body: Record<string, any>) =>
    this.proxy<RequirementMutation>('POST', `/api/v1/requirements/${id}/${action}`, {}, body)
  saveReviewFields = (id: number, version: number, fields: Record<string, any>) =>
    this.proxy<{ version: number }>('PATCH', `/api/v1/requirements/${id}/review-fields`, {}, { expected_version: version, fields })
  savePurchaseFields = (id: number, version: number, fields: Record<string, any>) =>
    this.proxy<{ version: number }>('PATCH', `/api/v1/requirements/${id}/purchase-fields`, {}, { expected_version: version, fields })
  saveWarehouseFields = (id: number, version: number, fields: Record<string, any>) =>
    this.proxy<{ version: number }>('PATCH', `/api/v1/requirements/${id}/warehouse-fields`, {}, { expected_version: version, fields })
  purchaseRecords = (params: Query = {}) =>
    this.proxy<PagedData<PurchaseRecord>>('GET', '/api/v1/purchase-records', { page: 1, page_size: 20, ...params })
  suppliers = (params: Query = {}) =>
    this.proxy<PagedData<SupplierSummary>>('GET', '/api/v1/suppliers', { page: 1, page_size: 20, ...params })
  supplier = (id: number) => this.proxy<SupplierDetail>('GET', `/api/v1/suppliers/${id}`)
  supplierRisks = (params: Query = {}) =>
    this.proxy<PagedData<SupplierRisk>>('GET', '/api/v1/suppliers/risks/building-scope', { page: 1, page_size: 20, ...params })
  adminOverview = () => this.proxy<AdminOverview>('GET', '/api/v1/admin/overview')
  adminReferences = () => this.proxy<AdminReferences>('GET', '/api/v1/admin/references')
  adminEmployees = (params: Query = {}) => this.proxy<PagedData<AdminEmployee>>('GET', '/api/v1/admin/employees', { page: 1, page_size: 20, ...params })
  createAdminEmployee = (body: Record<string, any>) => this.proxy<AdminEmployee>('POST', '/api/v1/admin/employees', {}, body)
  updateAdminEmployee = (id: number, body: Record<string, any>) => this.proxy<AdminEmployee>('PATCH', `/api/v1/admin/employees/${id}`, {}, body)
  deactivateAdminEmployee = (id: number, actionToken: string) => this.proxy<AdminEmployee>('DELETE', `/api/v1/admin/employees/${id}`, {}, { action_token: actionToken })
}
