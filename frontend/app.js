const roles = [
  {
    id: "test-user-01",
    name: "测试需求人",
    short: "需",
    code: "APPLICANT · 一号楼",
    kind: "applicant",
    defaultView: "CREATED_BY_ME",
  },
  {
    id: "test-user-02",
    name: "一号楼楼长",
    short: "楼",
    code: "BUILDING_MANAGER · 一号楼",
    kind: "manager",
    defaultView: "PENDING_FOR_ME",
  },
  {
    id: "test-user-03",
    name: "测试采购员",
    short: "采",
    code: "PURCHASER",
    kind: "purchaser",
    defaultView: "PENDING_FOR_ME",
  },
  {
    id: "test-user-04",
    name: "仓库管理员",
    short: "仓",
    code: "WAREHOUSE_MANAGER",
    kind: "warehouse",
    defaultView: "PENDING_FOR_ME",
  },
  {
    id: "test-user-05",
    name: "系统管理员",
    short: "管",
    code: "ADMIN",
    kind: "admin",
    defaultView: "PROCESSED_BY_ME",
  },
  {
    id: "test-user-07",
    name: "二号楼楼长",
    short: "二",
    code: "BUILDING_MANAGER · 二号楼",
    kind: "manager",
    defaultView: "PENDING_FOR_ME",
  },
];

const roleGuides = {
  applicant: {
    title: "需求人工作台",
    text: "新建采购申请，草稿可以暂缺字段；提交楼长审核前必须填写所有必填项。",
  },
  manager: {
    title: "楼长审批工作台",
    text: "查看管辖楼宇申请，可修订需求资料、补充审核方案，并选择驳回或通过。",
  },
  purchaser: {
    title: "采购员工作台",
    text: "查看分配给自己的采购任务，开始采购、填写供应商与成交信息并提交仓库。",
  },
  warehouse: {
    title: "仓库入库工作台",
    text: "查看待入库任务，登记库位和实收数量；少于申请数量时必须填写说明。",
  },
  admin: {
    title: "系统管理员",
    text: "管理员主要用于供应商和通知运维体验，不直接办理采购流程。",
  },
};

const roleViews = {
  applicant: [
    ["CREATED_BY_ME", "我的申请（含草稿和当前状态）"],
    ["PROCESSED_BY_ME", "我的历史申请"],
  ],
  manager: [
    ["PENDING_FOR_ME", "待我审批"],
    ["BUILDING_SCOPE", "管辖楼宇全部申请"],
    ["PROCESSED_BY_ME", "我的历史审批"],
  ],
  purchaser: [
    ["PENDING_FOR_ME", "待我采购"],
    ["PROCESSED_BY_ME", "我的历史采购"],
  ],
  warehouse: [
    ["PENDING_FOR_ME", "待我入库"],
    ["PROCESSED_BY_ME", "我的历史入库"],
  ],
  admin: [["PROCESSED_BY_ME", "参与记录"]],
};

const scenarioRows = [
  [91001, "草稿"],
  [91002, "待楼长审核"],
  [91003, "已驳回"],
  [91004, "待采购"],
  [91005, "采购中"],
  [91006, "待入库"],
  [91007, "已完成"],
];

const deviceTypes = [
  "电气",
  "暖通",
  "弱电",
  "机房环境",
  "工器具",
  "算力服务器",
  "IDC网络",
  "其他",
];

const pageNames = {
  procurement: "采购流程",
  suppliers: "供应商与推荐",
  records: "历史与时间线",
  agent: "Agent 存储",
  notifications: "通知 Outbox",
};

const state = {
  role: roles[0],
  tab: "procurement",
  currentUser: null,
  requirementId: null,
  requirement: null,
  requirementDirty: false,
  agentConversationId: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHtml = (value) =>
  String(value ?? "—")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

function token(prefix = "DEMO") {
  return `${prefix}-${crypto.randomUUID()}`;
}

function money(value) {
  if (value === null || value === undefined) return "—";
  return `¥ ${Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`;
}

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

async function api(path, options = {}) {
  const method = options.method || "GET";
  const response = await fetch("/demo-api/proxy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      platform_user_id: state.role.id,
      method,
      path,
      query: options.query || {},
      body: options.body ?? null,
    }),
  });
  const payload = await response.json();
  if (!response.ok || payload.success === false) {
    const error = new Error(payload.message || `请求失败 (${response.status})`);
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload.data;
}

function toast(message, type = "success") {
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast show ${type === "error" ? "error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    element.className = "toast";
  }, 3200);
}

const backendFieldLabels = {
  device_profession: "设备类型",
  device_name: "设备名称",
  quantity: "数量",
  unit: "单位",
  application_reason: "申请原因",
  proposed_supplier: "建议供应商",
  estimated_unit_price: "预计单价",
  payment_method: "付款方式",
  expected_arrival_date: "预计到货日期",
  warranty_info: "质保信息",
  contract_type: "合同类型",
  purchase_execution: "采购信息",
  warehouse_receipt: "入库信息",
};

function friendlyErrorMessage(error) {
  const code = error.payload?.code;
  const message = error.payload?.message || error.message || "";
  if (code === "MISSING_REQUIRED_FIELDS") {
    const fieldPart = message.includes("：") ? message.split("：").at(-1) : "";
    const fields = fieldPart
      .split(",")
      .map((item) => backendFieldLabels[item.trim()])
      .filter(Boolean);
    return fields.length
      ? `请先补齐${fields.join("、")}，保存后再提交`
      : "请先补齐必填信息并保存，再继续提交";
  }
  if (code === "CONCURRENT_MODIFICATION") return "申请已被其他操作更新，请刷新后再继续";
  if (code === "INVALID_STATUS") return "当前申请状态已经变化，请刷新后查看可执行操作";
  if (code === "INVALID_HANDLER") return "请选择有效的下一处理人";
  if (code === "PERMISSION_DENIED") return "当前身份没有执行此操作的权限";
  if (code === "VALIDATION_ERROR") {
    if (message.includes("入库数量少于")) return "入库数量少于申请数量，请填写入库说明";
    if (message.includes("总价")) return "单价与总价不一致，请检查价格信息";
    return "请检查必填项和填写格式";
  }
  if (error.status === 422) return "请检查必填项和填写格式";
  return message || "操作失败，请稍后重试";
}

function showError(error) {
  if (!error.status || error.status >= 500) console.error(error);
  toast(friendlyErrorMessage(error), "error");
}

