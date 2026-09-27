"""
Парсер workwithindies.com — вакансии инди-студий (GameDev-домен профиля).

Листинг подгружается скриптом, но карта сайта отдаёт ~1300 ссылок
/careers/<студия>-<роль>. Роль есть в слаге — фильтруем до детальной.
JSON-LD у источника нет, описание берём из блока с классом description.
"""

from parsers._html_board import HtmlBoardParser


class WorkWithIndiesParser(HtmlBoardParser):
    source_name = "workwithindies"
    channel = "global"

    base_url = "https://www.workwithindies.com"
    sitemap_urls = ["https://www.workwithindies.com/sitemap.xml"]
    sitemap_job_pattern = r"/careers/.+"
    prefilter_by_slug = True
    title_selector = "h1"
    description_selectors = ("[class*=description]", "main")
    max_vacancies = 30
