"""
Превью 150 последних вакансий, которые прошли бы на модерацию.
Запуск: poetry run python preview_batch.py
"""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(__file__))

import psycopg2
import psycopg2.extras
from bot.templates import format_ru, format_global
from bot.moderator import _scoring_footer, _row_to_scoring_result

_STRIP_TAGS = re.compile(r"<[^>]+>")
_SEP = "─" * 50


def _plain(text: str) -> str:
    return _STRIP_TAGS.sub("", text)


def main():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        from dotenv import load_dotenv
        load_dotenv()
        url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL не задан в .env")
        sys.exit(1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Последние 150 вакансий + их последний скор
    cur.execute("""
        SELECT
            v.id, v.title, v.company, v.location, v.work_format,
            v.salary_min, v.salary_max, v.currency, v.url, v.channel, v.source,
            v.description, v.snippet, v.status,
            s.tier, s.action, s.score, s.visa_sponsorship, s.relocation_support,
            s.remote_policy, s.experience_level, s.reason,
            s.verbatim_evidence, s.pre_filter_blocked, s.salary_min AS s_sal_min,
            s.salary_max AS s_sal_max, s.salary_currency, s.score_breakdown,
            s.post_enrichment
        FROM vacancies v
        LEFT JOIN LATERAL (
            SELECT * FROM vacancy_scores vs
            WHERE vs.vacancy_id = v.id
            ORDER BY vs.scored_at DESC LIMIT 1
        ) s ON TRUE
        ORDER BY v.id DESC
        LIMIT 150
    """)
    rows = cur.fetchall()
    conn.close()

    shown = 0
    skipped = 0
    errors = []

    for row in rows:
        tier = row.get("tier")
        action = row.get("action")

        # Пропускаем tier C и явный skip
        if tier == "C" or action == "skip":
            skipped += 1
            continue

        vacancy = {
            "id": row["id"],
            "title": row["title"],
            "company": row["company"],
            "location": row["location"],
            "work_format": row["work_format"],
            "salary_min": row["salary_min"],
            "salary_max": row["salary_max"],
            "currency": row["currency"],
            "url": row["url"] or "https://example.com",
            "channel": row["channel"],
            "source": row["source"],
            "description": row["description"],
            "snippet": row["snippet"],
        }

        scoring_result = None
        if tier:
            try:
                scoring_result = _row_to_scoring_result(dict(row), row["id"])
            except Exception as e:
                errors.append(f"id={row['id']}: {e}")

        try:
            if vacancy["channel"] == "ru":
                text = format_ru(vacancy, enrichment=scoring_result.post_enrichment.model_dump() if (scoring_result and scoring_result.post_enrichment) else None)
            else:
                text = format_global(vacancy, enrichment=scoring_result.post_enrichment.model_dump() if (scoring_result and scoring_result.post_enrichment) else None)

            if scoring_result:
                text += _scoring_footer(scoring_result)
        except Exception as e:
            errors.append(f"id={row['id']} format error: {e}")
            continue

        shown += 1
        status_mark = f"[{row['status']}]" if row["status"] != "new" else ""
        print(f"\n{_SEP}")
        print(f"#{row['id']} {row['source']} {status_mark}")
        print(_plain(text))

    print(f"\n{_SEP}")
    print(f"Показано: {shown}  |  Пропущено (tier C/skip): {skipped}")
    if errors:
        print(f"\nОшибки ({len(errors)}):")
        for e in errors[:10]:
            print(f"  {e}")


if __name__ == "__main__":
    main()