function showModal(title, value) {
  $("#modal-title").textContent = title;
  $("#modal-content").textContent =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  $("#modal").hidden = false;
}

function renderRoles() {
  $("#role-menu").innerHTML = roles
    .map(
      (role) => `
        <button class="role-option ${role.id === state.role.id ? "active" : ""}" data-role="${role.id}" type="button">
          <strong>${escapeHtml(role.name)}</strong>
          <small>${escapeHtml(role.code)}</small>
        </button>`,
    )
    .join("");
  $("#role-name").textContent = state.role.name;
  $("#role-code").textContent = state.role.code;
  $("#role-avatar").textContent = state.role.short;
}

async function switchRole(roleId) {
  state.role = roles.find((role) => role.id === roleId) || roles[0];
  state.currentUser = null;
  state.requirement = null;
  state.requirementId = null;
  state.requirementDirty = false;
  state.agentConversationId = null;
  renderRoleWorkspace();
  renderEmptyRequirement();
  $("#role-menu").hidden = true;
  renderRoles();
  await loadIdentity();
  await loadCurrentTab();
  toast(`已切换为：${state.role.name}`);
}

function renderRoleWorkspace() {
  const guide = roleGuides[state.role.kind] || roleGuides.applicant;
  $("#role-guide").innerHTML = `<strong>${guide.title}</strong><span>${guide.text}</span>`;
  $("#workbench-title").textContent = guide.title;
  const views = roleViews[state.role.kind] || roleViews.applicant;
  $("#requirement-view").innerHTML = views
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
  $("#requirement-view").value = state.role.defaultView;
  $("#create-requirement").hidden = state.role.kind !== "applicant";
}

function renderEmptyRequirement() {
  $("#requirement-detail").innerHTML = `
    <div class="empty-detail">
      <div class="empty-symbol">⌁</div>
      <h3>选择一张采购申请</h3>
      <p>查看当前状态、字段内容、允许操作和流程版本。</p>
    </div>`;
}

async function loadIdentity() {
  try {
    const user = await api("/api/v1/users/me");
    state.currentUser = user;
    $("#metric-user").textContent = user.name;
    $("#metric-building").textContent =
      user.buildings.map((building) => building.building_name).join("、") || "无楼宇范围";
    const status = $("#service-status");
    status.className = "service-status ok";
    status.innerHTML = '<span class="status-dot"></span><span>MySQL / Redis 正常</span>';
  } catch (error) {
    const status = $("#service-status");
    status.className = "service-status bad";
    status.innerHTML = '<span class="status-dot"></span><span>服务连接异常</span>';
    showError(error);
  }
}

function setTab(tab) {
  state.tab = tab;
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.tab === tab));
  $$(".tab-page").forEach((item) => item.classList.toggle("active", item.id === `tab-${tab}`));
  $("#page-title").textContent = pageNames[tab];
  loadCurrentTab();
}

async function loadCurrentTab() {
  try {
    if (state.tab === "procurement") await loadRequirements();
    if (state.tab === "suppliers") await searchSuppliers();
    if (state.tab === "records") await loadRecords();
    if (state.tab === "agent" && state.agentConversationId) await loadAgentMessages();
    if (state.tab === "notifications") await loadNotifications();
  } catch (error) {
    showError(error);
  }
}

async function loadRequirements() {
  const view = $("#requirement-view").value;
  const status = $("#requirement-status").value;
  const data = await api("/api/v1/requirements", {
    query: { view, status, page: 1, page_size: 50 },
  });
  $("#metric-total").textContent = data.total;
  $("#metric-pending").textContent = view === "PENDING_FOR_ME" ? data.total : "—";
  const container = $("#requirement-list");
  if (!data.items.length) {
    container.innerHTML = '<div class="empty-state">当前范围没有采购申请。尝试切换“查看范围”或角色。</div>';
    return;
  }
  container.innerHTML = data.items
    .map(
      (item) => `
      <div class="data-row ${item.requirement_id === state.requirementId ? "active" : ""}">
        <button type="button" data-requirement="${item.requirement_id}">
          <div class="row-title">
            <strong>${escapeHtml(item.requirement_no)}</strong>
            <span class="status-badge" data-status="${item.status}">${item.status}</span>
          </div>
          <div class="row-meta">${escapeHtml(item.device_name)} · 当前处理人：${escapeHtml(item.current_handler_name)}</div>
        </button>
        <span class="row-meta">#${item.requirement_id}</span>
      </div>`,
    )
    .join("");
}

function renderScenarios() {
  $("#scenario-strip").innerHTML = scenarioRows
    .map(
      ([id, label]) =>
        `<button type="button" class="scenario-chip" data-requirement="${id}">${id} · ${label}</button>`,
    )
    .join("");
}

async function openRequirement(id) {
  const detail = await api(`/api/v1/requirements/${id}`);
  state.requirementId = id;
  state.requirement = detail;
  state.requirementDirty = false;
  renderRequirementDetail(detail);
  await Promise.all([hydrateRequirementForm(detail), loadRequirementFlow(id)]);
  await loadRequirements();
}

