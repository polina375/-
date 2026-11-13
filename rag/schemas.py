from enum import Enum
from pydantic import BaseModel, Field


class Status(str, Enum):
    ANSWERED = "answered"    # ответ найден в базе
    CLARIFY = "clarify"      # вопрос неясный, задаём уточнение
    NO_ANSWER = "no_answer"  # в базе ответа нет


class UserProfile(BaseModel):
    """Профиль собирает Участник 1 (Telegram-часть), все поля необязательные."""
    business_stage: str | None = None   # idea | launched | growing
    industry: str | None = None
    tax_regime: str | None = None       # УСН, патент, НПД ...
    experience: str | None = None       # novice | some | experienced
    goal: str | None = None             # текущая задача


class Material(BaseModel):
    id: str
    title: str
    entity_type: str                    # course | article | document | webinar | podcast | glossary | calculator
    is_paid: bool
    url: str | None = None
    why: str = ""                       # 1 фраза о пользе (для платных — без подробностей содержания)


class Response(BaseModel):
    status: Status
    text: str                           # текст ответа или уточняющий вопрос
    materials: list[Material] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)  # id/названия найденных фрагментов