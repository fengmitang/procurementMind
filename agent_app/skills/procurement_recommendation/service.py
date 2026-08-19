from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

from agent_app.device_terms.service import DeviceTermSearchService
from agent_app.domain.device_catalog import get_device_catalog
from agent_app.skills.base import SkillDescriptor, SkillExecutionContext
from agent_app.skills.procurement_recommendation.profiles import RecommendationProfile
from agent_app.skills.procurement_recommendation.resolver import RecommendationProfileResolver
from agent_app.skills.procurement_recommendation.schemas import (
    ContractEvidenceData,
    ProductEvidenceData,
    PurchaserCandidateFields,
    RecommendationCandidate,
    RecommendationEvidence,
    RecommendationOutput,
    RecommendationProfileId,
    RecommendationQueryContext,
    RecommendationSkillResult,
    RequesterCandidateFields,
    SkillToolCall,
    SupplierCandidateFields,
    SupplierEvidenceData,
    WarehouseCandidateFields,
    WarehouseEvidenceData,
)
from agent_app.skills.procurement_recommendation.time_parser import parse_time_range


class ProcurementRecommendationSkill:
    descriptor = SkillDescriptor(
        skill_id="procurement_recommendation",
        version="1.0",
        description="角色感知的采购历史推荐",
        supported_route="RECOMMENDATION",
    )

    def __init__(self) -> None:
        self.resolver = RecommendationProfileResolver()
        self.device_term_search: DeviceTermSearchService | None = None

    def set_device_term_search(self, service: DeviceTermSearchService) -> None:
        self.device_term_search = service

    async def execute(self, context: SkillExecutionContext) -> RecommendationSkillResult:
        time_range = parse_time_range(context.message)
        calls: list[SkillToolCall] = []
        request_data: dict[str, Any] = {}
        async with context.mcp_client_factory(
            context.settings, context.identity, context.trace_id
        ) as client:
            if context.purchase_request_id is not None:
                response, call = await self._call(
                    client,
                    "get_purchase_request",
                    {"requirement_id": context.purchase_request_id},
                )
                calls.append(call)
                if response.success and isinstance(response.data, dict):
                    request_data = response.data

            resolution = self.resolver.resolve(
                context.message,
                context.current_user,
                request_status=(str(request_data.get("status")) if request_data else None),
            )
            query_context = await self._query_context(
                context.message,
                context.purchase_request_id,
                request_data,
                context.form_draft,
            )
            if resolution.profile is None:
                output = RecommendationOutput(
                    profile=None,
                    recommendation_type=resolution.explicit_type,
                    time_range=time_range,
                    query_context=query_context,
                    warnings=["PROFILE_PERMISSION_DENIED"] if resolution.permission_denied else [],
                    clarification_required=True,
                    clarification_message=resolution.clarification_message,
                )
                return RecommendationSkillResult(output=output, tool_calls=calls)

            missing_message = self._missing_query_message(resolution.profile, query_context)
            if missing_message:
                output = RecommendationOutput(
                    profile=resolution.profile.profile_id,
                    recommendation_type=resolution.profile.recommendation_type,
                    time_range=time_range,
                    query_context=query_context,
                    clarification_required=True,
                    clarification_message=missing_message,
                )
                return RecommendationSkillResult(output=output, tool_calls=calls)

            evidence, retrieval_calls, stages, warnings, ambiguity = await self._retrieve(
                client, resolution.profile, query_context, time_range
            )
            calls.extend(retrieval_calls)
            if ambiguity:
                output = RecommendationOutput(
                    profile=resolution.profile.profile_id,
                    recommendation_type=resolution.profile.recommendation_type,
                    time_range=time_range,
                    query_context=query_context,
                    evidence=evidence,
                    warnings=warnings,
                    retrieval_stages_used=stages,
                    clarification_required=True,
                    clarification_message=ambiguity,
                )
                return RecommendationSkillResult(output=output, tool_calls=calls)
            candidates = self._aggregate(resolution.profile, evidence)
            output = RecommendationOutput(
                profile=resolution.profile.profile_id,
                recommendation_type=resolution.profile.recommendation_type,
                time_range=time_range,
                query_context=query_context,
                candidates=candidates[: resolution.profile.candidate_limit],
                evidence=evidence,
                warnings=warnings,
                retrieval_stages_used=stages,
                no_result_reason=(
                    "未查询到相关历史采购记录，暂无可参考推荐。"
                    if not candidates
                    else None
                ),
            )
            return RecommendationSkillResult(output=output, tool_calls=calls)

    async def _query_context(
        self,
        message: str,
        requirement_id: int | None,
        request_data: dict[str, Any],
        form_draft: dict[str, Any] | None,
    ) -> RecommendationQueryContext:
        applicant = request_data.get("applicant_fields")
        applicant = applicant if isinstance(applicant, dict) else {}
        if form_draft:
            applicant = {**form_draft, **applicant}
        execution = request_data.get("purchase_execution")
        execution = execution if isinstance(execution, dict) else {}
        profession, device_name = self._extract_device(message)
        profession = profession or applicant.get("device_profession")
        device_name = device_name or applicant.get("device_name")
        resolved_names = [device_name] if isinstance(device_name, str) and device_name else []
        if profession and device_name and self.device_term_search is not None:
            lookup = await self.device_term_search.lookup(device_name, profession)
            if lookup.selected_names:
                resolved_names = lookup.selected_names[:5]
        brand = self._labeled_value(message, "品牌") or applicant.get("brand")
        model = self._labeled_value(message, "型号") or applicant.get("model")
        supplier_id = execution.get("supplier_id")
        supplier_name = execution.get("supplier_name")
        labeled_supplier = re.search(r"供应商(?:是|为|：|:)\s*([^，。；;]{2,80})", message)
        if labeled_supplier:
            supplier_name = labeled_supplier.group(1).strip()
            supplier_id = None
        return RecommendationQueryContext(
            requirement_id=requirement_id,
            device_profession=profession,
            device_name=device_name,
            resolved_device_names=resolved_names,
            brand=brand,
            model=model,
            supplier_id=supplier_id if isinstance(supplier_id, int) else None,
            supplier_name=supplier_name if isinstance(supplier_name, str) else None,
        )

    @staticmethod
    def _extract_device(message: str) -> tuple[str | None, str | None]:
        normalized = re.sub(r"\s+", "", message)
        catalog = get_device_catalog()
        canonical = [name for name in catalog.professions if name in normalized]
        typical = catalog.typical_matches(normalized)
        ambiguous = catalog.ambiguous_matches(normalized)
        if len(canonical) == 1:
            profession = canonical[0]
            # An ambiguous term may only refine the device name after the user has
            # independently supplied the canonical profession. It never establishes
            # the profession by itself.
            matched_terms = (*typical.get(profession, ()), *ambiguous.get(profession, ()))
            if matched_terms:
                return profession, max(matched_terms, key=len)
            return profession, profession
        if len(typical) == 1:
            profession, terms = next(iter(typical.items()))
            return profession, max(terms, key=len)
        return None, None

    @staticmethod
    def _labeled_value(message: str, label: str) -> str | None:
        match = re.search(rf"{label}(?:是|为|：|:)\s*([^，。；;]{{1,80}})", message)
        return match.group(1).strip() if match else None

    @staticmethod
    def _missing_query_message(
        profile: RecommendationProfile, query: RecommendationQueryContext
    ) -> str | None:
        if profile.profile_id is RecommendationProfileId.PURCHASER:
            if query.supplier_id is None and not query.supplier_name:
                return "请提供需要参考的供应商名称，或在采购单上下文中发起推荐。"
        elif not query.device_profession and not query.resolved_device_names:
            return "请提供需要参考的设备类型或设备名称。"
        return None

    async def _retrieve(self, client, profile, query, time_range):
        evidence: list[RecommendationEvidence] = []
        calls: list[SkillToolCall] = []
        stages_used: list[int] = []
        warnings: list[str] = []
        seen_refs: set[int] = set()
        seen_arguments: set[str] = set()
        ambiguity: str | None = None
        tool_name = profile.allowed_tools[0]
        for stage_number, stage_fields in enumerate(profile.retrieval_stages, start=1):
            arguments = self._stage_arguments(profile, stage_fields, query, time_range)
            signature = repr(sorted(arguments.items()))
            if signature in seen_arguments or not self._stage_has_subject(arguments):
                continue
            seen_arguments.add(signature)
            stages_used.append(stage_number)
            arguments["limit"] = profile.evidence_limit - len(evidence)
            response, call = await self._call(client, tool_name, arguments)
            calls.append(call)
            if not response.success:
                warnings.append(f"{tool_name}: {response.message}")
                break
            data = response.data if isinstance(response.data, dict) else {}
            ambiguous = data.get("ambiguous_suppliers")
            if isinstance(ambiguous, list) and len(ambiguous) > 1:
                names = "、".join(
                    f"{item.get('supplier_name')}（ID {item.get('supplier_id')}）"
                    for item in ambiguous
                    if isinstance(item, dict)
                )
                ambiguity = f"供应商名称对应多个主体：{names}。请确认具体供应商。"
                break
            items = data.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                reference_id = item.get("reference_id")
                if not isinstance(reference_id, int) or reference_id in seen_refs:
                    continue
                parsed = self._evidence(profile, item, stage_number, stage_fields)
                if parsed is not None:
                    seen_refs.add(reference_id)
                    evidence.append(parsed)
                if len(evidence) >= profile.evidence_limit:
                    break
            if len(evidence) >= profile.evidence_limit:
                break
        return evidence, calls, stages_used, warnings, ambiguity

    @staticmethod
    def _stage_has_subject(arguments: dict[str, Any]) -> bool:
        return any(
            arguments.get(key)
            for key in ("device_profession", "device_names", "supplier_id", "supplier_name")
        )

    @staticmethod
    def _stage_arguments(profile, fields, query, time_range) -> dict[str, Any]:
        source = query.model_dump(mode="json")
        arguments = {}
        for field in fields:
            value = source.get("resolved_device_names" if field == "device_names" else field)
            if value:
                arguments[field] = value
        prefix = (
            "received"
            if profile.profile_id is RecommendationProfileId.WAREHOUSE_MANAGER
            else "purchased"
        )
        if time_range.start:
            arguments[f"{prefix}_from"] = time_range.start.isoformat()
        if time_range.end:
            arguments[f"{prefix}_to"] = time_range.end.isoformat()
        return arguments

    @staticmethod
    def _evidence(profile, item, stage, basis) -> RecommendationEvidence | None:
        occurred_key = (
            "received_at"
            if profile.profile_id is RecommendationProfileId.WAREHOUSE_MANAGER
            else "purchased_at"
        )
        occurred = item.get(occurred_key)
        if not isinstance(occurred, str):
            return None
        if profile.profile_id is RecommendationProfileId.REQUESTER:
            data = ProductEvidenceData(
                device_profession=item.get("device_profession"),
                device_name=item.get("device_name"),
                brand=item.get("brand"),
                model=item.get("model"),
            )
        elif profile.profile_id is RecommendationProfileId.BUILDING_MANAGER:
            data = SupplierEvidenceData(
                supplier_id=item["supplier_id"],
                supplier_name=item["supplier_name"],
                supplier_contact_name=item.get("supplier_contact_name"),
                supplier_contact_info=item.get("supplier_contact_info"),
                actual_unit_price=item.get("actual_unit_price"),
                contract_type=item.get("contract_type"),
                payment_method=item.get("payment_method"),
                blacklist_status=item["blacklist_status"],
                blacklist_history_count=item.get("blacklist_history_count", 0),
            )
        elif profile.profile_id is RecommendationProfileId.PURCHASER:
            data = ContractEvidenceData(
                supplier_id=item["supplier_id"],
                supplier_name=item["supplier_name"],
                tax_rate=item.get("tax_rate"),
                contract_contact_info=item.get("contract_contact_info"),
            )
        else:
            data = WarehouseEvidenceData(
                device_profession=item.get("device_profession"),
                device_name=item.get("device_name"),
                warehouse_location=item["warehouse_location"],
                received_quantity=item["received_quantity"],
            )
        return RecommendationEvidence(
            reference_id=item["reference_id"],
            source_tool=profile.allowed_tools[0],
            occurred_at=datetime.fromisoformat(occurred),
            retrieval_stage=stage,
            match_basis=list(basis),
            data=data,
        )

    def _aggregate(
        self, profile: RecommendationProfile, evidence: list[RecommendationEvidence]
    ) -> list[RecommendationCandidate]:
        grouped: dict[tuple, list[RecommendationEvidence]] = defaultdict(list)
        for item in evidence:
            key = self._candidate_key(profile.profile_id, item)
            if key is not None:
                grouped[key].append(item)
        candidates = [
            self._candidate(profile.profile_id, key, items) for key, items in grouped.items()
        ]
        return sorted(
            candidates,
            key=lambda item: (
                item.best_retrieval_stage,
                -item.evidence_count,
                -item.last_seen_at.timestamp(),
                item.candidate_id,
            ),
        )

    @staticmethod
    def _candidate_key(profile_id, evidence):
        data = evidence.data
        if profile_id is RecommendationProfileId.REQUESTER:
            return (data.brand, data.model) if data.brand or data.model else None
        if profile_id is RecommendationProfileId.BUILDING_MANAGER:
            return (data.supplier_id,)
        if profile_id is RecommendationProfileId.PURCHASER:
            return (
                (data.tax_rate, data.contract_contact_info)
                if data.tax_rate is not None or data.contract_contact_info
                else None
            )
        return (data.warehouse_location,)

    @staticmethod
    def _candidate(profile_id, key, items):
        ordered = sorted(items, key=lambda item: item.occurred_at, reverse=True)
        latest = ordered[0]
        warnings: list[str] = []
        if profile_id is RecommendationProfileId.REQUESTER:
            data = latest.data
            fields = RequesterCandidateFields(brand=data.brand, model=data.model)
            title = " / ".join(value for value in (data.brand, data.model) if value)
        elif profile_id is RecommendationProfileId.BUILDING_MANAGER:
            data = latest.data
            if data.blacklist_status == "BLACKLISTED":
                warnings.append("当前处于有效黑名单")
            elif data.blacklist_history_count:
                warnings.append("存在历史黑名单记录，当前已解除")
            fields = SupplierCandidateFields(
                supplier_id=data.supplier_id,
                supplier_name=data.supplier_name,
                supplier_contact_name=data.supplier_contact_name,
                supplier_contact_info=data.supplier_contact_info,
                reference_unit_price=data.actual_unit_price,
                contract_type=data.contract_type,
                payment_method=data.payment_method,
                blacklist_status=data.blacklist_status,
                blacklist_history_count=data.blacklist_history_count,
            )
            title = data.supplier_name
        elif profile_id is RecommendationProfileId.PURCHASER:
            data = latest.data
            fields = PurchaserCandidateFields(
                supplier_id=data.supplier_id,
                supplier_name=data.supplier_name,
                tax_rate=data.tax_rate,
                contract_contact_info=data.contract_contact_info,
            )
            title = f"{data.supplier_name}历史参考组合"
        else:
            data = latest.data
            fields = WarehouseCandidateFields(warehouse_location=data.warehouse_location)
            title = data.warehouse_location
        return RecommendationCandidate(
            candidate_id="|".join("" if value is None else str(value) for value in key),
            title=title,
            fields=fields,
            evidence_count=len(items),
            last_seen_at=latest.occurred_at,
            best_retrieval_stage=min(item.retrieval_stage for item in items),
            evidence_refs=[item.reference_id for item in ordered],
            warnings=warnings,
        )

    @staticmethod
    async def _call(client, name: str, arguments: dict[str, Any]):
        started = time.perf_counter()
        response = await client.call_tool(name, arguments)
        call = SkillToolCall(
            name=name,
            arguments=arguments,
            success=response.success,
            code=response.code,
            source=response.source,
            trace_id=response.trace_id,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            data=response.data if isinstance(response.data, dict) else None,
        )
        return response, call


