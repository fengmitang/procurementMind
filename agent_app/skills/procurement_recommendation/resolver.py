from dataclasses import dataclass

from agent_app.schemas.backend import CurrentUserData
from agent_app.skills.procurement_recommendation.profiles import (
    PROFILE_BY_TYPE,
    RecommendationProfile,
)
from agent_app.skills.procurement_recommendation.schemas import RecommendationType


@dataclass(frozen=True, slots=True)
class RecommendationResolution:
    profile: RecommendationProfile | None
    explicit_type: RecommendationType | None
    clarification_message: str | None = None
    permission_denied: bool = False


class RecommendationProfileResolver:
    def resolve(
        self,
        message: str,
        current_user: CurrentUserData,
        *,
        request_status: str | None,
    ) -> RecommendationResolution:
        roles = {role.role_code for role in current_user.roles}
        explicit = self.explicit_type(message)
        if explicit is not None:
            profile = PROFILE_BY_TYPE[explicit]
            if profile.required_role in roles or "ADMIN" in roles:
                return RecommendationResolution(profile, explicit)
            alternatives = [
                candidate.recommendation_type.value
                for candidate in PROFILE_BY_TYPE.values()
                if candidate.required_role in roles
            ]
            alternative = (
                "可以为您参考历史采购记录推荐品牌和型号，是否需要？"
                if RecommendationType.BRAND_MODEL.value in alternatives
                else "请联系具有相应业务角色的同事发起该类推荐。"
            )
            return RecommendationResolution(
                None,
                explicit,
                f"您当前的角色权限不支持{self._type_label(explicit)}。{alternative}",
                permission_denied=True,
            )

        applicable = [
            profile for profile in PROFILE_BY_TYPE.values() if profile.required_role in roles
        ]
        if len(applicable) == 1:
            return RecommendationResolution(applicable[0], None)
        if len(applicable) > 1 and request_status:
            profile = self._profile_for_status(request_status)
            if profile and profile.required_role in roles:
                return RecommendationResolution(profile, None)
        return RecommendationResolution(
            None,
            None,
            "请说明需要哪类历史推荐：品牌型号、供应商、税率与合同联系方式，或历史入库位置。",
        )

    @staticmethod
    def explicit_type(message: str) -> RecommendationType | None:
        normalized = message.replace(" ", "")
        if "合同" in normalized or "税率" in normalized:
            return RecommendationType.PURCHASER_CONTRACT
        if any(term in normalized for term in ("仓库", "库位", "入库位置", "存放位置")):
            return RecommendationType.WAREHOUSE
        if "供应商" in normalized:
            return RecommendationType.SUPPLIER
        if any(term in normalized for term in ("品牌", "型号", "品牌型号")):
            return RecommendationType.BRAND_MODEL
        return None

    @staticmethod
    def _profile_for_status(status: str) -> RecommendationProfile | None:
        mapping = {
            "DRAFT": RecommendationType.BRAND_MODEL,
            "REJECTED": RecommendationType.BRAND_MODEL,
            "PENDING_REVIEW": RecommendationType.SUPPLIER,
            "PENDING_PURCHASE": RecommendationType.PURCHASER_CONTRACT,
            "PURCHASING": RecommendationType.PURCHASER_CONTRACT,
            "PENDING_WAREHOUSE": RecommendationType.WAREHOUSE,
        }
        recommendation_type = mapping.get(status)
        return PROFILE_BY_TYPE.get(recommendation_type) if recommendation_type else None

    @staticmethod
    def _type_label(value: RecommendationType) -> str:
        return {
            RecommendationType.BRAND_MODEL: "品牌型号推荐",
            RecommendationType.SUPPLIER: "供应商推荐",
            RecommendationType.PURCHASER_CONTRACT: "税率与合同联系方式推荐",
            RecommendationType.WAREHOUSE: "历史入库位置推荐",
        }[value]
