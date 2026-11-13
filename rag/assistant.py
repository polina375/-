from functools import lru_cache
import logging
from .llm import chat_json
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .recommender import recommend
from .retriever import Retriever
from .schemas import Response, Status, UserProfile
logging.basicConfig(level=logging.INFO)
NO_ANSWER_TEXT = ("В базе знаний «Альфа-Курса» я не нашёл ответа на этот вопрос. "
                  "Попробуйте переформулировать его или уточнить тему.")
CLARIFY_TEXT = "Расскажите чуть подробнее: о какой теме или задаче в бизнесе вы спрашиваете?"
ERROR_TEXT = "Сейчас не получается ответить. Попробуйте, пожалуйста, ещё раз чуть позже."


@lru_cache(maxsize=1)
def _retriever() -> Retriever:
    return Retriever()


def _profile_text(p: UserProfile | None) -> str:
    if not p:
        return ""
    fields = [("Стадия бизнеса", p.business_stage), ("Сфера", p.industry),
              ("Налоговый режим", p.tax_regime), ("Опыт", p.experience), ("Задача", p.goal)]
    return "\n".join(f"{k}: {v}" for k, v in fields if v)


def _build_query(text: str, history: list[dict] | None) -> str:
    """Короткая реплика («УСН») без контекста не ищется, поэтому добавляем прошлые реплики пользователя."""
    prev = [m["text"] for m in (history or []) if m.get("role") == "user"][-2:]
    return " ".join(prev + [text])


def _context_block(hit: dict) -> str:
    # Платные материалы: в LLM уходит только название, без содержания (ограничения 06 и 07)
    if hit["is_paid"]:
        return f'[ПЛАТНЫЙ материал, {hit["type"]}] {hit["title"]}'
    return f'[{hit["type"]}] chunk_id={hit["chunk_id"]} :: {hit["text"]}'


def answer(user_id: str, text: str, profile: UserProfile | None = None,
           history: list[dict] | None = None) -> Response:
    """history: [{"role": "user" | "assistant", "text": "..."}], необязательно."""
    retriever = _retriever()
    hits = retriever.search(_build_query(text, history), k=6)

    # Слабое совпадение с базой
    if not retriever.is_confident(hits):
        if len(text.split()) < 4:  # слишком короткий и расплывчатый запрос
            return Response(status=Status.CLARIFY, text=CLARIFY_TEXT)
        return Response(status=Status.NO_ANSWER, text=NO_ANSWER_TEXT)

    prompt = build_user_prompt(text, _profile_text(profile), [_context_block(h) for h in hits])
    try:
        data = chat_json(SYSTEM_PROMPT, prompt)
        status = Status(data.get("status", "no_answer"))
        reply = (data.get("text") or "").strip() or NO_ANSWER_TEXT
        used = set(data.get("used_chunk_ids") or [])

    except Exception as e:
        logging.exception("LLM error: %s", e)
        return Response(status=Status.NO_ANSWER, text=ERROR_TEXT)

    sources = sorted({
        h["title"]
        for h in hits
        if h["chunk_id"] in used and not h["is_paid"]
    })

    return Response(
        status=status,
        text=reply,
        materials=recommend(hits, profile, status),
        sources=sources,
    )