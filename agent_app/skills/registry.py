from agent_app.skills.base import DomainSkill


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, DomainSkill] = {}
        self._routes: dict[str, str] = {}

    def register(self, skill: DomainSkill) -> None:
        descriptor = skill.descriptor
        if descriptor.skill_id in self._skills:
            raise ValueError(f"Skill already registered: {descriptor.skill_id}")
        if descriptor.supported_route in self._routes:
            raise ValueError(f"Route already registered: {descriptor.supported_route}")
        self._skills[descriptor.skill_id] = skill
        self._routes[descriptor.supported_route] = descriptor.skill_id

    def get(self, skill_id: str) -> DomainSkill:
        try:
            return self._skills[skill_id]
        except KeyError as exc:
            raise ValueError(f"Unknown skill: {skill_id}") from exc

    def resolve(self, route: str) -> DomainSkill:
        try:
            return self.get(self._routes[route])
        except KeyError as exc:
            raise ValueError(f"No skill registered for route: {route}") from exc