function definition(label, value) {
  return `<div class="definition-item"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function formValue(value) {
  return value === null || value === undefined ? "" : String(value);
}

function field(label, name, value, options = {}) {
  const required = options.required ? '<em class="required">*</em>' : "";
  const type = options.type || "text";
  const step = options.step ? ` step="${options.step}"` : "";
  const placeholder = options.placeholder ? ` placeholder="${options.placeholder}"` : "";
  const span = options.wide ? " form-field-wide" : "";
  return `
    <label class="form-field${span}">
      <span>${label}${required}</span>
      <input name="${name}" type="${type}" value="${escapeHtml(formValue(value))}"${step}${placeholder} />
    </label>`;
}

function selectField(label, name, value, options) {
  const required = options.required ? '<em class="required">*</em>' : "";
  const selectedValue = options.items.includes(value) ? value : value ? "其他" : "";
  return `
    <label class="form-field">
      <span>${label}${required}</span>
      <select name="${name}">
        <option value="">请选择</option>
        ${options.items
          .map(
            (item) =>
              `<option value="${escapeHtml(item)}" ${
                item === selectedValue ? "selected" : ""
              }>${escapeHtml(item)}</option>`,
          )
          .join("")}
      </select>
    </label>`;
}

function textAreaField(label, name, value, options = {}) {
  const required = options.required ? '<em class="required">*</em>' : "";
  return `
    <label class="form-field form-field-wide">
      <span>${label}${required}</span>
      <textarea name="${name}" rows="${options.rows || 3}">${escapeHtml(formValue(value))}</textarea>
    </label>`;
}

function applicantForm(detail) {
  const applicant = detail.applicant_fields || {};
  return `
    <section class="business-form" data-form="applicant">
      <div class="form-heading">
        <div>
          <h3>${state.role.kind === "manager" ? "员工需求资料（楼长可修订）" : "采购需求资料"}</h3>
          <p>标有 * 的字段提交审核前必须填写；保存草稿时允许暂缺。</p>
        </div>
        <span class="completion ${detail.missing_fields?.length ? "incomplete" : "complete"}">
          ${detail.missing_fields?.length ? `待补 ${detail.missing_fields.length} 项` : "资料完整"}
        </span>
      </div>
      <div class="form-grid">
        ${selectField("设备类型", "applicant_device_profession", applicant.device_profession, {
          required: true,
          items: deviceTypes,
        })}
        ${field("设备名称", "applicant_device_name", applicant.device_name, { required: true })}
        ${field("品牌", "applicant_brand", applicant.brand)}
        ${field("型号", "applicant_model", applicant.model)}
        ${field("数量", "applicant_quantity", applicant.quantity, {
          required: true,
          type: "number",
          step: "0.001",
        })}
        ${field("单位", "applicant_unit", applicant.unit, { required: true })}
        ${textAreaField("申请原因", "applicant_application_reason", applicant.application_reason, {
          required: true,
        })}
        ${textAreaField("需求备注", "applicant_remark", applicant.applicant_remark)}
      </div>
      <div class="form-actions">
        <button class="button secondary" type="button" data-action="SAVE_APPLICANT_FIELDS">
          保存${state.role.kind === "applicant" ? "草稿" : "需求修改"}
        </button>
      </div>
    </section>`;
}

function reviewForm(detail) {
  const review = detail.review_records?.at(-1) || {};
  return `
    <section class="business-form" data-form="review">
      <div class="form-heading">
        <div>
          <h3>楼长审核与采购建议</h3>
          <p>先保存审核资料，再选择通过并提交采购员。</p>
        </div>
      </div>
      <div class="form-grid">
        ${field("建议供应商 ID", "review_supplier_id", review.proposed_supplier_id || 92001, {
          required: true,
          type: "number",
        })}
        ${field("供应商联系人", "review_contact_name", review.supplier_contact_name)}
        ${field("联系方式", "review_contact_info", review.supplier_contact_info)}
        ${field("供应商链接", "review_supplier_link", review.supplier_link)}
        ${field("预计单价（元）", "review_unit_price", review.estimated_unit_price, {
          required: true,
          type: "number",
          step: "0.01",
        })}
        ${field("预计到货日期", "review_arrival_date", review.expected_arrival_date, {
          required: true,
          type: "date",
        })}
        ${field("付款方式", "review_payment_method", review.payment_method, { required: true })}
        ${field("质保信息", "review_warranty", review.warranty_info, { required: true })}
        <label class="form-field checkbox-field">
          <input name="review_need_contract" type="checkbox" ${review.need_contract ? "checked" : ""} />
          <span>需要签订合同</span>
        </label>
        ${field("合同类型", "review_contract_type", review.contract_type)}
        ${textAreaField("审核备注", "review_remark", review.review_remark)}
      </div>
      <div class="form-actions">
        <button class="button secondary" type="button" data-action="SAVE_REVIEW_FIELDS">保存审核资料</button>
      </div>
    </section>`;
}

function purchaseForm(detail) {
  const execution = detail.purchase_execution || {};
  const purchasedAt = execution.purchased_at
    ? String(execution.purchased_at).slice(0, 16)
    : new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  return `
    <section class="business-form" data-form="purchase">
      <div class="form-heading">
        <div>
          <h3>采购执行信息</h3>
          <p>本次资料始终保存快照；勾选同步时才更新供应商主档。</p>
        </div>
      </div>
      <div class="form-grid">
        <label class="form-field">
          <span>成交供应商<em class="required">*</em></span>
          <select name="purchase_supplier_id" data-supplier-select>
            <option value="${escapeHtml(execution.supplier_id || 92001)}">正在加载供应商…</option>
          </select>
        </label>
        ${field("实际单价（元）", "purchase_unit_price", execution.actual_unit_price, {
          required: true,
          type: "number",
          step: "0.01",
        })}
        ${field("采购时间", "purchase_at", purchasedAt, {
          required: true,
          type: "datetime-local",
        })}
        ${field("税率（%）", "purchase_tax_rate", execution.tax_rate ?? 13, {
          type: "number",
          step: "0.01",
        })}
        ${field("统一社会信用代码", "purchase_tax_number", execution.supplier_tax_number)}
        ${field("开户银行", "purchase_bank_name", execution.bank_name)}
        ${field("银行账号", "purchase_bank_account", execution.bank_account)}
        ${field("注册地址", "purchase_address", execution.registered_address)}
        ${field("合同联系人", "purchase_contact", execution.contract_contact_info, { wide: true })}
        ${textAreaField("采购备注", "purchase_remark", execution.purchase_remark)}
        <label class="form-field form-field-wide checkbox-field">
          <input name="purchase_update_profile" type="checkbox" />
          <span>确认同步更新供应商主档</span>
        </label>
      </div>
      <div class="form-actions">
        <button class="button secondary" type="button" data-action="SAVE_PURCHASE_FIELDS">保存采购信息</button>
      </div>
    </section>`;
}

function warehouseForm(detail) {
  const receipt = detail.warehouse_receipt || {};
  return `
    <section class="business-form" data-form="warehouse">
      <div class="form-heading">
        <div>
          <h3>入库登记</h3>
          <p>实收数量可少于、等于或多于申请数量；少于时入库说明必填。</p>
        </div>
      </div>
      <div class="form-grid">
        ${field("仓库位置", "warehouse_location", receipt.warehouse_location, { required: true })}
        ${field("实收入库数量", "warehouse_quantity", receipt.received_quantity, {
          required: true,
          type: "number",
          step: "0.001",
        })}
        ${textAreaField("入库说明", "warehouse_remark", receipt.receipt_remark)}
      </div>
      <div class="form-actions">
        <button class="button secondary" type="button" data-action="SAVE_WAREHOUSE_FIELDS">保存入库信息</button>
      </div>
    </section>`;
}

function transitionActions(detail) {
  const actions = detail.allowed_actions || [];
  const buttons = [];
  if (actions.includes("SUBMIT_REVIEW") || actions.includes("RESUBMIT_REVIEW")) {
    const action = actions.includes("SUBMIT_REVIEW") ? "SUBMIT_REVIEW" : "RESUBMIT_REVIEW";
    buttons.push(`
      <label class="transition-field">
        <span>提交给楼长</span>
        <select data-handler-role="BUILDING_MANAGER" name="handler_BUILDING_MANAGER">
          <option value="">正在加载…</option>
        </select>
      </label>
      <button class="button primary" type="button" data-action="${action}">${actionLabel(action)}</button>`);
  }
  if (actions.includes("REJECT")) {
    buttons.push(`
      <label class="transition-field transition-field-wide">
        <span>驳回原因</span>
        <input name="reject_reason" value="" placeholder="请说明需要员工补充或修改的内容" />
      </label>
      <button class="button danger" type="button" data-action="REJECT">驳回申请</button>`);
  }
  if (actions.includes("SUBMIT_PURCHASER")) {
    buttons.push(`
      <label class="transition-field">
        <span>提交给采购员</span>
        <select data-handler-role="PURCHASER" name="handler_PURCHASER">
          <option value="">正在加载…</option>
        </select>
      </label>
      <button class="button primary" type="button" data-action="SUBMIT_PURCHASER">通过并提交采购员</button>`);
  }
  if (actions.includes("START_PURCHASE")) {
    buttons.push(
      '<button class="button primary" type="button" data-action="START_PURCHASE">开始办理采购</button>',
    );
  }
  if (actions.includes("SUBMIT_WAREHOUSE")) {
    buttons.push(`
      <label class="transition-field">
        <span>提交给仓管</span>
        <select data-handler-role="WAREHOUSE_MANAGER" name="handler_WAREHOUSE_MANAGER">
          <option value="">正在加载…</option>
        </select>
      </label>
      <button class="button primary" type="button" data-action="SUBMIT_WAREHOUSE">提交入库</button>`);
  }
  if (actions.includes("COMPLETE")) {
    buttons.push(
      '<button class="button primary" type="button" data-action="COMPLETE">确认入库并完成采购</button>',
    );
  }
  if (!buttons.length) {
    return '<span class="helper">当前没有需要该身份处理的操作，可查看申请资料和流程状态。</span>';
  }
  return buttons.join("");
}

function renderRequirementDetail(detail) {
  const applicant = detail.applicant_fields || {};
  const execution = detail.purchase_execution || {};
  const receipt = detail.warehouse_receipt || {};
  const actions = detail.allowed_actions || [];
  $("#requirement-detail").innerHTML = `
    <div class="detail-head">
      <div class="eyebrow">REQUIREMENT #${detail.requirement_id}</div>
      <h2>${escapeHtml(detail.requirement_no)}</h2>
      <div class="detail-sub">
        <span class="status-badge" data-status="${detail.status}">${detail.status}</span>
        <span>版本 ${detail.version}</span>
        <span>${escapeHtml(detail.building?.building_name)}</span>
      </div>
    </div>
    <div class="detail-section">
      <h3>需求资料</h3>
      <div class="definition-grid">
        ${definition("设备类型", applicant.device_profession)}
        ${definition("设备名称", applicant.device_name)}
        ${definition("品牌 / 型号", `${applicant.brand || "—"} / ${applicant.model || "—"}`)}
        ${definition("数量", `${applicant.quantity || "—"} ${applicant.unit || ""}`)}
        ${definition("当前处理人", detail.current_handler?.name)}
        ${
          state.role.kind !== "applicant"
            ? definition(
                "缺失字段",
                detail.missing_fields?.length
                  ? detail.missing_fields
                      .map((field) => backendFieldLabels[field] || "待补充信息")
                      .join("、")
                  : "无",
              )
            : ""
        }
      </div>
    </div>
    ${actions.includes("SAVE_APPLICANT_FIELDS") ? applicantForm(detail) : ""}
    ${actions.includes("SAVE_REVIEW_FIELDS") ? reviewForm(detail) : ""}
    ${actions.includes("SAVE_PURCHASE_FIELDS") ? purchaseForm(detail) : ""}
    ${actions.includes("SAVE_WAREHOUSE_FIELDS") ? warehouseForm(detail) : ""}
    ${
      state.role.kind !== "applicant" && execution.supplier_id
        ? `<div class="detail-section">
            <h3>采购执行快照</h3>
            <div class="definition-grid">
              ${definition("供应商", execution.supplier_name)}
              ${definition("银行账号", execution.bank_account)}
              ${definition("实际总价", money(execution.actual_total_price))}
              ${definition("采购时间", formatDate(execution.purchased_at))}
            </div>
          </div>`
        : ""
    }
    ${
      receipt.received_quantity
        ? `<div class="detail-section">
            <h3>入库记录</h3>
            <div class="definition-grid">
              ${definition("仓库位置", receipt.warehouse_location)}
              ${definition("入库数量", receipt.received_quantity)}
              ${definition("入库时间", formatDate(receipt.received_at))}
              ${definition("备注", receipt.receipt_remark)}
            </div>
          </div>`
        : ""
    }
    <div class="detail-section">
      <h3>流转操作</h3>
      <div class="transition-actions">
        ${transitionActions(detail)}
      </div>
    </div>
    <div class="detail-section">
      <h3>流程履历</h3>
      <div class="timeline compact-timeline" id="requirement-flow">
        <div class="empty-state">正在加载流程履历…</div>
      </div>
    </div>`;
}

const actionLabels = {
  SAVE_APPLICANT_FIELDS: "填写需求资料",
  SUBMIT_REVIEW: "提交楼长审核",
  REJECT: "驳回申请",
  RESUBMIT_REVIEW: "重新提交",
  SAVE_REVIEW_FIELDS: "填写审核方案",
  SUBMIT_PURCHASER: "提交采购员",
  START_PURCHASE: "开始采购",
  SAVE_PURCHASE_FIELDS: "填写采购结果",
  SUBMIT_WAREHOUSE: "提交仓库",
  SAVE_WAREHOUSE_FIELDS: "填写入库信息",
  COMPLETE: "完成采购",
};

function actionLabel(action) {
  return actionLabels[action] || action;
}

async function runRequirementAction(action) {
  const detail = state.requirement;
  if (!detail) return;
  const saveActions = new Set([
    "SAVE_APPLICANT_FIELDS",
    "SAVE_REVIEW_FIELDS",
    "SAVE_PURCHASE_FIELDS",
    "SAVE_WAREHOUSE_FIELDS",
  ]);
  if (!saveActions.has(action) && state.requirementDirty) {
    const messages = {
      applicant: "请先保存草稿再提交",
      manager: "请先保存需求修改和审核资料再提交",
      purchaser: "请先保存采购信息再提交仓库",
      warehouse: "请先保存入库信息再完成采购",
    };
    toast(messages[state.role.kind] || "请先保存当前修改再继续", "error");
    return;
  }
  const requiresCompleteData = new Set([
    "SUBMIT_REVIEW",
    "RESUBMIT_REVIEW",
    "SUBMIT_PURCHASER",
    "SUBMIT_WAREHOUSE",
    "COMPLETE",
  ]);
  if (requiresCompleteData.has(action) && detail.missing_fields?.length) {
    const labels = detail.missing_fields
      .map((fieldName) => backendFieldLabels[fieldName])
      .filter(Boolean);
    const missing = labels.length ? labels.join("、") : "必填信息";
    toast(`请先补齐${missing}并保存，再继续提交`, "error");
    return;
  }
  const id = detail.requirement_id;
  const version = detail.version;
  let method = "POST";
  let path = "";
  let body = {};
  const read = (name) => $(`[name="${name}"]`)?.value.trim() || null;
  const checked = (name) => Boolean($(`[name="${name}"]`)?.checked);

  if (action === "SAVE_APPLICANT_FIELDS") {
    method = "PATCH";
    path = `/api/v1/requirements/${id}/applicant-fields`;
    body = {
      expected_version: version,
      fields: {
        device_profession: read("applicant_device_profession"),
        device_name: read("applicant_device_name"),
        brand: read("applicant_brand"),
        model: read("applicant_model"),
        quantity: read("applicant_quantity"),
        unit: read("applicant_unit"),
        application_reason: read("applicant_application_reason"),
        applicant_remark: read("applicant_remark"),
      },
    };
  } else if (action === "SUBMIT_REVIEW" || action === "RESUBMIT_REVIEW") {
    path = `/api/v1/requirements/${id}/${action === "SUBMIT_REVIEW" ? "submit-review" : "resubmit-review"}`;
    body = {
      expected_version: version,
      assigned_to_employee_id: Number(read("handler_BUILDING_MANAGER")),
      action_token: token(action),
    };
  } else if (action === "REJECT") {
    const reason = read("reject_reason");
    if (!reason) throw new Error("请先填写驳回原因");
    path = `/api/v1/requirements/${id}/reject`;
    body = { expected_version: version, reason, action_token: token(action) };
  } else if (action === "SAVE_REVIEW_FIELDS") {
    method = "PATCH";
    path = `/api/v1/requirements/${id}/review-fields`;
    body = {
      expected_version: version,
      fields: {
        proposed_supplier_id: Number(read("review_supplier_id")) || null,
        supplier_contact_name: read("review_contact_name"),
        supplier_contact_info: read("review_contact_info"),
        supplier_link: read("review_supplier_link"),
        estimated_unit_price: read("review_unit_price"),
        need_contract: checked("review_need_contract"),
        contract_type: read("review_contract_type"),
        payment_method: read("review_payment_method"),
        expected_arrival_date: read("review_arrival_date"),
        warranty_info: read("review_warranty"),
        review_remark: read("review_remark"),
      },
    };
  } else if (action === "SUBMIT_PURCHASER") {
    path = `/api/v1/requirements/${id}/submit-purchaser`;
    body = {
      expected_version: version,
      assigned_to_employee_id: Number(read("handler_PURCHASER")),
      action_token: token(action),
    };
  } else if (action === "START_PURCHASE") {
    path = `/api/v1/requirements/${id}/start-purchase`;
    body = { expected_version: version, action_token: token(action) };
  } else if (action === "SAVE_PURCHASE_FIELDS") {
    method = "PATCH";
    path = `/api/v1/requirements/${id}/purchase-fields`;
    body = {
      expected_version: version,
      fields: {
        supplier_id: Number(read("purchase_supplier_id")),
        supplier_tax_number: read("purchase_tax_number"),
        bank_name: read("purchase_bank_name"),
        bank_account: read("purchase_bank_account"),
        registered_address: read("purchase_address"),
        contract_contact_info: read("purchase_contact"),
        actual_unit_price: read("purchase_unit_price"),
        tax_rate: read("purchase_tax_rate"),
        purchased_at: new Date(read("purchase_at")).toISOString(),
        purchase_remark: read("purchase_remark"),
        update_supplier_profile: checked("purchase_update_profile"),
      },
    };
  } else if (action === "SUBMIT_WAREHOUSE") {
    path = `/api/v1/requirements/${id}/submit-warehouse`;
    body = {
      expected_version: version,
      assigned_to_employee_id: Number(read("handler_WAREHOUSE_MANAGER")),
      action_token: token(action),
    };
  } else if (action === "SAVE_WAREHOUSE_FIELDS") {
    method = "PATCH";
    path = `/api/v1/requirements/${id}/warehouse-fields`;
    body = {
      expected_version: version,
      fields: {
        warehouse_location: read("warehouse_location"),
        received_quantity: read("warehouse_quantity"),
        receipt_remark: read("warehouse_remark"),
      },
    };
  } else if (action === "COMPLETE") {
    path = `/api/v1/requirements/${id}/complete`;
    body = { expected_version: version, action_token: token(action) };
  }

  if (!path) return;
  await api(path, { method, body });
  toast(`${actionLabel(action)}成功`);
  await openRequirement(id);
}

async function hydrateRequirementForm(detail) {
  const handlerSelects = $$("[data-handler-role]");
  for (const select of handlerSelects) {
    const targetRole = select.dataset.handlerRole;
    const data = await api(`/api/v1/requirements/${detail.requirement_id}/handler-candidates`, {
      query: { target_role: targetRole },
    });
    select.innerHTML = data.items
      .map(
        (item) =>
          `<option value="${item.employee_id}" ${
            item.employee_id === data.auto_selected_employee_id ? "selected" : ""
          }>${escapeHtml(item.name)} · ${escapeHtml(item.mobile)}</option>`,
      )
      .join("");
  }

  const supplierSelect = $("[data-supplier-select]");
  if (supplierSelect) {
    const suppliers = await api("/api/v1/suppliers", {
      query: { keyword: "TEST", page: 1, page_size: 50 },
    });
    const selectedSupplier = Number(detail.purchase_execution?.supplier_id || 92001);
    supplierSelect.innerHTML = suppliers.items
      .filter((item) => item.blacklist_status !== "BLACKLISTED")
      .map(
        (item) =>
          `<option value="${item.supplier_id}" ${
            item.supplier_id === selectedSupplier ? "selected" : ""
          }>${escapeHtml(item.supplier_name)}</option>`,
      )
      .join("");
  }
}

async function createRequirement() {
  const data = await api("/api/v1/requirements", {
    method: "POST",
    body: { building_id: 1 },
  });
  toast(`已创建草稿 ${data.requirement_no}`);
  await openRequirement(data.requirement_id);
}

async function searchSuppliers() {
  const keyword = $("#supplier-keyword").value.trim() || "TEST";
  const data = await api("/api/v1/suppliers", { query: { keyword, page: 1, page_size: 50 } });
  const container = $("#supplier-list");
  container.innerHTML = data.items.length
    ? data.items
        .map(
          (item) => `
          <div class="data-row">
            <button type="button" data-supplier="${item.supplier_id}">
              <div class="row-title">
                <strong>${escapeHtml(item.supplier_name)}</strong>
                <span class="status-badge" data-status="${item.blacklist_status}">${item.blacklist_status}</span>
              </div>
              <div class="row-meta">${escapeHtml(item.unified_social_credit_code)}</div>
            </button>
            <span class="row-meta">#${item.supplier_id}</span>
          </div>`,
        )
        .join("")
    : '<div class="empty-state">没有匹配的供应商。</div>';
}

async function openSupplier(id) {
  const detail = await api(`/api/v1/suppliers/${id}`);
  $("#supplier-detail").innerHTML = `
    <div class="detail-head">
      <div class="eyebrow">SUPPLIER #${detail.supplier_id}</div>
      <h2>${escapeHtml(detail.supplier_name)}</h2>
      <div class="detail-sub"><span class="status-badge" data-status="${detail.blacklist.status}">${detail.blacklist.status}</span><span>历史黑名单 ${detail.blacklist.history_count} 次</span></div>
    </div>
    <div class="detail-section">
      <h3>主档资料</h3>
      <div class="definition-grid">
        ${definition("统一社会信用代码", detail.unified_social_credit_code)}
        ${definition("开户银行", detail.bank_name)}
        ${definition("银行账号", detail.bank_account)}
        ${definition("注册地址", detail.registered_address)}
        ${definition("合同联系人", detail.contract_contact_info)}
      </div>
    </div>
    <div class="detail-section"><p class="helper">切换需求人和采购员角色，对比银行账号脱敏效果。</p></div>`;
}

async function createSupplier() {
  const suffix = Date.now().toString().slice(-6);
  const data = await api("/api/v1/suppliers", {
    method: "POST",
    body: {
      supplier_name: `体验供应商-${suffix}`,
      unified_social_credit_code: `DEMO-CREDIT-${suffix}`,
      bank_name: "体验银行",
      bank_account: `62220000${suffix}`,
      registered_address: "体验市采购大道",
      contract_contact_info: "体验联系人 13900000000",
    },
  });
  toast(`供应商 ${data.supplier_name} 已创建`);
  $("#supplier-keyword").value = data.supplier_name;
  await searchSuppliers();
}

async function loadProductRecommendations() {
  const deviceName = $("#recommend-device").value.trim() || "测试";
  const data = await api("/api/v1/recommendations/products", {
    query: { device_name: deviceName, limit: 10 },
  });
  $("#product-recommendations").innerHTML = data.items.length
    ? data.items
        .map(
          (item) => `<div class="recommend-card"><strong>${escapeHtml(item.brand)} · ${escapeHtml(item.model)}</strong><span>历史采购 ${item.historical_count} 次 · ${formatDate(item.last_purchased_at)}</span></div>`,
        )
        .join("")
    : '<div class="empty-state">暂无可用历史推荐。TEST 采购记录默认不会进入普通推荐。</div>';
}

async function addBlacklist() {
  const supplierId = $("#blacklist-supplier-id").value.trim();
  const requestId = Number($("#blacklist-request-id").value);
  const data = await api(`/api/v1/suppliers/${supplierId}/blacklist`, {
    method: "POST",
    body: {
      requirement_id: requestId,
      blacklist_type: "履约问题",
      reason: $("#blacklist-reason").value,
      duration_type: "PERMANENT",
      start_at: new Date().toISOString(),
      action_token: token("BLACKLIST"),
    },
  });
  toast(`已登记黑名单 #${data.blacklist_id}`);
  showModal("黑名单登记结果", data);
}

