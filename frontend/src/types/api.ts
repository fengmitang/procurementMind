export type RoleCode = 'APPLICANT' | 'BUILDING_MANAGER' | 'PURCHASER' | 'WAREHOUSE_MANAGER' | 'ADMIN'

export interface ApiEnvelope<T> {
  success: boolean
  trace_id: string
  code?: string
  message?: string
  data: T
}

export interface UserRole { role_id: number; role_code: RoleCode; role_name: string }
export interface UserBuilding { building_id: number; building_name: string; is_primary: boolean }
export interface CurrentUser {
  employee_id: number
  employee_no: string | null
  name: string
  mobile: string | null
  status: string
  platform_type: string
  platform_user_id: string
  roles: UserRole[]
  buildings: UserBuilding[]
}

export type RequirementView = 'CREATED_BY_ME' | 'PENDING_FOR_ME' | 'PROCESSED_BY_ME' | 'BUILDING_SCOPE' | 'ADMIN_SCOPE'
export interface RequirementListItem {
  requirement_id: number
  requirement_no: string
  device_name: string | null
  status: string
  current_handler_name: string | null
}
export interface PagedData<T> { items: T[]; page: number; page_size: number; total: number }
export type RequirementListData = PagedData<RequirementListItem>

export interface ApplicantFields {
  device_profession?: string | null
  device_name?: string | null
  brand?: string | null
  model?: string | null
  quantity?: number | string | null
  unit?: string | null
  application_reason?: string | null
  applicant_remark?: string | null
}

export interface RequirementDetail {
  requirement_id: number
  requirement_no: string
  status: string
  version: number
  building: Record<string, any>
  current_handler: Record<string, any> | null
  initiator: Record<string, any>
  applicant_fields: ApplicantFields
  review_records: Record<string, any>[]
  purchase_execution: Record<string, any> | null
  warehouse_receipt: Record<string, any> | null
  missing_fields: string[]
  allowed_actions: string[]
}

export interface RequirementMutation {
  requirement_id: number
  requirement_no?: string | null
  status: string
  version: number
  current_handler?: Record<string, any> | null
}

export interface TimelineItem {
  log_id: number
  action_type: string
  operator_name: string
  operator_role_name: string
  from_status: string | null
  to_status: string | null
  assigned_to_name: string | null
  operation_summary: string | null
  operated_at: string
}

export interface PurchaseRecord {
  requirement_id: number
  requirement_no: string
  device_name: string | null
  brand: string | null
  model: string | null
  quantity: string | null
  unit: string | null
  status: string
  supplier_id: number | null
  supplier_name: string | null
  actual_total_price: string | null
  purchased_at: string | null
  created_at: string
  submitted_at: string | null
  reviewed_at: string | null
  received_at: string | null
  completed_at: string | null
}

export interface SupplierSummary {
  supplier_id: number
  supplier_name: string
  unified_social_credit_code: string | null
  blacklist_status: string
  status: boolean
  blacklist_reason?: string | null
  [key: string]: any
}

export interface SupplierDetail {
  supplier_id: number
  supplier_name: string
  unified_social_credit_code: string | null
  bank_name: string | null
  bank_account: string | null
  registered_address: string | null
  contract_contact_info: string | null
  blacklist: { status: string; history_count: number }
}

export interface SupplierRisk {
  blacklist_id: number
  supplier_id: number
  supplier_name: string
  blacklist_type: string
  risk_reason: string
  status: string
  start_at: string
  end_at: string | null
  released_at: string | null
  release_reason: string | null
  is_effective: boolean
  source_requirement_id: number
  source_requirement_no: string
}

export interface Citation {
  citation_id?: string
  document_id?: string
  title?: string
  section_path?: string | string[]
  source_path?: string
  content?: string
  [key: string]: any
}

export interface KnowledgeSource { title: string; section_path: string[] }
export interface BusinessResult {
  kind: 'PURCHASE_REQUIREMENTS' | 'SUPPLIERS' | 'PURCHASE_HISTORY'
  title: string
  items: Record<string, any>[]
  total?: number | null
}

export interface AgentConversationSummary {
  conversation_id: number
  external_conversation_id: string | null
  status: string
  title: string
  message_count: number
  started_at: string
  last_active_at: string
}

export interface AgentStoredMessage {
  message_id: number
  external_message_id: string | null
  sender_type: 'USER' | 'AGENT' | 'SYSTEM'
  content: string
  message_data?: Partial<AgentChatData> | null
  created_at: string
}

export interface AgentConversationState {
  conversation_id: number
  purchase_request_id: number | null
  collected_data: Record<string, any>
  missing_fields: string[]
  pending_field: string | null
  awaiting_confirmation: boolean
}

export interface PendingAction {
  action_id: string
  confirmation_token: string
  action_type?: string
  title?: string
  summary?: string
  payload_preview?: Record<string, any>
  expires_at?: string
  [key: string]: any
}

export interface AgentChatData {
  task_id: string
  conversation_id: number
  status: string
  reply: string
  route: string
  tool_call_count: number
  evidence_count: number
  knowledge?: { citations?: Citation[]; evidence?: Citation[]; [key: string]: any } | null
  knowledge_sources?: KnowledgeSource[]
  business_results?: BusinessResult[]
  form_draft?: Record<string, any> | null
  form_missing_fields?: string[]
  analysis?: Record<string, any> | null
  risk_investigation?: Record<string, any> | null
  review?: Record<string, any> | null
  pending_action?: PendingAction | null
  execution?: { tools?: Record<string, any>[]; errors?: Record<string, any>[]; [key: string]: any }
}

export interface AgentUIContext {
  page_type: string
  requirement_id: number
  user_draft?: Record<string, unknown>
}

export interface AgentFormSuggestion {
  supplier_id?: number
  supplier_name?: string
  unit_price?: number
  source: string
}

export interface AgentMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  status?: 'loading' | 'success' | 'error'
  data?: AgentChatData
  error?: string
  originalPrompt?: string
  streamStatus?: string
}

export interface AdminEmployee {
  employee_id: number
  employee_no: string | null
  name: string
  mobile: string | null
  status: boolean
  roles: { role_id: number; role_code: RoleCode; role_name: string }[]
  buildings: { building_id: number; building_name: string; is_primary: boolean }[]
  identities: { identity_id: number; platform_type: string; platform_user_id: string; status: boolean }[]
  created_at: string
  updated_at: string
}

export interface AdminReferences {
  roles: { role_id: number; role_code: RoleCode; role_name: string }[]
  buildings: { building_id: number; building_name: string }[]
}

export interface AdminOverview {
  employee_count: number
  supplier_count: number
  requirement_count: number
  recent_employees: AdminEmployee[]
  recent_requirements: (RequirementListItem & { updated_at: string })[]
}
