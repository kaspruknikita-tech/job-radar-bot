"""
Общая механика HTML-бордов без публичного API.

Наследник задаёт список URL листингов, шаблон ссылки на вакансию и (если нет
JSON-LD) селекторы детальной страницы. Дальше всё одинаково:
листинг → ссылки → детальная → JSON-LD JobPosting, иначе селекторы.

Так устроены hitmarker, devby и yandex-jobs — отличаются только конфигом.
"""

import json
import logging
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from filters.stopwords import apply_filters
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def find_job_posting(soup: BeautifulSoup) -> dict | None:
    """JSON-LD блок с @type=JobPosting (учитывает @graph и массивы)."""
    for el in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if not el.string:
            continue
        try:
            d = json.loads(el.string)
        except json.JSONDecodeError:
            continue
        items = d.get("@graph", [d]) if isinstance(d, dict) else d
        for it in items if isinstance(items, list) else [items]:
            if isinstance(it, dict) and it.get("@type") == "JobPosting":
                return it
    return None


def _slug_title(url: str) -> str:
    """Роль из URL: .../posao/Weekend-Backend-Engineer/... → «Weekend Backend Engineer»."""
    parts = [p for p in url.rstrip("/").split("/") if p]
    slug = parts[-1] if parts else ""
    if slug.isdigit() and len(parts) > 1:
        slug = parts[-3] if len(parts) > 2 else parts[-2]
    return re.sub(r"[-_]+", " ", slug)


def ld_location(d: dict) -> str:
    loc = d.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return ""
    addr = loc.get("address")
    if not isinstance(addr, dict):
        return ""
    parts = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
    return ", ".join(p for p in parts if isinstance(p, str) and p.strip())


class HtmlBoardParser(BaseParser):
    """Борд без API: листинги (или sitemap) → карточки вакансий."""

    base_url: str = ""
    list_urls: list[str] = []
    href_pattern: str = ""          # regex ссылки на вакансию
    # Альтернатива листингам: карты сайта со ссылками на вакансии.
    sitemap_urls: list[str] = []
    sitemap_job_pattern: str = ""
    # Роль обычно видна в самом URL — отсеиваем по слагу до детального запроса.
    prefilter_by_slug: bool = False
    title_selector: str = "h1"
    description_selectors: tuple[str, ...] = ()
    company_selector: str = ""
    request_delay: float = 0.5
    request_timeout: int = 20
    max_vacancies: int = 60

    def fetch(self) -> list[dict]:
        urls = self._sitemap_urls() if self.sitemap_urls else self._listing_urls()

        if self.prefilter_by_slug:
            before = len(urls)
            urls = [u for u in urls if apply_filters({"title": _slug_title(u)})]
            logger.info("[%s] По слагу отсеяно %d из %d", self.source_name,
                        before - len(urls), before)

        urls = [u for u in urls if not self.is_known(u)]
        out: list[dict] = []
        for url in urls[:self.max_vacancies]:
            v = self._detail(url)
            # Нерелевантные тоже отдаём: планировщик отклонит и сохранит их,
            # и is_known не даст качать эти карточки в следующих циклах.
            if v:
                out.append(v)
        logger.info("[%s] Новых карточек: %d", self.source_name, len(out))
        return out

    def _sitemap_urls(self) -> list[str]:
        job_re = re.compile(self.sitemap_job_pattern)
        urls: list[str] = []
        seen: set[str] = set()
        for sm in self.sitemap_urls:
            xml = self._get(sm)
            if not xml:
                continue
            for loc in re.findall(r"<loc>([^<]+)</loc>", xml):
                if job_re.search(loc) and loc not in seen:
                    seen.add(loc)
                    urls.append(loc)
        logger.info("[%s] Ссылок в sitemap: %d", self.source_name, len(urls))
        # Свежие вакансии в картах обычно в конце — начинаем с них.
        urls.reverse()
        return urls

    def _listing_urls(self) -> list[str]:
        href_re = re.compile(self.href_pattern)
        urls: list[str] = []
        seen: set[str] = set()

        for list_url in self.list_urls:
            html = self._get(list_url)
            if not html:
                continue
            for m in href_re.finditer(html):
                full = urljoin(self.base_url, m.group(0))
                if full not in seen:
                    seen.add(full)
                    urls.append(full)

        logger.info("[%s] Ссылок в листингах: %d", self.source_name, len(urls))
        return urls

    def _get(self, url: str) -> str | None:
        try:
            time.sleep(self.request_delay)
            resp = requests.get(url, headers=_HEADERS, timeout=self.request_timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException:
            logger.debug("[%s] не открылась %s", self.source_name, url)
            return None

    def _detail(self, url: str) -> dict | None:
        html = self._get(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")

        posting = find_job_posting(soup)
        if posting:
            return self._from_ld(posting, url)
        return self._from_html(soup, url)

    def _from_ld(self, d: dict, url: str) -> dict | None:
        title = (d.get("title") or "").strip()
        if not title:
            return None
        org = d.get("hiringOrganization")
        company = (org.get("name") or "").strip() if isinstance(org, dict) else ""
        return {
            "external_id": url,
            "title": title,
            "company": company,
            "salary_min": None,
            "salary_max": None,
            "currency": None,
            "location": ld_location(d),
            "work_format": None,
            "url": url,
            "description": d.get("description") or "",
            "published_at": d.get("datePosted"),
        }

    def _from_html(self, soup: BeautifulSoup, url: str) -> dict | None:
        title_el = soup.select_one(self.title_selector)
        if not title_el:
            return None

        description = ""
        for sel in self.description_selectors:
            el = soup.select_one(sel)
            if el and len(el.get_text(strip=True)) > len(description):
                description = str(el)

        company = ""
        if self.company_selector:
            el = soup.select_one(self.company_selector)
            company = el.get_text(strip=True) if el else ""

        return {
            "external_id": url,
            "title": title_el.get_text(strip=True),
            "company": company,
            "salary_min": None,
            "salary_max": None,
            "currency": None,
            "location": "",
            "work_format": None,
            "url": url,
            "description": description,
            "published_at": None,
        }