async function releaseBlacklist() {
  const supplierId = $("#blacklist-supplier-id").value.trim();
  const blacklistId = prompt("请输入要解除的 blacklist_id");
  if (!blacklistId) return;
  const data = await api(`/api/v1/suppliers/${supplierId}/blacklists/${blacklistId}/release`, {
    method: "POST",
    body: { reason: "体验界面测试解除", action_token: token("RELEASE") },
  });
  toast(`黑名单 #${blacklistId} 已解除`);
  showModal("黑名单解除结果", data);
}

async function loadRecords() {
  const query = {
    requirement_no: $("#record-number").value.trim(),
    device_name: $("#record-device").value.trim(),
    status: $("#record-status").value,
    page: 1,
    page_size: 50,
  };
  const data = await api("/api/v1/purchase-records", { query });
  $("#record-table").innerHTML = data.items.length
    ? data.items
        .map(
          (item) => `<tr>
            <td><strong>${escapeHtml(item.requirement_no)}</strong><br><small>#${item.requirement_id}</small></td>
            <td>${escapeHtml(item.device_name)}<br><small>${escapeHtml(item.brand)} ${escapeHtml(item.model)}</small></td>
            <td>${escapeHtml(item.supplier_name)}</td>
            <td>${money(item.actual_total_price)}</td>
            <td><span class="status-badge" data-status="${item.status}">${item.status}</span></td>
            <td class="record-times">${renderRecordTimes(item)}</td>
            <td><button class="button secondary" type="button" data-timeline="${item.requirement_id}">查看时间线</button></td>
          </tr>`,
        )
        .join("")
    : '<tr><td colspan="7"><div class="empty-state">当前角色范围内没有匹配记录。</div></td></tr>';
}

