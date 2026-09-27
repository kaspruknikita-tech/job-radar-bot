"""
Парсер partnerkin.com/vacancy — вакансии в арбитраже трафика и affiliate
(iGaming, media buying, BD) — прямой домен профиля.

robots.txt запрещает пагинацию (Disallow: /vacancy*page*), поэтому берём
только первую страницу: ~35 свежих вакансий за проход. При цикле раз
в 15 минут это работает как лента новинок.

Текст ссылки в листинге — название роли, по нему отсеиваем чужое до
детального запроса. Карточка: «Вакансия компании <Компания>:<Роль>» в h1,
описание в .content_text, вилка в .vacancy_price внутри .vacancy_inner.
"""

import logging
import re
import time

import requests
from bs4 import BeautifulSoup

from filters.stopwords import apply_filters
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

BASE = "https://partnerkin.com"
LIST_URL = f"{BASE}/vacancy"
REQUEST_DELAY = 1.0
REQUEST_TIMEOUT = 40
RETRIES = 3

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_HREF_RE = re.compile(r"/vacancy/(\d+)_")
_H1_RE = re.compile(r"^Вакансия компании\s+(?P<company>.+?)\s*:\s*(?P<title>.+)$")
_CURRENCY = {"$": "USD", "€": "EUR", "₽": "RUR", "руб": "RUR"}
_AMOUNT_RE = re.compile(r"\d{1,3}(?:[ ,\u00a0]\d{3})+|\d{4,}|\d{3}")


def _parse_salary(text: str) -> tuple[int | None, int | None, str | None]:
    """«От $2,000» / «$1,500 – $3,000» / «После собеседования». Числа как есть, без пересчёта."""
    if not text:
        return None, None, None
    currency = next((code for sign, code in _CURRENCY.items() if sign in text), None)
    # Разделитель тысяч — строго группами по 3 цифры, иначе «$2,000 1-3 года»
    # склеивается в 20001 (хвост «1» из стажа).
    nums = [int(re.sub(r"[ ,\u00a0]", "", n)) for n in _AMOUNT_RE.findall(text)]
    nums = [n for n in nums if n >= 100]
    if not nums:
        return None, None, None
    if len(nums) == 1:
        return (None, nums[0], currency) if text.lower().lstrip().startswith("до") else (nums[0], None, currency)
    return nums[0], nums[1], currency


def _work_format(text: str) -> str | None:
    t = text.lower()
    if "удален" in t or "удалён" in t or "remote" in t:
        return "Удалёнка"
    if "гибрид" in t:
        return "Гибрид"
    if "офис" in t:
        return "Офис"
    return None


class PartnerkinParser(BaseParser):
    source_name = "partnerkin"
    channel = "ru"

    def fetch(self) -> list[dict]:
        html = self._get(LIST_URL)
        if not html:
            return []

        cards: dict[str, str] = {}
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=_HREF_RE):
            title = a.get_text(" ", strip=True)
            vid = _HREF_RE.search(a["href"]).group(1)
            if len(title) > 3 and vid not in cards:
                cards[vid] = a["href"] if a["href"].startswith("http") else BASE + a["href"]
                cards[vid + ":title"] = title

        ids = [k for k in cards if ":" not in k]
        # Детальную качаем только для релевантных по названию и ещё не виденных.
        todo = [vid for vid in ids
                if apply_filters({"title": cards[vid + ":title"]}) and not self.is_known(vid)]
        logger.info("[partnerkin] В ленте %d, к загрузке %d", len(ids), len(todo))

        out = [v for v in (self._detail(vid, cards[vid]) for vid in todo) if v]
        logger.info("[partnerkin] Карточек получено: %d", len(out))
        return out

    def _get(self, url: str) -> str | None:
        """Источник периодически отвечает с таймаутом — даём несколько попыток."""
        for _ in range(RETRIES):
            try:
                time.sleep(REQUEST_DELAY)
                resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                return resp.text
            except requests.RequestException:
                continue
        logger.warning("[partnerkin] не открылась %s", url)
        return None

    def _detail(self, vid: str, url: str) -> dict | None:
        html = self._get(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")

        h1 = soup.select_one("h1")
        if not h1:
            return None
        heading = h1.get_text(" ", strip=True)
        m = _H1_RE.match(heading)
        title = m.group("title").strip() if m else heading
        company = m.group("company").strip() if m else ""

        card = soup.select_one(".vacancy_inner") or soup
        description_el = card.select_one(".content_text")
        salary_el = card.select_one(".vacancy_price") or card.select_one(".price")
        smin, smax, currency = _parse_salary(salary_el.get_text(" ", strip=True) if salary_el else "")

        return {
            "external_id": vid,
            "title": title,
            "company": company,
            "salary_min": smin,
            "salary_max": smax,
            "currency": currency,
            "location": "",
            "work_format": _work_format(card.get_text(" ", strip=True)[:600]),
            "url": url,
            "description": str(description_el) if description_el else "",
            "published_at": None,
        }
