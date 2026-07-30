from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserRole:
    role_id: int
    role_code: str
    role_name: str


@dataclass(frozen=True, slots=True)
class UserBuilding:
    building_id: int
    building_name: str
    is_primary: bool


@dataclass(frozen=True, slots=True)
class CurrentUser:
    employee_id: int
    employee_no: str | None
    name: str
    mobile: str | None
    platform_type: str
    platform_user_id: str
    roles: tuple[UserRole, ...]
    buildings: tuple[UserBuilding, ...]

    @property
    def role_codes(self) -> frozenset[str]:
        return frozenset(role.role_code for role in self.roles)

    @property
    def building_ids(self) -> frozenset[int]:
        return frozenset(building.building_id for building in self.buildings)

    def has_any_role(self, *role_codes: str) -> bool:
        return bool(self.role_codes.intersection(role_codes))

    def belongs_to_building(self, building_id: int) -> bool:
        return "ADMIN" in self.role_codes or building_id in self.building_ids