function renderRecordTimes(item) {
  const times = [
    ["提交", item.submitted_at],
    ["审批", item.reviewed_at],
    ["采购", item.purchased_at],
    ["入库", item.received_at],
    ["完成", item.completed_at],
  ].filter(([, value]) => value);
  return times.length
    ? times
        .map(
          ([label, value]) =>
            `<span><b>${label}</b>${escapeHtml(formatDate(value))}</span>`,
        )
        .join("")
    : "<span>尚未提交</span>";
}

const timelineActionLabels = {
  CREATE_DRAFT: "创建草稿",
  SUBMIT_REVIEW: "提交楼长审批",
  SUBMIT: "提交楼长审批",
  RESUBMIT_REVIEW: "重新提交审批",
  RESUBMIT: "重新提交审批",
  REJECT: "楼长驳回",
  SUBMIT_PURCHASER: "楼长审批通过",
  APPROVE: "楼长审批通过",
  START_PURCHASE: "开始采购",
  SUBMIT_WAREHOUSE: "采购完成并提交仓库",
  COMPLETE_PURCHASE: "采购完成并提交仓库",
  COMPLETE: "确认入库并完成",
  WAREHOUSE_RECEIVE: "确认入库并完成",
  WAREHOUSE_RECEIVE_LESS: "少量入库并完成",
  WAREHOUSE_RECEIVE_MORE: "超量入库并完成",
};

