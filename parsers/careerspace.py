"""
Парсер careerspace.app.

Публичного API нет: robots.txt закрывает и /api, и любые URL с query
(Disallow: /*?*), поэтому пагинация и поиск нам недоступны — уважаем правила.
Разрешённая страница /jobs отдаёт 8 свежих вакансий на каждый проход;
при интервале цикла в 15 минут это работает как лента новинок, дубликаты
отсекает общий дедуп.

Детальная страница — полноценный SSR: заголовок в h1, описание в .j-d__dsc-vl,
компания и вилка — в блоке карточки.
"""

import logging
import re
import time

import requests
from bs4 import BeautifulSoup

from parsers.base import BaseParser

logger = logging.getLogger(__name__)

BASE = "https://careerspace.app"
LIST_URL = f"{BASE}/jobs"
REQUEST_DELAY = 0.6
REQUEST_TIMEOUT = 30
RETRIES = 3

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_JOB_ID_RE = re.compile(r"/job/(\d+)")
# «118 000 - 194 000 ₽» — пробелы неразрывные.
_SALARY_RE = re.compile(r"(\d[\d\s ]{3,})\s*(?:-|—|–)\s*(\d[\d\s ]{3,})\s*(₽|\$|€)")
_SALARY_ONE_RE = re.compile(r"(?:от|from)\s*(\d[\d\s ]{3,})\s*(₽|\$|€)", re.IGNORECASE)
_CURRENCY = {"₽": "RUR", "$": "USD", "€": "EUR"}


def _num(raw: str) -> int | None:
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


class CareerspaceParser(BaseParser):
    source_name = "careerspace"
    channel = "ru"

    def fetch(self) -> list[dict]:
        html = self._get(LIST_URL)
        if not html:
            return []

        ids = sorted(set(_JOB_ID_RE.findall(html)), reverse=True)
        logger.info("[careerspace] Вакансий в ленте: %d", len(ids))

        out: list[dict] = []
        for job_id in ids:
            if self.is_known(job_id):
                continue
            v = self._detail(job_id)
            # Фильтр — в планировщике: отклонённые сохранятся, и is_known их запомнит.
            if v:
                out.append(v)
        logger.info("[careerspace] Новых карточек: %d", len(out))
        return out

    def _get(self, url: str) -> str | None:
        """Источник заметно тормозит — даём несколько попыток."""
        for _ in range(RETRIES):
            try:
                time.sleep(REQUEST_DELAY)
                resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                return resp.text
            except requests.RequestException:
                continue
        logger.debug("[careerspace] не открылась %s", url)
        return None

    def _detail(self, job_id: str) -> dict | None:
        url = f"{BASE}/job/{job_id}"
        html = self._get(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.select_one("h1")
        if not h1:
            return None

        description_el = soup.select_one(".j-d__dsc-vl") or soup.select_one(".j-d__dsc")
        company_el = soup.select_one("[class*=company]")

        smin = smax = currency = None
        card = soup.select_one(".j-d__content") or soup.select_one(".j-d__wr")
        if card:
            text = card.get_text(" ", strip=True)[:200]
            m = _SALARY_RE.search(text)
            if m:
                smin, smax = _num(m.group(1)), _num(m.group(2))
                currency = _CURRENCY.get(m.group(3))
            else:
                m = _SALARY_ONE_RE.search(text)
                if m:
                    smin = _num(m.group(1))
                    currency = _CURRENCY.get(m.group(2))

        return {
            "external_id": job_id,
            "title": h1.get_text(strip=True),
            "company": company_el.get_text(strip=True) if company_el else "",
            "salary_min": smin,
            "salary_max": smax,
            "currency": currency,
            "location": "",
            "work_format": None,
            "url": url,
            "description": str(description_el) if description_el else "",
            "published_at": None,
        }
