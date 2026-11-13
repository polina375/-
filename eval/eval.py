"""Запуск: python -m eval.eval"""
import json
from pathlib import Path

from rag.assistant import answer, _retriever
from rag.schemas import UserProfile

CASES = json.loads((Path(__file__).parent / "test_cases.json").read_text(encoding="utf-8"))


def main():
    known_urls = {c["url"] for c in _retriever().chunks if c["url"]}
    rows, ok_status, kw_total, kw_ok, bad_links = [], 0, 0, 0, 0

    for i, case in enumerate(CASES):
        profile = UserProfile(**case["profile"]) if case.get("profile") else None
        resp = answer(f"eval-{i}", case["q"], profile)

        status_ok = resp.status.value == case["expect_status"]
        ok_status += status_ok

        kw_note = "-"
        if case.get("expect_keywords"):
            kw_total += 1
            titles = " ".join(m.title.lower() for m in resp.materials)
            found = any(k in titles for k in case["expect_keywords"])
            kw_ok += found
            kw_note = "да" if found else "нет"

        bad = [m.url for m in resp.materials if m.url and m.url not in known_urls]
        bad_links += len(bad)

        rows.append(f'| {case["q"]} | {case["expect_status"]} | {resp.status.value} | '
                    f'{"да" if status_ok else "нет"} | {kw_note} | {len(bad)} |')

    n = len(CASES)
    report = [
        "# Результаты eval", "",
        f"- Верный статус ответа: **{ok_status}/{n}** ({ok_status / n:.0%})",
        f"- Нужный материал в рекомендациях: **{kw_ok}/{kw_total}**" if kw_total else "",
        f"- Выдуманные ссылки: **{bad_links}**", "",
        "| Вопрос | Ожидалось | Получено | Статус верен | Материал найден | Левые ссылки |",
        "|---|---|---|---|---|---|",
        *rows,
    ]
    out = Path(__file__).parent / "results.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()