function contactButton(requirementId, item, subject) {
  const isAssignee = subject === "assignee";
  const mobile = isAssignee ? item.assigned_to_mobile_masked : item.operator_mobile_masked;
  if (!mobile) return '<span class="contact-empty">未留联系方式</span>';
  return `
    <button class="contact-reveal" type="button"
      data-contact-requirement="${requirementId}"
      data-contact-log="${item.log_id}"
      data-contact-subject="${subject}"
      title="点击查看完整手机号">${escapeHtml(mobile)}</button>`;
}

function renderTimeline(requirementId, items) {
  return items.length
    ? items
        .map(
          (item, index) => `
            <div class="timeline-item">
              <span class="timeline-index">${index + 1}</span>
              <div class="timeline-content">
                <div class="timeline-head">
                  <strong>${escapeHtml(timelineActionLabels[item.action_type] || item.action_type)}</strong>
                  <time>${escapeHtml(formatDate(item.operated_at))}</time>
                </div>
                <p>
                  ${escapeHtml(item.operator_role_name)}：${escapeHtml(item.operator_name)}
                  ${contactButton(requirementId, item, "operator")}
                </p>
                ${
                  item.assigned_to_name
                    ? `<p class="timeline-assignee">下一处理人：${escapeHtml(item.assigned_to_name)}
                       ${contactButton(requirementId, item, "assignee")}</p>`
                    : ""
                }
                ${
                  item.operation_summary
                    ? `<small>${escapeHtml(item.operation_summary)}</small>`
                    : ""
                }
              </div>
            </div>`,
        )
        .join("")
    : '<div class="empty-state">暂无关键流程操作。</div>';
}

