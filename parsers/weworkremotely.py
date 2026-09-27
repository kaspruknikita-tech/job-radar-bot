"""
Парсер We Work Remotely.
RSS: https://weworkremotely.com/categories/remote-design-jobs.rss
     https://weworkremotely.com/categories/remote-product-jobs.rss
Публичный, без ключей.
"""

import logging
import xml.etree.ElementTree as ET

import requests

from parsers.base import BaseParser

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    "https://weworkremotely.com/categories/remote-design-jobs.rss",
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
]

WHITELIST = ["researcher", "research", "ux", "cx", "insight", "usability"]


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in WHITELIST)


class WeWorkRemotelyParser(BaseParser):
    source_name = "weworkremotely"
    channel = "global"

    def fetch(self) -> list[dict]:
        result = []
        seen_ids: set[str] = set()

        for feed_url in RSS_FEEDS:
            try:
                resp = requests.get(
                    feed_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=15,
                )
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
            except Exception:
                logger.exception("[weworkremotely] Ошибка запроса: %s", feed_url)
                continue

            for item in root.findall(".//item"):
                raw_title = item.findtext("title", "")
                # Формат: "Company: Job Title"
                title = raw_title.split(": ", 1)[-1] if ": " in raw_title else raw_title
                company = raw_title.split(": ", 1)[0] if ": " in raw_title else ""

                if not _is_relevant(title):
                    continue

                url = item.findtext("link", "")
                if not url:
                    guid = item.findtext("guid", "")
                    url = guid

                external_id = url.rstrip("/").split("/")[-1]
                if external_id in seen_ids:
                    continue
                seen_ids.add(external_id)

                result.append({
                    "external_id": external_id,
                    "title": title,
                    "company": company,
                    "salary_min": None,
                    "salary_max": None,
                    "currency": None,
                    "location": item.findtext("region", "") or "Remote",
                    "work_format": "Remote",
                    "url": url,
                    "description": item.findtext("description", ""),
                })

        return result
