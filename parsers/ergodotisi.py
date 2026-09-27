"""
Парсер ergodotisi.com — борд вакансий Кипра (Кипр в списке стран релокации).

Листинг /en-CY/jobs?page=N — 20 ссылок /en-CY/jobs/<роль>-<id> на страницу;
роль видна в слаге, поэтому чужое отсеиваем до детального запроса.
Описание — первый блок .vacancy-description. Грекоязычные вакансии отсечёт
языковой фильтр: профилю нужен английский.
"""

from parsers._html_board import HtmlBoardParser


class ErgodotisiParser(HtmlBoardParser):
    source_name = "ergodotisi"
    channel = "global"

    base_url = "https://ergodotisi.com"
    list_urls = [f"https://ergodotisi.com/en-CY/jobs?page={n}" for n in range(1, 6)]
    href_pattern = r"/en-CY/jobs/[a-z0-9-]+-\d+"
    prefilter_by_slug = True
    title_selector = "h2"
    description_selectors = (".vacancy-description",)
    company_selector = "[class*=company]"
    max_vacancies = 25
