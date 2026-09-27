"""
Парсер vseti.app — русскоязычный борд вакансий (сайт на Webflow).

Листинг рисуется скриптом, но sitemap.xml отдаёт ~860 ссылок /vakansii/<id>.
Идентификаторы числовые, роль из URL не видна — поэтому карточки качаем
порциями по max_vacancies за цикл, а отклонённые запоминает is_known.

Детальная: название во втором h1 (.heading-9), описание в .w-richtext,
а город, формат и компания — в <title>:
«Вакансия Project Manager, Казань, офис, работа в компании Kitegroup».
"""

import re

from bs4 import BeautifulSoup

from parsers._html_board import HtmlBoardParser

_COMPANY_RE = re.compile(r",\s*работа в компании\s+(?P<company>.+)$")
_TITLE_PREFIX = "Вакансия "


def _work_format(part: str) -> str | None:
    p = part.lower()
    if p.startswith(("удалён", "удален")):
        return "Удалёнка"
    if p.startswith("гибрид"):
        return "Гибрид"
    if p.startswith("офис"):
        return "Офис"
    return None


def parse_page_title(text: str) -> dict:
    """Разбирает <title> карточки vseti. Реальные варианты:
    «Вакансия X, Удалённо, работа в компании Y»
    «Вакансия X, Удалённо (Мир), работа в компании Y»
    «Вакансия X, Москва, гибрид или удалённо (РФ), работа в компании Y»
    В названии роли тоже бывают запятые, поэтому режем с конца.
    """
    out = {"company": "", "location": "", "work_format": None}
    m = _COMPANY_RE.search(text)
    if not m or not text.startswith(_TITLE_PREFIX):
        return out
    out["company"] = m.group("company").strip()
    parts = text[len(_TITLE_PREFIX):m.start()].split(", ")
    if len(parts) < 2:
        return out
    last = parts[-1].strip()
    fmt = _work_format(last)
    if fmt:
        out["work_format"] = fmt
        # «Удалённо (Мир)» — география в скобках
        bracket = re.search(r"\(([^)]+)\)", last)
        if len(parts) >= 3 and not _work_format(parts[-2]):
            out["location"] = parts[-2].strip()
        elif bracket:
            out["location"] = bracket.group(1)
    else:
        out["location"] = last
    return out


class VsetiParser(HtmlBoardParser):
    source_name = "vseti"
    channel = "ru"

    base_url = "https://www.vseti.app"
    sitemap_urls = ["https://www.vseti.app/sitemap.xml"]
    sitemap_job_pattern = r"/vakansii/"
    title_selector = "h1.heading-9"
    description_selectors = (".w-richtext",)
    max_vacancies = 40

    def _from_html(self, soup: BeautifulSoup, url: str) -> dict | None:
        v = super()._from_html(soup, url)
        if not v:
            return None
        page_title = soup.select_one("title")
        if page_title:
            v.update(parse_page_title(page_title.get_text(strip=True)))
        return v
