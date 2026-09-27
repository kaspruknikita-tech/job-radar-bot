"""
Discovery: проходит career-URL из ineelhere/remote-jobs-resources README,
ищет ATS-токены (Ashby/Greenhouse/Lever/Workable), валидирует через
публичные API и печатает новые (которых нет в parsers/*.py).

Usage:
    python3 tools/discover_ats_from_repo.py            # дёрнуть свежий README
    python3 tools/discover_ats_from_repo.py readme.md  # из локального файла

Дальше — глазами просматриваешь вывод, копируешь токены в COMPANIES.
"""
import argparse
import concurrent.futures
import re
import sys
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# чтобы импортировать список существующих COMPANIES
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from parsers.ashby import COMPANIES as ASHBY_EXISTING
from parsers.greenhouse import COMPANIES as GH_EXISTING
from parsers.lever import COMPANIES as LEVER_EXISTING

README_URL = "https://raw.githubusercontent.com/ineelhere/remote-jobs-resources/main/README.md"
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; research-ux-jobs/1.0)"}

ATS_PATTERNS = {
    "ashby":      re.compile(r"jobs\.ashbyhq\.com/([^/?#\"' ]+)", re.I),
    "greenhouse": re.compile(r"(?:job-?boards?|boards-api)?\.?greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_\-.]+)", re.I),
    "lever":      re.compile(r"jobs\.lever\.co/([^/?#\"' ]+)", re.I),
    "workable":   re.compile(r"apply\.workable\.com/([^/?#\"' ]+)", re.I),
    "smartrecruiters": re.compile(r"(?:jobs\.smartrecruiters\.com|api\.smartrecruiters\.com/v1/companies)/([^/?#\"' ]+)", re.I),
    "bamboohr":   re.compile(r"https?://([a-z0-9][a-z0-9\-]*)\.bamboohr\.com", re.I),
}


def fetch_readme(arg: str | None) -> str:
    if arg:
        return Path(arg).read_text()
    return requests.get(README_URL, timeout=30).text


def extract_urls(md: str) -> list[str]:
    # markdown links и raw URLs
    urls = re.findall(r"https?://[^\s\)\"']+", md)
    # уникальные, без хвостовых знаков
    out = []
    seen = set()
    for u in urls:
        u = u.rstrip(".,);")
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


CAREER_PATHS = ["", "/careers", "/jobs", "/about/careers", "/company/careers",
                "/about/jobs", "/team/jobs", "/careers/jobs"]


def _scan_text(text: str, found: dict[str, set[str]]) -> None:
    for ats, pat in ATS_PATTERNS.items():
        for m in pat.findall(text):
            if _looks_like_token(m):
                found[ats].add(urllib.parse.unquote(m))


def scrape(url: str) -> dict[str, set[str]]:
    """Возвращает {ats: {tokens}}. Пробует основной URL + типичные career-пути.
    Останавливается при первом ATS-хите чтобы не плодить запросы."""
    found = {k: set() for k in ATS_PATTERNS}
    base = url.rstrip("/")
    for path in CAREER_PATHS:
        try_url = base + path if path else url
        try:
            r = requests.get(try_url, headers=HEAD, timeout=10, allow_redirects=True)
            if r.status_code >= 400:
                continue
            _scan_text(r.url, found)
            _scan_text(r.text, found)
        except Exception:
            continue
        if any(found[k] for k in found):
            break  # нашли ATS — дальше не пробуем
    return found


def _looks_like_token(t: str) -> bool:
    # отсекаем мусор типа "io", "com", "embed", numeric IDs одиночные
    if t in {"io", "com", "embed", "v1", "boards", "jobs", "jobs.lever.co"}:
        return False
    if t.isdigit() and len(t) < 6:
        return False
    if "/" in t or "?" in t or "<" in t:
        return False
    return True


def validate_ashby(t: str) -> bool:
    try:
        r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{t}?includeCompensation=true", timeout=20)
        return r.status_code == 200
    except Exception:
        return False


def validate_gh(t: str) -> bool:
    try:
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs", timeout=20)
        return r.status_code == 200
    except Exception:
        return False


def validate_lever(t: str) -> bool:
    try:
        r = requests.get(f"https://api.lever.co/v0/postings/{t}?mode=json", timeout=20)
        return r.status_code == 200
    except Exception:
        return False


def validate_smartrecruiters(t: str) -> bool:
    # API отдаёт 200 на любой токен — существование = totalFound>0.
    try:
        r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{t}/postings?limit=1", timeout=20)
        return r.status_code == 200 and r.json().get("totalFound", 0) > 0
    except Exception:
        return False


def validate_bamboohr(t: str) -> bool:
    # Несуществующий субдомен → 302 на www. Существование = 200 + ключ result.
    try:
        r = requests.get(f"https://{t}.bamboohr.com/careers/list", timeout=20, allow_redirects=False)
        return r.status_code == 200 and "result" in r.json()
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("readme", nargs="?", help="local README.md (иначе тянем с github)")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0, help="ограничить число URL для теста")
    args = ap.parse_args()

    md = fetch_readme(args.readme)
    urls = extract_urls(md)
    if args.limit:
        urls = urls[:args.limit]
    print(f"Сканирую {len(urls)} URL'ов...")

    found_total: dict[str, set[str]] = {k: set() for k in ATS_PATTERNS}
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for found in ex.map(scrape, urls):
            for ats, toks in found.items():
                found_total[ats].update(toks)
            done += 1
            if done % 50 == 0:
                print(f"  ... {done}/{len(urls)}")

    print()
    existing = {
        "ashby": {t.lower() for t in ASHBY_EXISTING},
        "greenhouse": {t.lower() for t in GH_EXISTING},
        "lever": {t.lower() for t in LEVER_EXISTING},
    }
    validators = {
        "ashby": validate_ashby,
        "greenhouse": validate_gh,
        "lever": validate_lever,
    }

    for ats in ("ashby", "greenhouse", "lever", "workable"):
        toks = sorted(found_total[ats])
        new = [t for t in toks if t.lower() not in existing.get(ats, set())]
        print(f"=== {ats}: всего {len(toks)}, новых {len(new)} ===")
        if ats == "workable":
            # парсера ещё нет — просто перечислим
            for t in new:
                print(f"  ? {t}")
            continue
        # валидируем параллельно
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
            results = list(zip(new, ex.map(validators[ats], new)))
        valid = [t for t, ok in results if ok]
        print(f"  валидных: {len(valid)}")
        for t in valid:
            print(f"  + {t}")


if __name__ == "__main__":
    main()
