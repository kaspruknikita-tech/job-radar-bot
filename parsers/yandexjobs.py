"""
Парсер yandex.ru/jobs — вакансии самого Яндекса.

API нет, JSON-LD на детальной тоже: берём SSR-разметку через HtmlBoardParser
(листинг по маскам → ссылки /jobs/vacancies/<slug> → блок main детальной).

Узкий источник (один работодатель), но это Москва/СПб с сильным TPM/Ops-потоком.
"""

from parsers._html_board import HtmlBoardParser
from user_profile import P

SEARCH_QUERIES = P.SEARCH_YANDEXJOBS  # правится в profile/profile.py


class YandexJobsParser(HtmlBoardParser):
    source_name = "yandex_jobs"
    channel = "ru"

    base_url = "https://yandex.ru"
    list_urls = [
        f"https://yandex.ru/jobs/vacancies?text={q.replace(' ', '+')}"
        for q in SEARCH_QUERIES
    ]
    href_pattern = r"/jobs/vacancies/[a-z0-9-]{4,}"
    title_selector = "h1"
    description_selectors = ("main",)
    max_vacancies = 40