def render_recommendation(output: RecommendationOutput) -> str:
    if output.clarification_required:
        return output.clarification_message or "请补充推荐类型或查询对象。"
    if not output.candidates:
        return output.no_result_reason or "未查询到相关历史采购记录，暂无可参考推荐。"
    scope = output.time_range.description or "全部可见历史记录"
    lines = [f"根据{scope}整理了以下历史参考："]
    for index, candidate in enumerate(output.candidates, start=1):
        fields = candidate.fields
        details: list[str] = []
        if isinstance(fields, RequesterCandidateFields):
            if fields.brand:
                details.append(f"品牌：{fields.brand}")
            if fields.model:
                details.append(f"型号：{fields.model}")
        elif isinstance(fields, SupplierCandidateFields):
            details.append(f"供应商：{fields.supplier_name}")
            if fields.reference_unit_price is not None:
                details.append(f"最近真实采购单价：{fields.reference_unit_price}")
            if fields.supplier_contact_name:
                details.append(f"联系人：{fields.supplier_contact_name}")
            if fields.supplier_contact_info:
                details.append(f"联系方式：{fields.supplier_contact_info}")
            if fields.contract_type:
                details.append(f"合同类型：{fields.contract_type}")
            if fields.payment_method:
                details.append(f"付款方式：{fields.payment_method}")
        elif isinstance(fields, PurchaserCandidateFields):
            if fields.tax_rate is not None:
                details.append(f"历史税率：{fields.tax_rate}%")
            if fields.contract_contact_info:
                details.append(f"合同联系方式：{fields.contract_contact_info}")
        else:
            details.append(f"历史入库位置：{fields.warehouse_location}")
        details.append(f"历史依据：{candidate.evidence_count} 条")
        if candidate.warnings:
            details.append("；".join(candidate.warnings))
        lines.append(f"{index}. {candidate.title}（{'；'.join(details)}）")
    lines.append("以上仅为历史记录参考，不代表当前审批、采购、库存或最优选择结论。")
    return "\n".join(lines)
