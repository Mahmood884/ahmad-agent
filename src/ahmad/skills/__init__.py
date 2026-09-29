"""
Skills Registry: ديناميكيات وقدرات يمكن تحميلها أثناء التشغيل.
"""
from typing import Protocol, Any

class Skill(Protocol):
    name: str
    description: str
    
    def execute(self, **kwargs: Any) -> dict:
        ...

class SkillsRegistry:
    def __init__(self):
        self._skills: dict[str, Skill] = {}
        
    def register(self, skill: Skill):
        self._skills[skill.name] = skill
        
    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)
        
    def list_all(self) -> list[dict]:
        return [{"name": s.name, "description": s.description} for s in self._skills.values()]

skills_registry = SkillsRegistry()
