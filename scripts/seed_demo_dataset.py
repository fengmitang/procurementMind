"""Build the isolated, deterministic full synthetic development dataset.

The namespace is intentionally independent from ``TEST-*`` fixtures.  Running
this module repeatedly is safe: the DEMO namespace is removed in FK order and
then recreated from the same random seed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.db.session import engine
from app.domain.enums import ConversationStatus, PurchaseStatus, RoleCode
from app.models.agent import AgentConversation, AgentMessage, AgentSessionState
from app.models.identity import (
    AdminOperationLog,
    Building,
    Employee,
    EmployeeBuilding,
    EmployeeExternalIdentity,
    EmployeeRole,
    Role,
)
from app.models.knowledge import KnowledgeDocument, KnowledgeParent
from app.models.notification import NotificationOutbox
from app.models.procurement import (
    PurchaseExecution,
    PurchaseOperationLog,
    PurchaseRequest,
    PurchaseReview,
    Supplier,
    SupplierBlacklist,
    WarehouseReceipt,
)
from app.schemas.procurement import DEVICE_PROFESSIONS

RANDOM_SEED = 20260819
DEMO_NOW = datetime(2026, 8, 19, 12, 0)
EMPLOYEE_IDS = range(8_100_001, 8_100_029)
SUPPLIER_IDS = range(8_200_001, 8_200_037)
REQUEST_IDS = range(8_300_001, 8_300_211)
CONVERSATION_IDS = range(8_400_001, 8_400_013)
DEMO_BUILDING_IDS = (8_000_007, 8_000_008, 8_000_009)
DEMO_PLATFORM = "WEB"

STATUS_COUNTS = {
    PurchaseStatus.DRAFT.value: 20,
    PurchaseStatus.PENDING_REVIEW.value: 25,
    PurchaseStatus.REJECTED.value: 15,
    PurchaseStatus.PENDING_PURCHASE.value: 25,
    PurchaseStatus.PURCHASING.value: 25,
    PurchaseStatus.PENDING_WAREHOUSE.value: 35,
    PurchaseStatus.COMPLETED.value: 65,
}

PROFESSION_COUNTS = {
    "10kV开关柜": 10,
    "变压器": 10,
    "400V配电柜": 10,
    "UPS": 18,
    "高压直流": 8,
    "蓄电池": 12,
    "监控": 10,
    "冷水机组": 15,
    "SHU": 8,
    "冷却塔": 8,
    "冷却泵": 8,
    "机房环境": 10,
    "水系统": 8,
    "传输": 15,
    "服务器": 26,
    "运维工具": 18,
    "列间空调": 16,
}

CATALOG: dict[str, dict[str, Any]] = {
    "10kV开关柜": {
        "devices": ["10kV开关柜", "真空断路器", "微机保护装置", "保护测控单元"],
        "brands": ["ABB", "施耐德", "西门子", "正泰"],
        "price": (8000, 90000),
        "unit": "台",
    },
    "变压器": {
        "devices": ["干式变压器", "变压器温控器", "横流冷却风机", "温控显示模块"],
        "brands": ["西门子", "正泰", "德力西"],
        "price": (1500, 180000),
        "unit": "台",
    },
    "400V配电柜": {
        "devices": ["低压配电柜", "ATS切换装置", "塑壳断路器", "框架断路器", "智能仪表"],
        "brands": ["ABB", "施耐德", "西门子", "正泰"],
        "price": (3000, 100000),
        "unit": "台",
    },
    "UPS": {
        "devices": ["UPS主机", "UPS功率模块", "UPS模块", "集中旁路模块", "UPS控制板"],
        "brands": ["科士达", "维谛", "科华", "伊顿"],
        "price": (5000, 80000),
        "unit": "台",
    },
    "高压直流": {
        "devices": ["高频开关电源模块", "整流模块", "监控模块", "配电单元"],
        "brands": ["华为", "维谛", "科华"],
        "price": (3000, 50000),
        "unit": "个",
    },
    "蓄电池": {
        "devices": ["铅酸蓄电池", "蓄电池组", "电池监控模块", "电池采集模块"],
        "brands": ["GNB", "理士", "双登", "南都"],
        "price": (500, 18000),
        "unit": "只",
    },
    "监控": {
        "devices": ["温湿度传感器", "漏水检测模块", "压力传感器", "动环监控网关", "门禁控制器"],
        "brands": ["海康威视", "华为", "安科瑞"],
        "price": (200, 12000),
        "unit": "个",
    },
    "冷水机组": {
        "devices": ["冷水机组", "冷水机组控制板", "压缩机组件", "水流开关", "温度传感器"],
        "brands": ["约克", "开利", "特灵"],
        "price": (1500, 480000),
        "unit": "台",
    },
    "SHU": {
        "devices": ["SHU末端机组", "EC风机", "SHU控制器", "过滤器"],
        "brands": ["维谛", "英维克", "佳力图"],
        "price": (500, 90000),
        "unit": "个",
    },
    "冷却塔": {
        "devices": ["冷却塔电机", "冷却塔风机", "减震器", "皮带", "布水器"],
        "brands": ["马利", "览讯", "亚士霸"],
        "price": (300, 80000),
        "unit": "个",
    },
    "冷却泵": {
        "devices": ["冷却水泵", "水泵轴承", "机械密封", "联轴器", "变频器"],
        "brands": ["格兰富", "威乐", "南方泵业"],
        "price": (400, 70000),
        "unit": "个",
    },
    "机房环境": {
        "devices": ["加湿模块", "除湿设备", "环境传感器", "空气过滤组件", "漏水检测带"],
        "brands": ["维谛", "英维克", "海康威视"],
        "price": (200, 30000),
        "unit": "个",
    },
    "水系统": {
        "devices": ["板式换热器", "电动调节阀", "水流开关", "压差表", "压力变送器", "水处理设备"],
        "brands": ["西门子", "施耐德", "霍尼韦尔"],
        "price": (300, 120000),
        "unit": "个",
    },
    "传输": {
        "devices": ["汇聚交换机", "接入交换机", "光模块", "万兆光模块", "OTN板卡", "光纤跳线"],
        "brands": ["华为", "中兴", "新华三"],
        "price": (300, 50000),
        "unit": "个",
    },
    "服务器": {
        "devices": ["服务器", "机架式服务器", "机架服务器", "业务服务器", "管控服务器"],
        "brands": ["浪潮", "华为", "新华三", "联想", "戴尔"],
        "price": (8000, 50000),
        "unit": "台",
    },
    "运维工具": {
        "devices": [
            "数字万用表",
            "钳形电流表",
            "红外测温仪",
            "螺丝刀套装",
            "网线测试仪",
            "标签打印机",
        ],
        "brands": ["福禄克", "世达", "优利德"],
        "price": (50, 3000),
        "unit": "件",
    },
    "列间空调": {
        "devices": ["列间空调", "压缩机", "EC风机", "电源模块", "主控板"],
        "brands": ["英维克", "维谛", "佳力图"],
        "price": (3000, 150000),
        "unit": "台",
    },
}

SERVER_MODELS = [
    ("浪潮", "NF5180M6"),
    ("华为", "FusionServer 2288H V6"),
    ("新华三", "UniServer R4900 G5"),
    ("联想", "ThinkSystem SR650 V3"),
    ("戴尔", "PowerEdge R760"),
]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _snapshot(employee_id: int) -> dict[str, Any]:
    index = employee_id - 8_100_000
    return {
        "platform_type_snapshot": DEMO_PLATFORM,
        "platform_user_id_snapshot": f"demo_user_{index:03d}",
        "name_snapshot": f"演示员工{index:02d}",
        "mobile_snapshot": f"DEMO-MOBILE-{index:03d}",
    }


def employee_rows() -> list[dict[str, Any]]:
    labels = [
        "演示需求人",
        "演示楼长A",
        "演示采购员",
        "演示仓管员",
        "演示管理员",
        "演示需求人兼楼长",
        "演示楼长兼采购员",
        "演示采购员兼仓管",
        "演示楼长B",
        "演示楼长C",
        "演示楼长D",
        *[f"演示业务员{i:02d}" for i in range(1, 18)],
    ]
    return [
        {
            "employee_id": employee_id,
            "employee_no": f"DEMO-E{index:03d}",
            "name": labels[index - 1],
            "mobile": f"DEMO-MOBILE-{index:03d}",
            "status": True,
            "created_at": DEMO_NOW - timedelta(days=400),
            "updated_at": DEMO_NOW,
        }
        for index, employee_id in enumerate(EMPLOYEE_IDS, 1)
    ]


def identity_rows() -> list[dict[str, Any]]:
    return [
        {
            "identity_id": 8_110_000 + index,
            "employee_id": employee_id,
            "platform_type": DEMO_PLATFORM,
            "platform_user_id": f"demo_user_{index:03d}",
            "status": True,
            "last_synced_at": DEMO_NOW,
        }
        for index, employee_id in enumerate(EMPLOYEE_IDS, 1)
    ]


def supplier_rows() -> list[dict[str, Any]]:
    regions = ["南京", "苏州", "无锡", "上海", "合肥", "杭州", "成都", "武汉", "常州"]
    terms = [
        "云维机电",
        "恒启电气",
        "启辰数据",
        "智联通信",
        "新能制冷",
        "恒远电源",
        "众达设备",
        "锐捷科技",
    ]
    rows = []
    for index, supplier_id in enumerate(SUPPLIER_IDS, 1):
        rows.append(
            {
                "supplier_id": supplier_id,
                "supplier_name": (
                    f"{regions[(index - 1) % len(regions)]}"
                    f"{terms[(index - 1) % len(terms)]}{index:02d}号有限公司"
                ),
                "unified_social_credit_code": f"DEMO-CREDIT-{index:04d}",
                "bank_name": f"DEMO银行{(index % 4) + 1}号支行",
                "bank_account": f"DEMO-ACCOUNT-{index:04d}",
                "registered_address": f"DEMO市数据中心产业园{index:02d}号",
                "contract_contact_info": None if index % 7 == 0 else f"DEMO-CONTACT-{index:03d}",
                "status": index <= 32,
                "created_at": DEMO_NOW - timedelta(days=500),
                "updated_at": DEMO_NOW,
            }
        )
    return rows


def _profession_status_pairs() -> list[tuple[str, str]]:
    rng = random.Random(RANDOM_SEED)
    pairs: list[tuple[str, str]] = []
    remaining_professions: list[str] = []
    for profession, count in PROFESSION_COUNTS.items():
        pairs.extend(
            [
                (profession, PurchaseStatus.COMPLETED.value),
                (profession, PurchaseStatus.PENDING_WAREHOUSE.value),
            ]
        )
        remaining_professions.extend([profession] * (count - 2))
    remaining_statuses: list[str] = []
    used = Counter(status for _, status in pairs)
    for status, count in STATUS_COUNTS.items():
        remaining_statuses.extend([status] * (count - used[status]))
    rng.shuffle(remaining_professions)
    rng.shuffle(remaining_statuses)
    pairs.extend(zip(remaining_professions, remaining_statuses, strict=True))
    # Server recommendation needs enough legal history while preserving all totals.
    while sum(p == "服务器" and s in {"COMPLETED", "PENDING_WAREHOUSE"} for p, s in pairs) < 18:
        server_index = next(
            i
            for i, (p, s) in enumerate(pairs)
            if p == "服务器" and s not in {"COMPLETED", "PENDING_WAREHOUSE"}
        )
        history_index = next(
            i
            for i, (p, s) in enumerate(pairs)
            if p != "服务器"
            and s in {"COMPLETED", "PENDING_WAREHOUSE"}
            and sum(pp == p and ss in {"COMPLETED", "PENDING_WAREHOUSE"} for pp, ss in pairs) > 2
        )
        p1, s1 = pairs[server_index]
        p2, s2 = pairs[history_index]
        pairs[server_index], pairs[history_index] = (p1, s2), (p2, s1)
    rng.shuffle(pairs)
    return pairs


def _created_time(index: int) -> datetime:
    # Uniform, deterministic coverage of the preceding twelve months.
    return DEMO_NOW - timedelta(days=(index * 37) % 355 + 8, hours=index % 7)


def _quantity(profession: str, index: int, rng: random.Random) -> int:
    if profession in {"蓄电池", "传输"}:
        value = rng.randint(10, 100)
    elif profession == "运维工具":
        value = rng.randint(5, 80)
    elif "模块" in CATALOG[profession]["devices"][index % len(CATALOG[profession]["devices"])]:
        value = rng.randint(2, 30)
    else:
        value = rng.randint(1, 10)
    return 420 if index == 188 else value


def _server_product(history_rank: int, recent: bool) -> tuple[str, str]:
    if recent:
        return SERVER_MODELS[1]
    sequence = [
        SERVER_MODELS[0],
        SERVER_MODELS[0],
        SERVER_MODELS[0],
        SERVER_MODELS[0],
        SERVER_MODELS[0],
        SERVER_MODELS[0],
        SERVER_MODELS[1],
        SERVER_MODELS[1],
        SERVER_MODELS[2],
        SERVER_MODELS[2],
        SERVER_MODELS[2],
        SERVER_MODELS[3],
        SERVER_MODELS[3],
        SERVER_MODELS[3],
        SERVER_MODELS[4],
        SERVER_MODELS[4],
    ]
    return sequence[history_rank % len(sequence)]


def build_dataset(
    building_ids: list[int], role_ids: dict[str, int]
) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(RANDOM_SEED)
    suppliers = supplier_rows()
    supplier_by_id = {row["supplier_id"]: row for row in suppliers}
    pairs = _profession_status_pairs()
    applicants = list(EMPLOYEE_IDS)[11:]
    manager_sequence = [
        8_100_002,
        8_100_002,
        8_100_009,
        8_100_009,
        8_100_010,
        8_100_010,
        8_100_011,
        8_100_011,
        8_100_011,
    ]
    managers_by_building = dict(zip(building_ids, manager_sequence, strict=True))
    purchasers = [8_100_003, 8_100_007, 8_100_008]
    warehouses = [8_100_004, 8_100_008]
    requests: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    server_history_rank = 0
    contract_pattern_count = 0
    profession_seen: Counter[str] = Counter()
    history_statuses = {PurchaseStatus.PENDING_WAREHOUSE.value, PurchaseStatus.COMPLETED.value}

    for index, ((profession, status), request_id) in enumerate(
        zip(pairs, REQUEST_IDS, strict=True), 1
    ):
        spec = CATALOG[profession]
        profession_seen[profession] += 1
        device_name = spec["devices"][(profession_seen[profession] - 1) % len(spec["devices"])]
        building_id = building_ids[(index - 1) % 9]
        applicant_id = applicants[(index - 1) % len(applicants)]
        created_at = _created_time(index)
        submitted_at = created_at + timedelta(hours=4)
        reviewed_at = submitted_at + timedelta(days=1)
        purchased_at = reviewed_at + timedelta(days=2)
        received_at = purchased_at + timedelta(days=4)
        if index == 177:
            received_at += timedelta(days=18)
        completed_at = received_at + timedelta(hours=2)
        is_recent = purchased_at >= DEMO_NOW - timedelta(days=60)
        if profession == "服务器" and status in history_statuses:
            brand, model = _server_product(server_history_rank, is_recent)
            server_history_rank += 1
        else:
            brand = spec["brands"][(index - 1) % len(spec["brands"])]
            model = None if index % 6 == 0 else f"{device_name}-{(index % 4) + 1}型"
        if index % 7 == 0 and not (profession == "服务器" and status in history_statuses):
            brand = None
        quantity = _quantity(profession, index, rng)
        low, high = spec["price"]
        unit_price = Decimal(str(round(rng.uniform(low, high), 2)))
        if index == 177:
            unit_price *= 3
        estimated_price = (unit_price * Decimal(str(rng.uniform(0.92, 1.08)))).quantize(
            Decimal("0.01")
        )
        manager_id = managers_by_building[building_id]
        purchaser_id = purchasers[index % len(purchasers)]
        warehouse_id = warehouses[index % len(warehouses)]
        current_handler = {
            "PENDING_REVIEW": manager_id,
            "REJECTED": applicant_id,
            "PENDING_PURCHASE": purchaser_id,
            "PURCHASING": purchaser_id,
            "PENDING_WAREHOUSE": warehouse_id,
        }.get(status)
        reason_templates = [
            f"{building_id}号楼{device_name}近期频繁告警，申请更换备件",
            f"现网{device_name}运行年限较长，计划分批替换",
            f"新业务上线，需要补充{device_name}资源",
            f"日常维护库存不足，申请补充{device_name}",
            f"原{device_name}故障后无法修复，需要更换",
        ]
        request = {
            "request_id": request_id,
            "request_no": f"DEMO-PR-{index:04d}",
            "building_id": building_id,
            "applicant_employee_id": applicant_id,
            "applicant_platform_type_snapshot": DEMO_PLATFORM,
            "applicant_platform_user_id_snapshot": f"demo_user_{applicant_id - 8_100_000:03d}",
            "applicant_name_snapshot": f"演示员工{applicant_id - 8_100_000:02d}",
            "applicant_mobile_snapshot": f"DEMO-MOBILE-{applicant_id - 8_100_000:03d}",
            "device_profession": profession,
            "device_name": device_name,
            "brand": brand,
            "model": model,
            "quantity": quantity,
            "unit": spec["unit"],
            "application_reason": reason_templates[index % len(reason_templates)],
            "applicant_remark": None if index % 4 else "请结合现场维保窗口安排交付",
            "status": status,
            "current_handler_employee_id": current_handler,
            "version": 1 + (status not in {"DRAFT", "PENDING_REVIEW"}),
            "submitted_at": None if status == "DRAFT" else submitted_at,
            "completed_at": completed_at if status == "COMPLETED" else None,
            "created_at": created_at,
            "updated_at": completed_at if status == "COMPLETED" else DEMO_NOW,
        }
        requests.append(request)

        # Reviews exist from review stage onward; pending review has a draft review.
        if status not in {"DRAFT"}:
            review_completed = status != "PENDING_REVIEW"
            rejected = status == "REJECTED"
            supplier_id = 8_200_001 + ((index * 5) % 28)
            if supplier_id == 8_200_005:
                supplier_id = 8_200_006
            if status in history_statuses and profession != "服务器" and contract_pattern_count < 9:
                supplier_id = 8_200_005
            supplier = supplier_by_id[supplier_id]
            reviews.append(
                {
                    "review_id": 8_500_000 + index,
                    "request_id": request_id,
                    "review_round": 1,
                    "review_status": "COMPLETED" if review_completed else "DRAFT",
                    "reviewer_employee_id": manager_id,
                    "reviewer_platform_type_snapshot": DEMO_PLATFORM,
                    "reviewer_platform_user_id_snapshot": f"demo_user_{manager_id - 8_100_000:03d}",
                    "reviewer_name_snapshot": f"演示楼长{manager_id - 8_100_000:02d}",
                    "reviewer_mobile_snapshot": f"DEMO-MOBILE-{manager_id - 8_100_000:03d}",
                    "review_result": "REJECTED"
                    if rejected
                    else "APPROVED"
                    if review_completed
                    else None,
                    "review_opinion": "申请依据不足，请补充故障记录"
                    if rejected
                    else "需求合理，按预算推进"
                    if review_completed
                    else None,
                    "proposed_supplier_id": None
                    if rejected or not review_completed
                    else supplier_id,
                    "proposed_supplier_name": None
                    if rejected or not review_completed
                    else supplier["supplier_name"],
                    "supplier_contact_name": None if index % 7 == 0 else f"联系人{index % 9 + 1}",
                    "supplier_contact_info": None
                    if index % 7 == 0
                    else f"DEMO-SUPPLIER-CONTACT-{supplier_id % 1000:03d}",
                    "supplier_link": None,
                    "estimated_unit_price": None
                    if rejected or not review_completed
                    else estimated_price,
                    "estimated_total_price": None
                    if rejected or not review_completed
                    else (estimated_price * quantity).quantize(Decimal("0.01")),
                    "need_contract": bool(index % 3),
                    "contract_type": None
                    if index % 6 == 0
                    else ["框架协议", "单次采购合同", "年度采购合同", "零星采购"][index % 4],
                    "payment_method": None
                    if index % 10 == 0
                    else ["到货验收后30天", "月结30天", "验收后一次性付款"][index % 3],
                    "expected_arrival_date": (
                        DEMO_NOW + timedelta(days=14)
                        if status == "PENDING_WAREHOUSE" and index % 10
                        else purchased_at + timedelta(days=3 if index == 12 else 7)
                    ).date()
                    if review_completed and not rejected
                    else None,
                    "warranty_info": None if index % 5 == 0 else "验收后12个月质保",
                    "review_remark": None if index % 4 else "到货前联系楼宇管理员",
                    "reviewed_at": reviewed_at if review_completed else None,
                }
            )

        if status in history_statuses:
            supplier_id = 8_200_001 + ((index * 5) % 28)
            if supplier_id == 8_200_005:
                supplier_id = 8_200_006
            # Server history deliberately concentrates suppliers and makes #1 blacklisted.
            if profession == "服务器":
                supplier_id = [
                    8_200_001,
                    8_200_001,
                    8_200_001,
                    8_200_001,
                    8_200_002,
                    8_200_002,
                    8_200_002,
                    8_200_003,
                    8_200_003,
                    8_200_004,
                ][server_history_rank % 10]
            elif contract_pattern_count < 9:
                supplier_id = 8_200_005
                contract_pattern_count += 1
            supplier = supplier_by_id[supplier_id]
            combo_rank = sum(1 for row in executions if row["supplier_id"] == 8_200_005)
            if supplier_id == 8_200_005:
                if combo_rank < 6:
                    tax_rate, contract_contact = Decimal("13.00"), "DEMO-CONTACT-A"
                elif combo_rank < 8:
                    tax_rate, contract_contact = Decimal("9.00"), "DEMO-CONTACT-B"
                else:
                    tax_rate, contract_contact = Decimal("13.00"), "DEMO-CONTACT-C"
            else:
                tax_rate = (
                    None
                    if index % 19 == 0
                    else [Decimal("13.00"), Decimal("9.00"), Decimal("6.00")][index % 3]
                )
                contract_contact = None if index % 7 == 0 else supplier["contract_contact_info"]
            executions.append(
                {
                    "execution_id": 8_600_000 + index,
                    "request_id": request_id,
                    "purchaser_employee_id": purchaser_id,
                    "purchaser_platform_type_snapshot": DEMO_PLATFORM,
                    "purchaser_platform_user_id_snapshot": (
                        f"demo_user_{purchaser_id - 8_100_000:03d}"
                    ),
                    "purchaser_name_snapshot": f"演示采购员{purchaser_id - 8_100_000:02d}",
                    "purchaser_mobile_snapshot": f"DEMO-MOBILE-{purchaser_id - 8_100_000:03d}",
                    "supplier_id": supplier_id,
                    "supplier_name_snapshot": supplier["supplier_name"],
                    "supplier_tax_no_snapshot": supplier["unified_social_credit_code"],
                    "supplier_bank_name_snapshot": supplier["bank_name"],
                    "supplier_bank_account_snapshot": supplier["bank_account"],
                    "supplier_address_snapshot": supplier["registered_address"],
                    "contract_contact_info_snapshot": contract_contact,
                    "actual_unit_price": unit_price.quantize(Decimal("0.01")),
                    "actual_total_price": (unit_price * quantity).quantize(Decimal("0.01")),
                    "tax_rate": tax_rate,
                    "purchased_at": purchased_at,
                    "execution_remark": "DEMO合成历史采购记录",
                    "created_at": purchased_at,
                }
            )
        if status == "COMPLETED":
            received_quantity = quantity - 1 if index in {177, 188} and quantity > 1 else quantity
            preferred = {
                "服务器": "1号楼一层设备仓",
                "传输": "1号楼一层设备仓",
                "UPS": "2号楼电气备件仓",
                "10kV开关柜": "2号楼电气备件仓",
                "400V配电柜": "2号楼电气备件仓",
                "蓄电池": "2号楼电气备件仓",
                "冷水机组": "8号楼暖通备件仓",
                "冷却塔": "8号楼暖通备件仓",
                "冷却泵": "8号楼暖通备件仓",
                "水系统": "8号楼暖通备件仓",
            }.get(profession, "中心公共备件仓")
            location = "4号楼设备暂存区" if index % 11 == 0 else preferred
            receipts.append(
                {
                    "receipt_id": 8_700_000 + index,
                    "request_id": request_id,
                    "warehouse_employee_id": warehouse_id,
                    "warehouse_platform_type_snapshot": DEMO_PLATFORM,
                    "warehouse_platform_user_id_snapshot": (
                        f"demo_user_{warehouse_id - 8_100_000:03d}"
                    ),
                    "warehouse_name_snapshot": f"演示仓管员{warehouse_id - 8_100_000:02d}",
                    "warehouse_mobile_snapshot": f"DEMO-MOBILE-{warehouse_id - 8_100_000:03d}",
                    "warehouse_location": location,
                    "received_quantity": received_quantity,
                    "receipt_remark": "分批到货，本次数量与申请不一致"
                    if received_quantity != quantity
                    else None,
                    "received_at": received_at,
                }
            )

        logs.extend(
            _operation_logs(
                index,
                request,
                manager_id,
                purchaser_id,
                warehouse_id,
                submitted_at,
                reviewed_at,
                purchased_at,
                received_at,
                role_ids,
            )
        )

    _enforce_recommendation_patterns(requests, executions, receipts)
    return {
        "employees": employee_rows(),
        "identities": identity_rows(),
        "suppliers": suppliers,
        "requests": requests,
        "reviews": reviews,
        "executions": executions,
        "receipts": receipts,
        "logs": logs,
    }


def _enforce_recommendation_patterns(
    requests: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
) -> None:
    request_by_id = {row["request_id"]: row for row in requests}
    server_executions = sorted(
        (
            row
            for row in executions
            if request_by_id[row["request_id"]]["device_profession"] == "服务器"
        ),
        key=lambda row: row["purchased_at"],
        reverse=True,
    )
    recent = [
        row for row in server_executions if row["purchased_at"] >= DEMO_NOW - timedelta(days=60)
    ]
    older = [row for row in server_executions if row not in recent]
    for execution in recent:
        request_by_id[execution["request_id"]]["device_name"] = "服务器"
        request_by_id[execution["request_id"]].update(
            brand=SERVER_MODELS[1][0], model=SERVER_MODELS[1][1]
        )
    older_products = (
        [SERVER_MODELS[0]] * 8
        + [SERVER_MODELS[1]]
        + [SERVER_MODELS[2]] * 3
        + [SERVER_MODELS[3]] * 2
        + [SERVER_MODELS[4]]
    )
    for execution, product in zip(older, older_products, strict=True):
        request_by_id[execution["request_id"]]["device_name"] = "服务器"
        request_by_id[execution["request_id"]].update(brand=product[0], model=product[1])

    server_receipts = [
        row for row in receipts if request_by_id[row["request_id"]]["device_profession"] == "服务器"
    ]
    locations = ["1号楼一层设备仓"] * 7 + ["中心公共备件仓"] * 4 + ["4号楼设备暂存区"]
    for receipt, location in zip(server_receipts, locations, strict=True):
        receipt["warehouse_location"] = location
    mismatch = receipts[0]
    requested = request_by_id[mismatch["request_id"]]["quantity"]
    if requested > 1:
        mismatch["received_quantity"] = requested - 1
        mismatch["receipt_remark"] = "分批到货，尚有1件待入库"


def _operation_logs(
    index: int,
    request: dict[str, Any],
    manager_id: int,
    purchaser_id: int,
    warehouse_id: int,
    submitted_at: datetime,
    reviewed_at: datetime,
    purchased_at: datetime,
    received_at: datetime,
    role_ids: dict[str, int],
) -> list[dict[str, Any]]:
    status = request["status"]
    request_id = request["request_id"]
    applicant_id = request["applicant_employee_id"]
    steps: list[tuple[str, str | None, str, int, str, datetime, int | None]] = [
        (
            "CREATE_DRAFT",
            None,
            "DRAFT",
            applicant_id,
            RoleCode.APPLICANT.value,
            request["created_at"],
            applicant_id,
        ),
    ]
    if status != "DRAFT":
        steps.append(
            (
                "SUBMIT_REVIEW",
                "DRAFT",
                "PENDING_REVIEW",
                applicant_id,
                RoleCode.APPLICANT.value,
                submitted_at,
                manager_id,
            )
        )
    if status == "REJECTED":
        steps.append(
            (
                "REJECT",
                "PENDING_REVIEW",
                "REJECTED",
                manager_id,
                RoleCode.BUILDING_MANAGER.value,
                reviewed_at,
                applicant_id,
            )
        )
    elif status not in {"DRAFT", "PENDING_REVIEW"}:
        steps.append(
            (
                "SUBMIT_PURCHASER",
                "PENDING_REVIEW",
                "PENDING_PURCHASE",
                manager_id,
                RoleCode.BUILDING_MANAGER.value,
                reviewed_at,
                purchaser_id,
            )
        )
        if status not in {"PENDING_PURCHASE"}:
            steps.append(
                (
                    "START_PURCHASE",
                    "PENDING_PURCHASE",
                    "PURCHASING",
                    purchaser_id,
                    RoleCode.PURCHASER.value,
                    reviewed_at + timedelta(hours=4),
                    purchaser_id,
                )
            )
        if status in {"PENDING_WAREHOUSE", "COMPLETED"}:
            steps.append(
                (
                    "SUBMIT_WAREHOUSE",
                    "PURCHASING",
                    "PENDING_WAREHOUSE",
                    purchaser_id,
                    RoleCode.PURCHASER.value,
                    purchased_at + timedelta(hours=2),
                    warehouse_id,
                )
            )
        if status == "COMPLETED":
            steps.append(
                (
                    "COMPLETE",
                    "PENDING_WAREHOUSE",
                    "COMPLETED",
                    warehouse_id,
                    RoleCode.WAREHOUSE_MANAGER.value,
                    received_at + timedelta(hours=2),
                    None,
                )
            )
    role_names = {
        RoleCode.APPLICANT.value: "需求人",
        RoleCode.BUILDING_MANAGER.value: "楼长",
        RoleCode.PURCHASER.value: "采购员",
        RoleCode.WAREHOUSE_MANAGER.value: "仓库管理员",
    }
    result = []
    for sequence, (
        action,
        from_status,
        to_status,
        operator_id,
        role,
        operated_at,
        assigned_to,
    ) in enumerate(steps, 1):
        result.append(
            {
                "log_id": 9_000_000 + index * 10 + sequence,
                "request_id": request_id,
                "operator_employee_id": operator_id,
                "operator_platform_type_snapshot": DEMO_PLATFORM,
                "operator_platform_user_id_snapshot": f"demo_user_{operator_id - 8_100_000:03d}",
                "operator_name_snapshot": f"演示员工{operator_id - 8_100_000:02d}",
                "operator_mobile_snapshot": f"DEMO-MOBILE-{operator_id - 8_100_000:03d}",
                "operator_role_id_snapshot": role_ids[role],
                "operator_role_name_snapshot": role_names[role],
                "assigned_to_employee_id": assigned_to,
                "action_token": f"DEMO-ACTION-{index:04d}-{sequence}",
                "action_type": action,
                "from_status": from_status,
                "to_status": to_status,
                "operation_summary": f"DEMO流程：{action}",
                "operated_at": operated_at,
            }
        )
    return result


def role_and_building_rows(
    role_ids: dict[str, int], building_ids: list[int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    assignments: dict[int, tuple[str, ...]] = {
        8_100_001: ("APPLICANT",),
        8_100_002: ("BUILDING_MANAGER",),
        8_100_003: ("PURCHASER",),
        8_100_004: ("WAREHOUSE_MANAGER",),
        8_100_005: ("ADMIN",),
        8_100_006: ("APPLICANT", "BUILDING_MANAGER"),
        8_100_007: ("BUILDING_MANAGER", "PURCHASER"),
        8_100_008: ("PURCHASER", "WAREHOUSE_MANAGER"),
        8_100_009: ("BUILDING_MANAGER",),
        8_100_010: ("BUILDING_MANAGER",),
        8_100_011: ("BUILDING_MANAGER",),
    }
    for employee_id in list(EMPLOYEE_IDS)[11:]:
        assignments[employee_id] = ("APPLICANT",)
    role_rows = [
        {
            "employee_id": employee_id,
            "role_id": role_ids[role],
            "status": True,
            "synced_at": DEMO_NOW,
        }
        for employee_id, roles in assignments.items()
        for role in roles
    ]
    scope: dict[int, list[int]] = {
        8_100_001: [building_ids[0]],
        8_100_002: building_ids[0:2],
        8_100_006: building_ids[0:2],
        8_100_007: building_ids[2:4],
        8_100_009: building_ids[2:4],
        8_100_010: building_ids[4:6],
        8_100_011: building_ids[6:9],
    }
    for offset, employee_id in enumerate(list(EMPLOYEE_IDS)[11:]):
        scope[employee_id] = [building_ids[offset % 9]]
    building_rows = [
        {
            "employee_id": employee_id,
            "building_id": building_id,
            "is_primary": pos == 0,
            "status": True,
            "synced_at": DEMO_NOW,
        }
        for employee_id, ids in scope.items()
        for pos, building_id in enumerate(ids)
    ]
    return role_rows, building_rows


def _blacklist_rows(dataset: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    execution_by_supplier: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for execution in dataset["executions"]:
        execution_by_supplier[execution["supplier_id"]].append(execution)
    suppliers = [8_200_001, 8_200_002, *list(range(8_200_006, 8_200_016))]
    rows = []
    for index, supplier_id in enumerate(suppliers, 1):
        execution = execution_by_supplier[supplier_id][0]
        supplier = next(row for row in dataset["suppliers"] if row["supplier_id"] == supplier_id)
        released = index in {2, 9, 10, 11, 12}
        limited = index % 3 == 0
        rows.append(
            {
                "blacklist_id": 8_800_000 + index,
                "supplier_id": supplier_id,
                "supplier_name_snapshot": supplier["supplier_name"],
                "source_request_id": execution["request_id"],
                "registrar_employee_id": 8_100_005,
                "registrar_platform_type_snapshot": DEMO_PLATFORM,
                "registrar_platform_user_id_snapshot": "demo_user_005",
                "registrar_name_snapshot": "演示管理员",
                "registrar_mobile_snapshot": "DEMO-MOBILE-005",
                "blacklist_type": "DELIVERY" if index % 2 else "QUALITY",
                "blacklist_reason": [
                    "多次发生到货延期",
                    "交付型号与合同约定不一致",
                    "验收资料长期不完整",
                ][index % 3],
                "duration_type": "LIMITED" if limited else "PERMANENT",
                "start_at": DEMO_NOW - timedelta(days=120 - index),
                "end_at": DEMO_NOW + timedelta(days=90) if limited else None,
                "released_at": DEMO_NOW - timedelta(days=15) if released else None,
                "released_by_employee_id": 8_100_005 if released else None,
                "release_reason": "整改完成，经复核解除" if released else None,
                "status": "RELEASED" if released else "ACTIVE",
                "created_at": DEMO_NOW - timedelta(days=120 - index),
            }
        )
    return rows


def _supporting_rows(dataset: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    request_ids = [row["request_id"] for row in dataset["requests"]]
    notifications = []
    for index in range(1, 26):
        status = ["PENDING", "SENT", "FAILED"][index % 3]
        receiver = 8_100_001 + index % 11
        notifications.append(
            {
                "notification_id": 8_900_000 + index,
                "request_id": request_ids[index * 3],
                "event_type": ["REVIEW_PENDING", "PURCHASE_PENDING", "WAREHOUSE_PENDING"][
                    index % 3
                ],
                "receiver_employee_id": receiver,
                "platform_type": DEMO_PLATFORM,
                "receiver_platform_user_id_snapshot": f"demo_user_{receiver - 8_100_000:03d}",
                "dedup_key": f"demo_notification_{index:03d}",
                "payload": {"demo": True, "request_id": request_ids[index * 3]},
                "status": status,
                "retry_count": 1 if status == "FAILED" else 0,
                "next_retry_at": DEMO_NOW + timedelta(days=3650) if status != "SENT" else None,
                "last_error": "DEMO通道未启用" if status == "FAILED" else None,
                "created_at": DEMO_NOW - timedelta(days=index),
                "sent_at": DEMO_NOW - timedelta(days=index, hours=-1) if status == "SENT" else None,
                "updated_at": DEMO_NOW,
            }
        )
    conversations, messages, states = [], [], []
    statuses = list(ConversationStatus)
    message_id = 9_100_000
    for index, conversation_id in enumerate(CONVERSATION_IDS, 1):
        status = statuses[index % len(statuses)].value
        conversations.append(
            {
                "conversation_id": conversation_id,
                "employee_id": 8_100_011 + index,
                "platform_type": DEMO_PLATFORM,
                "external_conversation_id": f"demo_conversation_{index:03d}",
                "purchase_request_id": request_ids[index * 5],
                "status": status,
                "started_at": DEMO_NOW - timedelta(days=index),
                "last_active_at": DEMO_NOW - timedelta(days=index, minutes=-20),
            }
        )
        contents = [
            "这张采购单现在到哪一步了？",
            "当前已进入采购流程，请关注待办。",
            "给我看看历史供应商情况。",
            "已根据可见历史整理候选证据。",
        ]
        for pos, content in enumerate(contents, 1):
            message_id += 1
            messages.append(
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "external_message_id": f"demo_message_{index:03d}_{pos}",
                    "sender_type": "USER" if pos % 2 else "AGENT",
                    "content": content,
                    "message_data": {"demo": True},
                    "created_at": DEMO_NOW - timedelta(days=index, minutes=-pos * 3),
                }
            )
        states.append(
            {
                "state_id": 9_200_000 + index,
                "conversation_id": conversation_id,
                "current_action": "NONE",
                "state_data": {"demo": True},
                "missing_fields": [],
                "confirmed": status == "COMPLETED",
                "saved_at": DEMO_NOW - timedelta(days=index),
            }
        )
    documents, parents = [], []
    titles = [
        "数据中心采购审批管理办法",
        "供应商黑名单管理办法",
        "采购验收入库规范",
        "设备采购合同管理说明",
    ]
    for d_index, title in enumerate(titles, 1):
        document_id = f"demo_doc_{d_index:02d}"
        documents.append(
            {
                "document_id": document_id,
                "title": title,
                "document_type": "DEMO_POLICY",
                "version": "1.0",
                "status": "ACTIVE",
                "source_path": f"demo://knowledge/{d_index:02d}",
                "content_hash": _hash(title),
                "effective_at": DEMO_NOW - timedelta(days=200),
                "allowed_roles": [role.value for role in RoleCode],
                "device_scopes": None,
                "metadata_json": {"synthetic": True},
                "index_status": "PENDING",
                "indexed_at": None,
                "index_error": None,
                "created_at": DEMO_NOW,
                "updated_at": DEMO_NOW,
            }
        )
        for ordinal in range(1, 4):
            content = f"{title}演示条款{ordinal}：采购业务应保留审批、交付和验收证据。"
            parents.append(
                {
                    "parent_id": f"demo_parent_{d_index:02d}_{ordinal:02d}",
                    "document_id": document_id,
                    "ordinal": ordinal,
                    "title": f"第{ordinal}条",
                    "section_path": [title, f"第{ordinal}条"],
                    "topic": title,
                    "chunk_type": "SECTION",
                    "version": "1.0",
                    "status": "ACTIVE",
                    "content": content,
                    "content_hash": _hash(content),
                    "source_start_line": ordinal * 10,
                    "source_end_line": ordinal * 10 + 5,
                    "metadata_json": {"synthetic": True},
                    "created_at": DEMO_NOW,
                    "updated_at": DEMO_NOW,
                }
            )
    admin_logs = [
        {
            "operation_id": 9_300_000 + index,
            "admin_employee_id": 8_100_005,
            "target_employee_id": 8_100_011 + index,
            "action_type": [
                "ASSIGN_ROLE",
                "REMOVE_ROLE",
                "UPDATE_BUILDING",
                "ENABLE_EMPLOYEE",
                "DISABLE_EMPLOYEE",
            ][index % 5],
            "action_token": f"DEMO-ADMIN-{index:03d}",
            "created_at": DEMO_NOW - timedelta(days=index),
        }
        for index in range(1, 9)
    ]
    return {
        "notifications": notifications,
        "conversations": conversations,
        "messages": messages,
        "states": states,
        "documents": documents,
        "parents": parents,
        "admin_logs": admin_logs,
    }


async def _demo_request_ids(connection) -> list[int]:
    return list(
        (
            await connection.scalars(
                select(PurchaseRequest.request_id).where(
                    PurchaseRequest.request_no.like("DEMO-PR-%")
                )
            )
        ).all()
    )


async def _demo_employee_ids(connection) -> list[int]:
    return list(
        (
            await connection.scalars(
                select(Employee.employee_id).where(Employee.employee_no.like("DEMO-E%"))
            )
        ).all()
    )


async def _demo_supplier_ids(connection) -> list[int]:
    return list(
        (
            await connection.scalars(
                select(Supplier.supplier_id).where(
                    Supplier.unified_social_credit_code.like("DEMO-CREDIT-%")
                )
            )
        ).all()
    )


async def reset_demo(connection) -> None:
    request_ids = await _demo_request_ids(connection)
    legacy_request_ids = list(
        (
            await connection.scalars(
                select(PurchaseRequest.request_id).where(
                    PurchaseRequest.request_no.like("DEMO-HIST-%")
                )
            )
        ).all()
    )
    request_ids.extend(legacy_request_ids)
    employee_ids = await _demo_employee_ids(connection)
    supplier_ids = await _demo_supplier_ids(connection)
    conversation_ids = list(
        (
            await connection.scalars(
                select(AgentConversation.conversation_id).where(
                    AgentConversation.external_conversation_id.like("demo_conversation_%")
                )
            )
        ).all()
    )
    document_ids = list(
        (
            await connection.scalars(
                select(KnowledgeDocument.document_id).where(
                    KnowledgeDocument.document_id.like("demo_doc_%")
                )
            )
        ).all()
    )
    if conversation_ids:
        await connection.execute(
            delete(AgentSessionState).where(AgentSessionState.conversation_id.in_(conversation_ids))
        )
        await connection.execute(
            delete(AgentMessage).where(AgentMessage.conversation_id.in_(conversation_ids))
        )
        await connection.execute(
            delete(AgentConversation).where(AgentConversation.conversation_id.in_(conversation_ids))
        )
    if request_ids:
        await connection.execute(
            delete(NotificationOutbox).where(NotificationOutbox.request_id.in_(request_ids))
        )
        await connection.execute(
            delete(WarehouseReceipt).where(WarehouseReceipt.request_id.in_(request_ids))
        )
        await connection.execute(
            delete(SupplierBlacklist).where(SupplierBlacklist.source_request_id.in_(request_ids))
        )
        await connection.execute(
            delete(PurchaseExecution).where(PurchaseExecution.request_id.in_(request_ids))
        )
        await connection.execute(
            delete(PurchaseReview).where(PurchaseReview.request_id.in_(request_ids))
        )
        await connection.execute(
            delete(PurchaseOperationLog).where(PurchaseOperationLog.request_id.in_(request_ids))
        )
        await connection.execute(
            delete(PurchaseRequest).where(PurchaseRequest.request_id.in_(request_ids))
        )
    if employee_ids:
        await connection.execute(
            delete(AdminOperationLog).where(AdminOperationLog.action_token.like("DEMO-ADMIN-%"))
        )
        await connection.execute(
            delete(EmployeeRole).where(EmployeeRole.employee_id.in_(employee_ids))
        )
        await connection.execute(
            delete(EmployeeBuilding).where(EmployeeBuilding.employee_id.in_(employee_ids))
        )
        await connection.execute(
            delete(EmployeeExternalIdentity).where(
                EmployeeExternalIdentity.employee_id.in_(employee_ids)
            )
        )
        await connection.execute(delete(Employee).where(Employee.employee_id.in_(employee_ids)))
    if supplier_ids:
        await connection.execute(delete(Supplier).where(Supplier.supplier_id.in_(supplier_ids)))
    if document_ids:
        await connection.execute(
            delete(KnowledgeParent).where(KnowledgeParent.document_id.in_(document_ids))
        )
        await connection.execute(
            delete(KnowledgeDocument).where(KnowledgeDocument.document_id.in_(document_ids))
        )
    await connection.execute(
        delete(Building).where(Building.building_id.in_(DEMO_BUILDING_IDS))
    )


async def _master_data(connection) -> tuple[list[int], dict[str, int]]:
    shared_names = ["一号楼", "二号楼", "三号楼", "四号楼", "五号楼", "六号楼"]
    demo_names = ["七号楼", "八号楼", "九号楼"]
    statement = mysql_insert(Building).values(
        [
            {"building_id": building_id, "building_name": name, "status": True}
            for building_id, name in zip(DEMO_BUILDING_IDS, demo_names, strict=True)
        ]
    )
    await connection.execute(statement.on_duplicate_key_update(status=statement.inserted.status))
    buildings = (
        await connection.execute(
            select(Building.building_id, Building.building_name).where(
                Building.building_name.in_([*shared_names, *demo_names])
            )
        )
    ).all()
    building_map = {name: building_id for building_id, name in buildings}
    role_records = (
        await connection.execute(
            select(Role.role_id, Role.role_code).where(
                Role.role_code.in_([role.value for role in RoleCode])
            )
        )
    ).all()
    role_ids = {code: role_id for role_id, code in role_records}
    if set(role_ids) != {role.value for role in RoleCode}:
        raise RuntimeError("数据库缺少标准 Role 主数据，请先执行 migration/role seed")
    if not all(name in building_map for name in shared_names):
        raise RuntimeError("数据库缺少一号楼至六号楼主数据")
    return [building_map[name] for name in [*shared_names, *demo_names]], role_ids


async def seed_demo() -> None:
    async with engine.begin() as connection:
        await reset_demo(connection)
        building_ids, role_ids = await _master_data(connection)
        dataset = build_dataset(building_ids, role_ids)
        role_rows, building_rows = role_and_building_rows(role_ids, building_ids)
        dataset["blacklists"] = _blacklist_rows(dataset)
        support = _supporting_rows(dataset)
        await connection.execute(insert(Employee), dataset["employees"])
        await connection.execute(insert(EmployeeExternalIdentity), dataset["identities"])
        await connection.execute(insert(EmployeeRole), role_rows)
        await connection.execute(insert(EmployeeBuilding), building_rows)
        await connection.execute(insert(Supplier), dataset["suppliers"])
        await connection.execute(insert(PurchaseRequest), dataset["requests"])
        await connection.execute(insert(PurchaseReview), dataset["reviews"])
        await connection.execute(insert(PurchaseExecution), dataset["executions"])
        await connection.execute(insert(WarehouseReceipt), dataset["receipts"])
        await connection.execute(insert(SupplierBlacklist), dataset["blacklists"])
        await connection.execute(insert(PurchaseOperationLog), dataset["logs"])
        await connection.execute(insert(NotificationOutbox), support["notifications"])
        await connection.execute(insert(AgentConversation), support["conversations"])
        await connection.execute(insert(AgentMessage), support["messages"])
        await connection.execute(insert(AgentSessionState), support["states"])
        await connection.execute(insert(KnowledgeDocument), support["documents"])
        await connection.execute(insert(KnowledgeParent), support["parents"])
        await connection.execute(insert(AdminOperationLog), support["admin_logs"])


async def _counts(connection) -> dict[str, int]:
    request_ids = await _demo_request_ids(connection)
    employee_ids = await _demo_employee_ids(connection)
    supplier_ids = await _demo_supplier_ids(connection)
    conversation_ids = list(
        (
            await connection.scalars(
                select(AgentConversation.conversation_id).where(
                    AgentConversation.external_conversation_id.like("demo_conversation_%")
                )
            )
        ).all()
    )

    async def count(model, condition):
        return await connection.scalar(select(func.count()).select_from(model).where(condition))

    return {
        "employee": int(await count(Employee, Employee.employee_id.in_(employee_ids)) or 0),
        "employee_role": int(
            await count(EmployeeRole, EmployeeRole.employee_id.in_(employee_ids)) or 0
        ),
        "employee_building": int(
            await count(EmployeeBuilding, EmployeeBuilding.employee_id.in_(employee_ids)) or 0
        ),
        "supplier": int(await count(Supplier, Supplier.supplier_id.in_(supplier_ids)) or 0),
        "purchase_request": len(request_ids),
        "purchase_review": int(
            await count(PurchaseReview, PurchaseReview.request_id.in_(request_ids)) or 0
        ),
        "purchase_execution": int(
            await count(PurchaseExecution, PurchaseExecution.request_id.in_(request_ids)) or 0
        ),
        "warehouse_receipt": int(
            await count(WarehouseReceipt, WarehouseReceipt.request_id.in_(request_ids)) or 0
        ),
        "supplier_blacklist": int(
            await count(SupplierBlacklist, SupplierBlacklist.source_request_id.in_(request_ids))
            or 0
        ),
        "purchase_operation_log": int(
            await count(PurchaseOperationLog, PurchaseOperationLog.request_id.in_(request_ids)) or 0
        ),
        "notification_outbox": int(
            await count(NotificationOutbox, NotificationOutbox.request_id.in_(request_ids)) or 0
        ),
        "agent_conversation": len(conversation_ids),
        "agent_message": int(
            await count(AgentMessage, AgentMessage.conversation_id.in_(conversation_ids)) or 0
        ),
        "agent_session_state": int(
            await count(AgentSessionState, AgentSessionState.conversation_id.in_(conversation_ids))
            or 0
        ),
        "admin_operation_log": int(
            await count(AdminOperationLog, AdminOperationLog.action_token.like("DEMO-ADMIN-%")) or 0
        ),
        "knowledge_document": int(
            await count(KnowledgeDocument, KnowledgeDocument.document_id.like("demo_doc_%")) or 0
        ),
        "knowledge_parent": int(
            await count(KnowledgeParent, KnowledgeParent.document_id.like("demo_doc_%")) or 0
        ),
    }


async def verify_demo() -> dict[str, Any]:
    errors: list[str] = []
    async with engine.connect() as connection:
        request_ids = await _demo_request_ids(connection)
        counts = await _counts(connection)
        status_rows = (
            await connection.execute(
                select(PurchaseRequest.status, func.count())
                .where(PurchaseRequest.request_id.in_(request_ids))
                .group_by(PurchaseRequest.status)
            )
        ).all()
        profession_rows = (
            await connection.execute(
                select(PurchaseRequest.device_profession, func.count())
                .where(PurchaseRequest.request_id.in_(request_ids))
                .group_by(PurchaseRequest.device_profession)
            )
        ).all()
        statuses = dict(status_rows)
        professions = dict(profession_rows)
        if statuses != STATUS_COUNTS:
            errors.append(f"状态分布不符: {statuses}")
        if professions != PROFESSION_COUNTS:
            errors.append(f"专业分布不符: {professions}")
        if set(PROFESSION_COUNTS) != set(DEVICE_PROFESSIONS):
            errors.append("Synthetic Catalog 与 DEVICE_PROFESSIONS 不一致")
        expected_minimums = {
            "employee": 24,
            "supplier": 30,
            "purchase_request": 210,
            "purchase_review": 1,
            "purchase_execution": 1,
            "warehouse_receipt": 1,
            "supplier_blacklist": 10,
            "purchase_operation_log": 1,
            "notification_outbox": 20,
            "agent_conversation": 10,
            "agent_message": 30,
            "knowledge_document": 3,
            "knowledge_parent": 6,
        }
        for name, minimum in expected_minimums.items():
            if counts[name] < minimum:
                errors.append(f"{name} 数量不足: {counts[name]} < {minimum}")
        completed_without = int(
            await connection.scalar(
                select(func.count())
                .select_from(PurchaseRequest)
                .outerjoin(PurchaseExecution)
                .outerjoin(WarehouseReceipt)
                .where(
                    PurchaseRequest.request_id.in_(request_ids),
                    PurchaseRequest.status == "COMPLETED",
                    (PurchaseExecution.execution_id.is_(None))
                    | (WarehouseReceipt.receipt_id.is_(None)),
                )
            )
            or 0
        )
        pending_bad = int(
            await connection.scalar(
                select(func.count())
                .select_from(PurchaseRequest)
                .outerjoin(PurchaseExecution)
                .outerjoin(WarehouseReceipt)
                .where(
                    PurchaseRequest.request_id.in_(request_ids),
                    PurchaseRequest.status == "PENDING_WAREHOUSE",
                    (PurchaseExecution.execution_id.is_(None))
                    | (WarehouseReceipt.receipt_id.is_not(None)),
                )
            )
            or 0
        )
        draft_execution = int(
            await connection.scalar(
                select(func.count())
                .select_from(PurchaseRequest)
                .join(PurchaseExecution)
                .where(
                    PurchaseRequest.request_id.in_(request_ids), PurchaseRequest.status == "DRAFT"
                )
            )
            or 0
        )
        if completed_without:
            errors.append(f"COMPLETED 缺 Execution/Receipt: {completed_without}")
        if pending_bad:
            errors.append(f"PENDING_WAREHOUSE 关联错误: {pending_bad}")
        if draft_execution:
            errors.append(f"DRAFT 含 Execution: {draft_execution}")
        invalid_reviews = int(
            await connection.scalar(
                select(func.count())
                .select_from(PurchaseRequest)
                .outerjoin(PurchaseReview)
                .where(
                    PurchaseRequest.request_id.in_(request_ids),
                    ((PurchaseRequest.status == "DRAFT") & PurchaseReview.review_id.is_not(None))
                    | (
                        (PurchaseRequest.status == "PENDING_REVIEW")
                        & (PurchaseReview.review_status != "DRAFT")
                    )
                    | (
                        (PurchaseRequest.status == "REJECTED")
                        & (PurchaseReview.review_result != "REJECTED")
                    ),
                )
            )
            or 0
        )
        if invalid_reviews:
            errors.append(f"Review 与申请状态不一致: {invalid_reviews}")
        invalid_blacklist = int(
            await connection.scalar(
                select(func.count())
                .select_from(SupplierBlacklist)
                .join(
                    PurchaseExecution,
                    PurchaseExecution.request_id == SupplierBlacklist.source_request_id,
                )
                .where(
                    SupplierBlacklist.source_request_id.in_(request_ids),
                    SupplierBlacklist.supplier_id != PurchaseExecution.supplier_id,
                )
            )
            or 0
        )
        if invalid_blacklist:
            errors.append(f"黑名单 source_request 供应商不匹配: {invalid_blacklist}")
        multi_role = int(
            await connection.scalar(
                select(func.count()).select_from(
                    select(EmployeeRole.employee_id)
                    .where(EmployeeRole.employee_id.in_(await _demo_employee_ids(connection)))
                    .group_by(EmployeeRole.employee_id)
                    .having(func.count() > 1)
                    .subquery()
                )
            )
            or 0
        )
        scoped_manager = int(
            await connection.scalar(
                select(func.count())
                .select_from(EmployeeBuilding)
                .where(
                    EmployeeBuilding.employee_id.in_([8_100_002, 8_100_009, 8_100_010, 8_100_011])
                )
            )
            or 0
        )
        if multi_role < 3:
            errors.append("缺少 3 个多角色账号")
        if scoped_manager < 9:
            errors.append("楼长楼宇范围不完整")
        log_rows = (
            await connection.execute(
                select(
                    PurchaseOperationLog.request_id,
                    PurchaseOperationLog.operated_at,
                )
                .where(PurchaseOperationLog.request_id.in_(request_ids))
                .order_by(
                    PurchaseOperationLog.request_id,
                    PurchaseOperationLog.operated_at,
                    PurchaseOperationLog.log_id,
                )
            )
        ).all()
        timelines: dict[int, list[datetime]] = defaultdict(list)
        for request_id, operated_at in log_rows:
            timelines[request_id].append(operated_at)
        if any(times != sorted(times) for times in timelines.values()):
            errors.append("OperationLog 时间线非递增")
        # Recommendation patterns are verified from the same production-valid history definition.
        server_history = (
            await connection.execute(
                select(PurchaseRequest.brand, PurchaseRequest.model, PurchaseExecution.purchased_at)
                .join(PurchaseExecution)
                .where(
                    PurchaseRequest.request_id.in_(request_ids),
                    PurchaseRequest.device_profession == "服务器",
                    PurchaseRequest.status.in_(["PENDING_WAREHOUSE", "COMPLETED"]),
                )
            )
        ).all()
        all_rank = Counter((brand, model) for brand, model, _ in server_history).most_common()
        recent_rank = Counter(
            (brand, model)
            for brand, model, purchased_at in server_history
            if purchased_at >= DEMO_NOW - timedelta(days=60)
        ).most_common()
        if not all_rank or not recent_rank or all_rank[0][0] == recent_rank[0][0]:
            errors.append("服务器全历史/近2月推荐首位未形成差异")
        contract_rows = (
            await connection.execute(
                select(
                    PurchaseExecution.tax_rate,
                    PurchaseExecution.contract_contact_info_snapshot,
                    func.count(),
                )
                .where(PurchaseExecution.supplier_id == 8_200_005)
                .group_by(
                    PurchaseExecution.tax_rate,
                    PurchaseExecution.contract_contact_info_snapshot,
                )
            )
        ).all()
        contract_pattern = {
            (str(tax_rate), contact): count for tax_rate, contact, count in contract_rows
        }
        if contract_pattern != {
            ("13.00", "DEMO-CONTACT-A"): 6,
            ("9.00", "DEMO-CONTACT-B"): 2,
            ("13.00", "DEMO-CONTACT-C"): 1,
        }:
            errors.append(f"采购员推荐 6/2/1 模式不符: {contract_pattern}")
        risk_candidates = int(
            await connection.scalar(
                select(func.count())
                .select_from(PurchaseRequest)
                .join(PurchaseExecution)
                .where(
                    PurchaseRequest.request_id.in_(request_ids),
                    (PurchaseExecution.actual_unit_price > 100_000)
                    | (PurchaseRequest.quantity >= 300),
                )
            )
            or 0
        )
        if risk_candidates < 2:
            errors.append("风险异常样本不足")
        if counts["purchase_request"] != len(set(request_ids)):
            errors.append("DEMO request key 不唯一")
    if errors:
        raise RuntimeError("FULL DEMO VERIFY FAILED\n- " + "\n- ".join(errors))
    return {
        "counts": counts,
        "statuses": statuses,
        "professions": professions,
        "all_server_rank": all_rank[:5],
        "recent_server_rank": recent_rank[:5],
        "risk_candidates": risk_candidates,
    }


def _print_summary(report: dict[str, Any]) -> None:
    print("FULL DEMO DATASET READY")
    print("\nTables:")
    for name, count in report["counts"].items():
        print(f"  {name}: {count}")
    print("\nPurchase Status:")
    for name, count in report["statuses"].items():
        print(f"  {name}: {count}")
    print("\nDevice Profession:")
    for name, count in report["professions"].items():
        print(f"  {name}: {count}")
    print("\nRecommendation checkpoints:")
    print(f"  server all-time: {report['all_server_rank']}")
    print(f"  server recent-2-month: {report['recent_server_rank']}")
    print(f"  designed risk candidates: {report['risk_candidates']}")
    print("\nDemo Accounts:")
    for index, label in enumerate(
        [
            "演示需求人",
            "演示楼长A",
            "演示采购员",
            "演示仓管员",
            "演示管理员",
            "演示需求人兼楼长",
            "演示楼长兼采购员",
            "演示采购员兼仓管",
        ],
        1,
    ):
        print(f"  {label}: platform={DEMO_PLATFORM}, user=demo_user_{index:03d}")


async def main(*, reset: bool, verify: bool) -> None:
    if reset:
        async with engine.begin() as connection:
            await reset_demo(connection)
        print("DEMO namespace removed; TEST and non-DEMO rows were preserved.")
        return
    if not verify:
        await seed_demo()
    _print_summary(await verify_demo())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--reset", action="store_true", help="remove only the DEMO namespace")
    group.add_argument("--verify", action="store_true", help="verify the existing DEMO dataset")
    args = parser.parse_args()
    asyncio.run(main(reset=args.reset, verify=args.verify))