async function loadTimeline(id) {
  const data = await api(`/api/v1/requirements/${id}/timeline`);
  $("#timeline-title").textContent = `采购申请 #${id}`;
  $("#timeline").innerHTML = renderTimeline(id, data.items);
}

async function loadRequirementFlow(id) {
  const data = await api(`/api/v1/requirements/${id}/timeline`);
  const container = $("#requirement-flow");
  if (container && state.requirementId === id) {
    container.innerHTML = renderTimeline(id, data.items);
  }
}

async function revealTimelineContact(button) {
  const requirementId = Number(button.dataset.contactRequirement);
  const logId = Number(button.dataset.contactLog);
  const subject = button.dataset.contactSubject;
  const data = await api(
    `/api/v1/requirements/${requirementId}/timeline/${logId}/contact`,
    { query: { subject } },
  );
  button.textContent = data.mobile || "未留联系方式";
  button.classList.add("revealed");
  button.title = `${data.employee_name}的完整手机号`;
}

async function openAgentSession() {
  const action = $("#agent-action").value.trim();
  if (!action) throw new Error("请填写业务动作");
  const data = await api("/api/v1/agent/conversations/active", {
    method: "POST",
    body: { current_action: action },
  });
  state.agentConversationId = data.conversation_id;
  $("#agent-session-badge").textContent = `会话 #${data.conversation_id} · ${data.status}`;
  toast(`已获取活动会话 #${data.conversation_id}`);
  await Promise.all([loadAgentMessages(), readAgentState()]);
}

async function sendAgentMessage() {
  if (!state.agentConversationId) throw new Error("请先获取活动会话");
  await api(`/api/v1/agent/conversations/${state.agentConversationId}/messages`, {
    method: "POST",
    body: {
      external_message_id: token("MSG"),
      sender_type: $("#agent-sender").value,
      content: $("#agent-message").value,
    },
  });
  toast("消息已写入 MySQL");
  await loadAgentMessages();
}

async function loadAgentMessages() {
  if (!state.agentConversationId) return;
  const data = await api(`/api/v1/agent/conversations/${state.agentConversationId}/messages`, {
    query: { page: 1, page_size: 100 },
  });
  $("#agent-messages").innerHTML = data.items.length
    ? data.items
        .map(
          (item) => `<div class="message ${item.sender_type.toLowerCase()}"><strong>${item.sender_type}</strong>${escapeHtml(item.content)}</div>`,
        )
        .join("")
    : '<div class="empty-state">会话中还没有消息。</div>';
}

async function saveAgentState() {
  if (!state.agentConversationId) throw new Error("请先获取活动会话");
  let collected;
  try {
    collected = JSON.parse($("#agent-collected").value);
  } catch {
    throw new Error("collected_data 不是有效 JSON");
  }
  const missing = $("#agent-missing")
    .value.split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const data = await api(`/api/v1/agent/conversations/${state.agentConversationId}/state`, {
    method: "PUT",
    body: {
      purchase_request_id: null,
      current_action: $("#agent-action").value.trim(),
      collected_data: collected,
      missing_fields: missing,
      pending_field: missing[0] || null,
      awaiting_confirmation: false,
      recent_messages: [],
      last_recommendations: [],
    },
  });
  toast(`状态已保存，TTL ${data.expires_in_seconds} 秒`);
  await readAgentState();
}

async function readAgentState() {
  if (!state.agentConversationId) throw new Error("请先获取活动会话");
  const data = await api(`/api/v1/agent/conversations/${state.agentConversationId}/state`);
  $("#agent-state-preview").textContent = JSON.stringify(data, null, 2);
}

