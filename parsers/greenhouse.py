"""
Парсер Greenhouse Job Board API.
Публичный, без авторизации. Итерируется по списку компаний.
API: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
"""

import logging

import requests

from parsers._ats_tokens import merge_companies
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

API_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"


def all_companies() -> list[str]:
    """SEED (COMPANIES) + авто-найденные токены из БД."""
    return merge_companies(COMPANIES, "greenhouse")

# Верифицированные board_token компаний на Greenhouse (API возвращает 200).
# Токены не всегда совпадают с названием компании.
COMPANIES = [
    # Крупные tech — активно нанимают исследователей
    "airbnb", "stripe", "figma", "twilio", "datadog",
    "duolingo", "gitlab", "gitlabcrm", "instacart", "mixpanel", "robinhood",
    "neweratech",
    "reddit", "khanacademy", "upwork",
    # Продуктовые / B2B SaaS
    "airtable", "asana", "dropbox", "intercom", "brex",
    "carta", "checkr", "contentful", "faire", "gusto",
    "lattice", "modernhealth", "pendo", "toast", "vercel",
    "webflow", "gleanwork", "growtherapy", "connectwise",
    "betterhelpcom", "stratacareers",
    # Крупные компании (много вакансий, широкий поиск)
    "realtimeboardglobal",  # Miro
    "lucidmotors",          # Lucid
    "gongio",               # Gong
    "tripactions",          # Navan
    "dept", "wpp", "accenturefederalservices",
    # Найдено через google site:boards.greenhouse.io (2026-05)
    "anthropic", "smartsheet", "esri", "monzo", "mozilla", "upstart",
    "adyen", "affirm", "apolloio", "celonis", "databento", "humaninterest",
    "huntress", "ideo", "inmobi", "leagueinc", "metalab", "myfitnesspal",
    "okx", "omadahealth", "penninteractive", "postman", "samsungresearchamerica",
    "similarweb", "skylighthq", "triparc", "typeform", "via", "workato",
    "globalizationpartners", "creditkarma", "civicactions", "refhs",
    "ideoorg",
    # Расширенный гугл + TheirStack топ-10 (2026-05)
    "mintel", "harrys", "nubank", "olipop", "simplisafe",
    "greenthumbindustries", "tegnainc", "calendly", "deepmind",
    "ezcaterinc", "yipitdata", "opentable", "opswat",
    "worldquant", "aquaticcapitalmanagement", "wehrtyou", "vaticlabs",
    "imc", "radixexperienced", "chathamfinancial",
    "canonical", "spacex", "andurilindustries", "assetliving", "agoda",
    "cloudflare", "ouihelp", "sohohouseco",
    # Авто-добавлено discover_ats_by_name.py 2026-05-29
    "42",
    "ARK",
    "Acquia",
    "AlphaSights",
    "Appinio",
    "Arctouch",
    "Axios",
    "Bandzoogle",
    "C6Bank",
    "Cabify",
    "CircleCI",
    "Coinbase",
    "Comet",
    "ConsenSys",
    "Coursera",
    "Dashlane",
    "DataCamp",
    "Discord",
    "Elastic",
    "Ergeon",
    "Fastly",
    "Flip",
    "GoDaddy",
    "GoHiring",
    "Gremlin",
    "Gympass",
    "Headway",
    "Honeycomb",
    "HubSpot",
    "Hudl",
    "Indeed",
    "Juno",
    "Jusbrasil",
    "Kaggle",
    "Kentik",
    "Klaviyo",
    "Knack",
    "Kona",
    "Labelbox",
    "LivePerson",
    "Medium",
    "Mercari",
    "Mixmax",
    "MongoDB",
    "NoRedInk",
    "Oddball",
    "Okta",
    "OpenZeppelin",
    "Packlink",
    "PagerDuty",
    "Pleo",
    "Praxent",
    "QuintoAndar",
    "Raft",
    "ReCharge",
    "Scandit",
    "SecurityScorecard",
    "SmugMug",
    "Squad",
    "StreamNative",
    "Thorn",
    "Turing",
    "Udacity",
    "VTEX",
    "Valimail",
    "Valtech",
    "Wizeline",
    "ZenRows",
    "aestudio",
    "aha",
    "artlogic",
    "beyond",
    "brave",
    "carbon",
    "coalition",
    "cortex",
    "epicgames",
    "eyeo",
    "generalassembly",
    "ghost",
    "grafanalabs",
    "help",
    "iFit",
    "keen",
    "lincoln",
    "magrathea",
    "muckrack",
    "new",
    "octopusdeploy",
    "pantherlabs",
    "remote",
    "securityscorecard",
    "socket",
    "softexpert",
    "stackexchange",
    "stitchfix",
    "teravision",
    "testio",
    "vast",
    "wikimedia",
    "xpinc",
    # Авто-добавлено discover_ats_by_name.py 2026-05-29
    "AKQA",
    "Accela",
    "Affinity",
    "Algolia",
    "Allbirds",
    "Alloy",
    "Amplitude",
    "Anaplan",
    "Apollo",
    "AppDirect",
    "Appodeal",
    "Ascend",
    "Babylist",
    "Betterment",
    "Blend",
    "BlueCrew",
    "Branch",
    "Brightidea",
    "Bugcrowd",
    "Chartboost",
    "Chime",
    "ClassPass",
    "Clever",
    "Crunchyroll",
    "Databricks",
    "Dealpath",
    "Descript",
    "Dialpad",
    "Earnest",
    "Everlane",
    "Everlaw",
    "Five9",
    "Fivetran",
    "Flexport",
    "Forward",
    "Gemini",
    "Givecampus",
    "Glassdoor",
    "GoodTime",
    "Grin",
    "Groupon",
    "HackerRank",
    "Harmonic",
    "Haven",
    "Hover",
    "Imgur",
    "Insightly",
    "Iterable",
    "JustAnswer",
    "Landor",
    "LinkedIn",
    "Linqia",
    "Lob",
    "Lookout",
    "Lyft",
    "Marqeta",
    "MasterClass",
    "McAfee",
    "Medrio",
    "Mercury",
    "Method",
    "Narvar",
    "Nextdoor",
    "Nuro",
    "Oath",
    "Oura",
    "Pantheon",
    "Pathstream",
    "Philo",
    "Pinterest",
    "Poshmark",
    "PubNub",
    "Qualia",
    "Quip",
    "Roblox",
    "Rockbot",
    "Roku",
    "Roofstock",
    "Samsara",
    "Skupos",
    "SoFi",
    "Spin",
    "Springboard",
    "SurveyMonkey",
    "Tanium",
    "TaskRabbit",
    "Tetra",
    "Thirdlove",
    "Thoughtworks",
    "Truework",
    "Twitch",
    "Udemy",
    "Upgrade",
    "Vaco",
    "Verkada",
    "Wonderschool",
    "WorkBoard",
    "Yext",
    "Zenput",
    "ZeroCater",
    "Zscaler",
    "Zuora",
    "alphasense",
    "apollo",
    "askmediagroup",
    "aura",
    "batteryventures",
    "bitwarden",
    "branch",
    "carrotfertility",
    "chainguard",
    "charles",
    "clara",
    "cloverhealth",
    "collectivehealth",
    "cultureamp",
    "didi",
    "doximity",
    "ebury",
    "fabricgenomics",
    "figure",
    "fingerprint",
    "fleetio",
    "founders",
    "general",
    "goodbysilversteinpartners",
    "greenhouse",
    "grovecollaborative",
    "highland",
    "industrial",
    "iris",
    "juullabs",
    "karat",
    "launchdarkly",
    "leap",
    "lumahealth",
    "mattermost",
    "missionlane",
    "nearform",
    "netlify",
    "newrelic",
    "nexus",
    "novacredit",
    "onemedical",
    "oscar",
    "paypay",
    "productschool",
    "rga",
    "riotgames",
    "rocketlawyer",
    "saucelabs",
    "seatgeek",
    "silananotechnologies",
    "space",
    "stashinvest",
    "sterling",
    "stitch",
    "sumologic",
    "tailscale",
    "tempo",
    "temporal",
    "thetradedesk",
    "thrive",
    "tide",
    "zero",
    # Авто-добавлено discover_ats_by_name.py 2026-05-29
    "customerio",
    "platformsh",
    "rocketchat",
    # Авто-добавлено discover_ats_by_name.py 2026-05-30
    "brooklinen",
    "cleo",
    "ians",
    "justworks",
    "litify",
    "renaissancelearning-nam",
    "sharkninjaoperatingllc",
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
    offices = job.get("offices", [])
    if offices:
        return offices[0].get("name", "")
    return ""


def _extract_work_format(job: dict) -> str:
    title_lower = job.get("title", "").lower()
    content = job.get("content", "").lower()
    if "remote" in title_lower or "remote" in content[:500]:
        return "Remote"
    return ""


class GreenhouseParser(BaseParser):
    source_name = "greenhouse"
    channel = "global"
    harvest_ats = False  # сам ATS — url уже его токен

    def fetch(self) -> list[dict]:
        result = []
        for board_token in all_companies():
            url = API_URL.format(board_token=board_token)
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                logger.warning(
                    "[greenhouse] %s — ошибка: %s",
                    board_token,
                    getattr(getattr(e, "response", None), "status_code", str(e)),
                )
                continue

            for job in data.get("jobs", []):
                title = job.get("title", "")
                if not _is_relevant(title):
                    continue
                result.append({
                    "external_id": str(job.get("id", "")),
                    "title": title,
                    "company": board_token.capitalize(),
                    "salary_min": None,
                    "salary_max": None,
                    "currency": None,
                    "location": _extract_location(job),
                    "work_format": _extract_work_format(job),
                    "url": job.get("absolute_url", ""),
                    "description": job.get("content", ""),
                })

        return result
