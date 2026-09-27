"""
Парсер jobs.devby.io — белорусский IT-борд, русскоязычный.

API и JSON-LD нет: листинг отдаёт ссылки /vacancies/<id>, описание лежит
в блоке .vacancy__body детальной страницы.
"""

from parsers._html_board import HtmlBoardParser


class DevbyParser(HtmlBoardParser):
    source_name = "devby"
    channel = "ru"

    base_url = "https://jobs.devby.io"
    list_urls = ["https://jobs.devby.io/"]
    href_pattern = r"/vacancies/\d+"
    title_selector = "h1"
    description_selectors = (".vacancy__body", "[class*=vacancy__body]")
    max_vacancies = 40