async function snapshotAgentState() {
  if (!state.agentConversationId) throw new Error("请先获取活动会话");
  const data = await api(`/api/v1/agent/conversations/${state.agentConversationId}/snapshot`, {
    method: "POST",
    body: { snapshot_reason: "USER_CONFIRMED" },
  });
  toast(`MySQL 快照 #${data.state_id} 已保存`);
}

async function completeAgentSession() {
  if (!state.agentConversationId) throw new Error("请先获取活动会话");
  const id = state.agentConversationId;
  const data = await api(`/api/v1/agent/conversations/${id}/complete`, {
    method: "POST",
    body: {},
  });
  $("#agent-session-badge").textContent = `会话 #${id} · ${data.status}`;
  state.agentConversationId = null;
  toast("会话已完成，Redis 状态已清理");
}

async function loadNotifications() {
  const status = $("#notification-status").value;
  const isAdmin = state.role.id === "test-user-05";
  const callout = $("#notification-permission");
  callout.className = `permission-callout ${isAdmin ? "ok" : ""}`;
  callout.textContent = isAdmin
    ? "当前为管理员身份，可以查看失败原因并将失败通知重新入队。"
    : "此区域仅管理员可用。切换到“系统管理员”体验查询和补发。";
  if (!isAdmin) {
    $("#notification-table").innerHTML =
      '<tr><td colspan="8"><div class="empty-state">当前身份没有通知管理权限。</div></td></tr>';
    return;
  }
  const data = await api("/api/v1/notifications", {
    query: { status, page: 1, page_size: 100 },
  });
  $("#notification-table").innerHTML = data.items.length
    ? data.items
        .map(
          (item) => `<tr>
            <td>#${item.notification_id}</td>
            <td>${escapeHtml(item.event_type)}</td>
            <td>${escapeHtml(item.receiver_platform_user_id_snapshot)}</td>
            <td><span class="status-badge" data-status="${item.status}">${item.status}</span></td>
            <td>${item.retry_count}</td>
            <td>${formatDate(item.next_retry_at)}</td>
            <td title="${escapeHtml(item.last_error)}">${escapeHtml((item.last_error || "—").slice(0, 30))}</td>
            <td>${item.status === "FAILED" ? `<button class="button secondary" type="button" data-resend="${item.notification_id}">重新入队</button>` : ""}</td>
          </tr>`,
        )
        .join("")
    : '<tr><td colspan="8"><div class="empty-state">没有匹配的通知。</div></td></tr>';
}

async function resendNotification(id) {
  const data = await api(`/api/v1/notifications/${id}/resend`, {
    method: "POST",
    body: { reason: "体验界面人工补发", action_token: token("RESEND") },
  });
  toast(`通知 #${id} 已重新入队`);
  showModal("补发结果", data);
  await loadNotifications();
}

function bind(selector, event, handler) {
  $(selector).addEventListener(event, async (...args) => {
    try {
      await handler(...args);
    } catch (error) {
      showError(error);
    }
  });
}

function initializeEvents() {
  bind("#role-current", "click", () => {
    $("#role-menu").hidden = !$("#role-menu").hidden;
  });
  $("#role-menu").addEventListener("click", (event) => {
    const button = event.target.closest("[data-role]");
    if (button) switchRole(button.dataset.role);
  });
  $$(".nav-item").forEach((item) => item.addEventListener("click", () => setTab(item.dataset.tab)));
  bind("#refresh-button", "click", loadCurrentTab);
  bind("#load-requirements", "click", loadRequirements);
  bind("#create-requirement", "click", createRequirement);
  $("#requirement-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-requirement]");
    if (button) openRequirement(Number(button.dataset.requirement)).catch(showError);
  });
  $("#scenario-strip").addEventListener("click", (event) => {
    const button = event.target.closest("[data-requirement]");
    if (button) openRequirement(Number(button.dataset.requirement)).catch(showError);
  });
  $("#requirement-detail").addEventListener("click", (event) => {
    const contact = event.target.closest("[data-contact-log]");
    if (contact) {
      revealTimelineContact(contact).catch(showError);
      return;
    }
    const button = event.target.closest("[data-action]");
    if (button) runRequirementAction(button.dataset.action).catch(showError);
  });
  $("#requirement-detail").addEventListener("input", (event) => {
    if (event.target.closest("[data-form]")) state.requirementDirty = true;
  });
  $("#requirement-detail").addEventListener("change", (event) => {
    if (event.target.closest("[data-form]")) state.requirementDirty = true;
  });
  bind("#search-suppliers", "click", searchSuppliers);
  bind("#create-supplier", "click", createSupplier);
  $("#supplier-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-supplier]");
    if (button) openSupplier(Number(button.dataset.supplier)).catch(showError);
  });
  bind("#load-products", "click", loadProductRecommendations);
  bind("#add-blacklist", "click", addBlacklist);
  bind("#release-blacklist", "click", releaseBlacklist);
  bind("#load-records", "click", loadRecords);
  $("#record-table").addEventListener("click", (event) => {
    const button = event.target.closest("[data-timeline]");
    if (button) loadTimeline(Number(button.dataset.timeline)).catch(showError);
  });
  $("#timeline").addEventListener("click", (event) => {
    const contact = event.target.closest("[data-contact-log]");
    if (contact) revealTimelineContact(contact).catch(showError);
  });
  bind("#agent-open", "click", openAgentSession);
  bind("#agent-send", "click", sendAgentMessage);
  bind("#agent-save-state", "click", saveAgentState);
  bind("#agent-read-state", "click", readAgentState);
  bind("#agent-snapshot", "click", snapshotAgentState);
  bind("#agent-complete", "click", completeAgentSession);
  bind("#load-notifications", "click", loadNotifications);
  $("#notification-table").addEventListener("click", (event) => {
    const button = event.target.closest("[data-resend]");
    if (button) resendNotification(Number(button.dataset.resend)).catch(showError);
  });
  bind("#modal-close", "click", () => {
    $("#modal").hidden = true;
  });
  $("#modal").addEventListener("click", (event) => {
    if (event.target === $("#modal")) $("#modal").hidden = true;
  });
}

async function initialize() {
  renderRoles();
  renderRoleWorkspace();
  renderScenarios();
  initializeEvents();
  await loadIdentity();
  await loadRequirements();
}

initialize().catch(showError);
