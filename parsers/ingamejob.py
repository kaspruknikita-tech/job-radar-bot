"""
Парсер ingamejob.com — вакансии в геймдеве (домен профиля), СНГ и Европа.

Листинг /en/jobs?page=N отдаёт ~30 ссылок /en/job/<роль>-<id> на страницу;
роль видна в слаге — отсеиваем чужое до детального запроса.
Описание — блок .job-view-container. robots.txt просит Crawl-delay: 5.
"""

from parsers._html_board import HtmlBoardParser


class IngamejobParser(HtmlBoardParser):
    source_name = "ingamejob"
    channel = "ru"

    base_url = "https://ingamejob.com"
    list_urls = [f"https://ingamejob.com/en/jobs?page={n}" for n in (1, 2, 3)]
    href_pattern = r"/en/job/[a-z0-9_.-]{4,}"
    prefilter_by_slug = True
    title_selector = "h1"
    description_selectors = (".job-view-container",)
    request_delay = 5.0  # Crawl-delay из robots.txt
    max_vacancies = 20
