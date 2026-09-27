"""
Проверка профиля на одной вакансии — без базы и Telegram.

    python scripts/try_profile.py "Technical Project Manager" < vacancy.txt
    python scripts/try_profile.py "Менеджер по продажам" --location "Москва" --format Офис < vacancy.txt

Описание вакансии — со стандартного ввода. Печатает тир, баллы и за что они начислены.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from filters import stopwords  # noqa: E402
from scoring import score_vacancy  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("title")
    ap.add_argument("--company", default="")
    ap.add_argument("--location", default="")
    ap.add_argument("--format", default="", help="Удалёнка / Гибрид / Офис")
    args = ap.parse_args()
    description = sys.stdin.read() if not sys.stdin.isatty() else ""

    vacancy = {"id": 0, "source": "manual", "title": args.title, "company": args.company,
               "location": args.location, "work_format": args.format, "description": description}
    passes = not stopwords.stop_role(args.title) and bool(stopwords._WHITELIST_RE.search(args.title))
    r = score_vacancy(vacancy)
    print(f"Фильтр заголовков: {'пропущена' if passes else 'отсеяна до скоринга'}")
    print(f"Тир {r.tier} ({r.action}), баллы {r.score}, архетип {r.archetype}, гео {r.geo_bucket}")
    for k, v in sorted(r.score_breakdown.items(), key=lambda kv: -abs(kv[1])):
        print(f"  {v:+4d}  {k}")
    print(r.reason)


if __name__ == "__main__":
    main()
