"""
Парсер Lever Postings API.
Публичный, без авторизации. Итерируется по списку компаний.
API: https://api.lever.co/v0/postings/{board_token}?mode=json
"""

import logging

import requests

from parsers._ats_tokens import merge_companies
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

API_URL = "https://api.lever.co/v0/postings/{board_token}?mode=json"


def all_companies() -> list[str]:
    """SEED (COMPANIES) + авто-найденные токены из БД."""
    return merge_companies(COMPANIES, "lever")

# Верифицированные board_token на Lever (jobs.lever.co/{token}).
# Регистр важен (есть Huckleberrylabs, court-avenue и т.п.).
COMPANIES = [
    # Найдено через google site:jobs.lever.co (2026-05)
    "outreach", "Huckleberrylabs", "colibrigroup", "zoox", "articulate",
    "fyusion", "jobgether", "prosper", "brevo",
    "xero", "wetransfer", "pointclickcare", "wmg", "valgenesis",
    "blinkux", "elevatelabs", "spotify",
    "researchinnovations.com", "waabi", "convergentresearch", "grantstreet",
    "apolloresearch", "hopelab", "whoop",
    "crowdriff", "ro", "viget", "rover", "finix", "fantasy",
    "court-avenue", "lodgify",
    # Авто-добавлено discover_ats_by_name.py 2026-05-29
    "15five",
    # Авто-добавлено discover_ats_by_name.py 2026-05-29
    "Smile.io",
    "activecampaign",
    "aerostrat",
    "anomali",
    "atlassian",
    "bluecatnetworks",
    "bounteous",
    "britecore",
    "capital",
    "caremessage",
    "charitywater",
    "collabora",
    "dronedeploy",
    "freeletics",
    "gojob",
    "graylog",
    "heetch",
    "instructure",
    "kinsta",
    "kraken",
    "labelbox",
    "lifen",
    "loadsmart",
    "marcopolo",
    "medium",
    "mindful",
    "objective",
    "octopus",
    "olo",
    "oowlish",
    "paytm",
    "prominentedge",
    "rackspace",
    "renofi",
    "spreedly",
    "sysdig",
    "teamsnap",
    "teleport",
    "toptal",
    "webfx",
    # Авто-добавлено discover_ats_by_name.py 2026-05-29
    "5amventures",
    "Coda",
    "Hivemapper",
    "alloy",
    "angellist",
    "appen",
    "backerkit",
    "better",
    "blue",
    "boxbot",
    "brilliant",
    "buildingconnected",
    "canvasmedical",
    "circlemedical",
    "coderpad",
    "delphix",
    "distru",
    "endpointclinical",
    "fabricgenomics",
    "findem",
    "fond",
    "goodeggs",
    "grand",
    "houzz",
    "incorta",
    "jobvite",
    "kabam",
    "kapwing",
    "leadspace",
    "lever",
    "linkedin",
    "logrocket",
    "minted",
    "modeln",
    "netflix",
    "ockam",
    "palantir",
    "peoplegrove",
    "perforce",
    "pivotal",
    "plaid",
    "quantcast",
    "relay",
    "rigetti",
    "rylo",
    "scality",
    "sila",
    "snaplogic",
    "snappr",
    "sonatype",
    "terminus",
    "theathletic",
    "trustarc",
    "unitq",
    "veeva",
    "vevo",
    "visby",
    "wealthfront",
    "zazzle",
    "zenysis",
    # Авто-добавлено discover_ats_by_name.py 2026-05-29
    "Sauce",
]

WHITELIST = [
    "ux researcher", "ux research",
    "user researcher", "user research",
    "product researcher", "design researcher",
    "usability researcher", "usability research",
    "cx researcher", "cx research",
    "consumer insights", "user insights",
    "ux writer", "content designer",
    "usability", "user experience researcher",
]


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in WHITELIST)


def _extract_location(job: dict) -> str:
    cats = job.get("categories") or {}
    return (cats.get("location") or "").strip()


def _extract_work_format(job: dict) -> str:
    wt = (job.get("workplaceType") or "").strip()
    if wt:
        return wt.capitalize()  # "remote" -> "Remote"
    return ""


def _extract_salary(job: dict) -> tuple[int | None, int | None, str | None]:
    sr = job.get("salaryRange") or {}
    return sr.get("min"), sr.get("max"), sr.get("currency")


class LeverParser(BaseParser):
    source_name = "lever"
    channel = "global"
    harvest_ats = False  # сам ATS — url уже его токен

    def fetch(self) -> list[dict]:
        result = []
        for board_token in all_companies():
            url = API_URL.format(board_token=board_token)
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as e:
                logger.warning(
                    "[lever] %s — ошибка: %s",
                    board_token,
                    getattr(getattr(e, "response", None), "status_code", str(e)),
                )
                continue

            for job in data:
                title = (job.get("text") or "").strip()
                if not _is_relevant(title):
                    continue
                salary_min, salary_max, currency = _extract_salary(job)
                result.append({
                    "external_id": str(job.get("id", "")),
                    "title": title,
                    "company": board_token,
                    "salary_min": salary_min,
                    "salary_max": salary_max,
                    "currency": currency,
                    "location": _extract_location(job),
                    "work_format": _extract_work_format(job),
                    "url": job.get("hostedUrl") or job.get("applyUrl", ""),
                    "description": job.get("description", ""),
                })

        return result
