"""Подбор материалов по найденным фрагментам с учётом профиля.
Правила простые и объяснимые, их удобно описать в презентации."""
from .schemas import Material, Status, UserProfile

# Какие типы материалов лучше подходят под опыт/цель пользователя
TYPE_BOOST_BY_EXPERIENCE = {
    "novice": {"course": 0.15, "article": 0.10, "glossary": 0.05},
    "experienced": {"document": 0.15, "calculator": 0.15, "webinar": 0.05},
}
GOAL_KEYWORDS = {
    "document": ("шаблон", "образец", "договор", "документ", "бланк"),
    "calculator": ("посчитать", "рассчитать", "калькулятор"),
    "course": ("научиться", "с нуля", "обучение", "курс"),
}


def _boost(hit: dict, profile: UserProfile | None) -> float:
    if not profile:
        return 0.0
    boost = 0.0
    exp = (profile.experience or "").lower()
    boost += TYPE_BOOST_BY_EXPERIENCE.get(exp, {}).get(hit["type"], 0.0)
    goal = (profile.goal or "").lower()
    for etype, words in GOAL_KEYWORDS.items():
        if hit["type"] == etype and any(w in goal for w in words):
            boost += 0.2
    return boost


def _why(hit: dict) -> str:
    # Для платных ничего не пересказываем (ограничение 06): только польза и приглашение перейти
    if hit["is_paid"]:
        return f"Подробно разбирает эту тему. Загляните на страницу материала, чтобы узнать детали."
    return "Бесплатный материал по теме вашего вопроса."


def recommend(hits: list[dict], profile: UserProfile | None, status: Status,
              max_free: int = 2, max_paid: int = 1) -> list[Material]:
    if status == Status.NO_ANSWER or not hits:
        return []

    top_rrf = max(h["rrf"] for h in hits) or 1.0
    best: dict[str, tuple[float, dict]] = {}
    for h in hits:
        score = h["rrf"] / top_rrf + _boost(h, profile)
        if h["doc_id"] not in best or score > best[h["doc_id"]][0]:
            best[h["doc_id"]] = (score, h)

    ranked = sorted(best.values(), key=lambda x: -x[0])
    free = [h for _, h in ranked if not h["is_paid"]][:max_free]
    paid = [h for _, h in ranked if h["is_paid"]][:max_paid]

    return [
        Material(id=h["doc_id"], title=h["title"], entity_type=h["type"],
                 is_paid=h["is_paid"], url=h["url"], why=_why(h))
        for h in free + paid
    ]