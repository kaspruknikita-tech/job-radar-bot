"""
Скоринг реальных вакансий из БД + превью поста до и после AI.
Запуск: poetry run python preview_score.py [N]
"""
import os
import sys
import re
from dotenv import load_dotenv
load_dotenv()

import database
from scoring import score_vacancy
from bot.templates import format_ru, format_global

SEP = "─" * 60
N = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def pick_vacancies(n: int) -> list[dict]:
    conn = database._get_connection()
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM vacancies
                WHERE source != 'hh.ru'
                  AND status IN ('new', 'pending', 'posted')
                  AND description IS NOT NULL
                  AND length(description) > 200
                ORDER BY parsed_at DESC
                LIMIT %s
            """, (n,))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def print_post(label: str, vacancy: dict, enrichment: dict | None) -> None:
    print(f"\n  [{label}]")
    fmt = format_ru if vacancy.get("channel") == "ru" else format_global
    text = strip_html(fmt(vacancy, enrichment=enrichment))
    for line in text.splitlines():
        if line.strip():
            print(f"  {line}")


vacancies = pick_vacancies(N)
if not vacancies:
    print("Нет подходящих вакансий в БД")
    sys.exit(0)

for v in vacancies:
    print(f"\n{SEP}")
    print(f"[{v['source']}] {v['title']} @ {v['company']}")
    print(f"id={v['id']}  channel={v['channel']}  status={v['status']}")
    print(SEP)

    print_post("ПОСТ БЕЗ AI", v, enrichment=None)

    print(f"\n  [SCORING...]")
    result = score_vacancy(v)

    print(f"  tier={result.tier}  score={result.score}/10  enrich={result.enrichment_used}")
    print(f"  visa={result.visa_sponsorship}  reloc={result.relocation_support}  remote={result.remote_policy}")
    print(f"  model={result.model_used}  latency={result.latency_ms}ms")
    print(f"  reason: {result.reason}")

    if result.post_enrichment:
        enrichment_dict = result.post_enrichment.model_dump()
        print_post("ПОСТ С AI", v, enrichment=enrichment_dict)
    else:
        print("\n  [ПОСТ С AI] — обогащение не потребовалось")

    print()
