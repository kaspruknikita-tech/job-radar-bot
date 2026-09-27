"""
Парсер hitmarker.net — вакансии в геймдеве и киберспорте (домен профиля).

Листинг отдаёт ссылки /jobs/<slug>, на детальной есть JSON-LD JobPosting —
описание и дату берём оттуда.
"""

from parsers._html_board import HtmlBoardParser
from user_profile import P

SEARCH_QUERIES = P.SEARCH_HITMARKER  # правится в profile/profile.py


class HitmarkerParser(HtmlBoardParser):
    source_name = "hitmarker"
    channel = "global"

    base_url = "https://hitmarker.net"
    list_urls = [
        f"https://hitmarker.net/jobs?search={q.replace(' ', '+')}"
        for q in SEARCH_QUERIES
    ]
    href_pattern = r"/jobs/[a-z0-9-]{6,}"
    max_vacancies = 40
