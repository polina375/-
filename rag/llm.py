"""Обёртка над GigaChat. Интерфейс chat_json() не изменился."""
import json
import os
import re
import time

from gigachat import GigaChat

_client = None


def _get_client() -> GigaChat:
    global _client
    if _client is None:
        _client = GigaChat(
            credentials=os.environ["GIGACHAT_CREDENTIALS"],
            scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            model=os.getenv("GIGACHAT_MODEL", "GigaChat-2"),
            # у GigaChat сертификат Минцифры, которого нет в системном хранилище;
            # для хакатона проверку отключаем (см. примечание ниже)
            verify_ssl_certs=os.getenv("GIGACHAT_VERIFY_SSL", "false").lower() == "true",
            timeout=30,
        )
    return _client


def _extract_json(text: str) -> dict:
    """Достаёт JSON из ответа, даже если модель обернула его в ```-блок или добавила текст."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("В ответе модели нет JSON")
    return json.loads(match.group(0))


def chat_json(system: str, user: str, retries: int = 2) -> dict:
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = _get_client().chat({
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "max_tokens": 700,
            })
            return _extract_json(resp.choices[0].message.content)
        except Exception as e:  # сеть, лимиты, невалидный JSON
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"LLM недоступен или вернул невалидный ответ: {last_err}")