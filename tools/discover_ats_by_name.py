"""
Discovery v2: берёт имена компаний из ineelhere/remote-jobs-resources,
генерит slug-маски (как в existing COMPANIES), пробует через
Ashby/Greenhouse/Lever API. Выводит валидные новые токены.

Маски (применяются к каждому имени):
    1. lower()
    2. lower().replace(' ', '')           # "Anduril Industries" -> "andurilindustries"
    3. lower().replace(' ', '-')          # -> "anduril-industries"
    4. lower().replace(' ', '_')
    5. первое_слово.lower()                # -> "anduril"
    6. как есть (camelCase, "OpenAI"-like)
    7. capitalize() (для Ashby — там Vetcove/Strava)

Usage:
    python3 tools/discover_ats_by_name.py
    python3 tools/discover_ats_by_name.py --limit 100
"""
import argparse
import ast
import concurrent.futures
import datetime
import logging
import re
import sys
import threading
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from parsers.ashby import COMPANIES as ASHBY_EXISTING
from parsers.greenhouse import COMPANIES as GH_EXISTING
from parsers.lever import COMPANIES as LEVER_EXISTING
from parsers.smartrecruiters import COMPANIES as SR_EXISTING
from parsers.bamboohr import COMPANIES as BH_EXISTING

README_URL = "https://raw.githubusercontent.com/ineelhere/remote-jobs-resources/main/README.md"
REMOTEINTECH_API = "https://api.github.com/repos/remoteintech/remote-jobs/contents/src/companies"
COMPANIES_CSV_URL = "https://raw.githubusercontent.com/connor11528/tech-companies-and-startups/master/companies.csv"


def fetch_names_ineelhere() -> list[str]:
    """ineelhere/remote-jobs-resources — markdown-таблица."""
    try:
        md = requests.get(README_URL, timeout=30).text
    except Exception as e:
        print(f"  [ineelhere] ошибка: {e}")
        return []
    names: list[str] = []
    for line in md.splitlines():
        m = re.match(r"\|\s*\d+\s*\|\s*([^|]+?)\s*\|", line)
        if m:
            name = m.group(1).strip().strip("*_`")
            mlink = re.match(r"\[([^\]]+)\]\([^)]+\)", name)
            if mlink:
                name = mlink.group(1).strip()
            if name and name.lower() not in ("company", "name"):
                names.append(name)
    return names


def fetch_names_remoteintech() -> list[str]:
    """remoteintech/remote-jobs — GitHub API listing src/companies/*.md.
    Имя файла = slug компании (15five.md -> 15five)."""
    try:
        r = requests.get(REMOTEINTECH_API, timeout=30, params={"per_page": 1000})
        if r.status_code == 403:
            body = r.json() if r.text else {}
            print(f"  [remoteintech] GitHub rate-limit (403): {body.get('message', 'без auth токена 60 req/h')}")
            return []
        r.raise_for_status()
        files = r.json()
    except Exception as e:
        print(f"  [remoteintech] ошибка: {e}")
        return []
    if not isinstance(files, list):
        print(f"  [remoteintech] неожиданный формат ответа: {type(files).__name__}")
        return []
    names: list[str] = []
    skip_prefixes = ("_", ".")
    skip_files = {"README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "LICENSE.md"}
    for f in files:
        n = f.get("name", "")
        if not n.endswith(".md") or n in skip_files or n.startswith(skip_prefixes):
            continue
        names.append(n[:-3])
    return names


def fetch_names_csv() -> list[str]:
    """connor11528/tech-companies-and-startups — CSV с колонкой Company Name."""
    import csv as csv_mod
    import io
    try:
        r = requests.get(COMPANIES_CSV_URL, timeout=60)
        r.raise_for_status()
        text = r.text
    except Exception as e:
        print(f"  [csv] ошибка: {e}")
        return []
    reader = csv_mod.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "Company Name" not in reader.fieldnames:
        print(f"  [csv] колонка 'Company Name' не найдена. Доступные: {reader.fieldnames}")
        return []
    names: list[str] = []
    for row in reader:
        n = (row.get("Company Name") or "").strip().strip('"')
        if n:
            names.append(n)
    return names


SOURCES = [
    ("ineelhere", fetch_names_ineelhere),
    ("remoteintech", fetch_names_remoteintech),
    ("connor11528-csv", fetch_names_csv),
]


def fetch_names() -> list[str]:
    """Собирает имена из всех SOURCES, дедупит без потери порядка.
    Падает с RuntimeError если ВСЕ источники вернули пусто — silent failure скрыл бы это."""
    all_names: list[str] = []
    source_counts: dict[str, int] = {}
    for label, fn in SOURCES:
        got = fn()
        source_counts[label] = len(got)
        print(f"  [{label}] {len(got)} имён")
        all_names.extend(got)
    if not all_names:
        raise RuntimeError(
            f"Все источники имён пусты: {source_counts}. "
            "Проверь интернет/rate-limit GitHub API."
        )
    seen: set[str] = set()
    uniq: list[str] = []
    for n in all_names:
        key = n.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(n)
    return uniq


_SUFFIXES = {"inc", "llc", "corp", "co", "ltd", "limited",
             "industries", "labs", "studios", "solutions",
             "group", "tech", "technologies", "software", "ai"}


def _strip_suffix(name: str) -> str:
    """Убирает один common-suffix с конца, если у имени 2+ слова.
    'Anduril Industries' -> 'Anduril'. 'Apollo' -> 'Apollo' (без изменения)."""
    parts = name.split()
    if len(parts) >= 2 and parts[-1].lower().rstrip(".,") in _SUFFIXES:
        return " ".join(parts[:-1])
    return name


def candidates(name: str) -> list[str]:
    """Генерит варианты токена для имени."""
    out: list[str] = []
    # как есть
    out.append(name)
    # очистка: только буквы/цифры/пробелы/дефис/точка
    clean = re.sub(r"[^A-Za-z0-9 .\-]", "", name).strip()
    lo = clean.lower()
    out += [
        lo,
        lo.replace(" ", ""),
        lo.replace(" ", "-"),
        lo.replace(" ", "_"),
    ]
    # Маска А: убрать точки (для "Apollo.io" -> "apolloio")
    no_dot = lo.replace(".", "")
    out += [
        no_dot,
        no_dot.replace(" ", ""),
        no_dot.replace(" ", "-"),
    ]
    parts = lo.split()
    if parts:
        out.append(parts[0])  # первое слово
        out.append("-".join(parts))

    # Маска Б: CamelCase split на дефис ("PostHog" -> "post-hog")
    if re.search(r"[a-z][A-Z]", name):
        kebab = re.sub(r"(?<=[a-z])(?=[A-Z])", "-", name).lower()
        out.append(kebab)

    # Маска В: убрать common-suffix ("Anduril Industries" -> "Anduril" / "anduril")
    stripped = _strip_suffix(name)
    if stripped != name:
        s_lo = stripped.lower()
        out += [
            stripped,
            s_lo,
            s_lo.replace(" ", ""),
            s_lo.replace(" ", "-"),
        ]

    # дедуп с сохранением порядка
    seen: set[str] = set()
    uniq: list[str] = []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


_RATE_LOCKS = {
    "ashby": threading.Lock(),
    "greenhouse": threading.Lock(),
    "lever": threading.Lock(),
    "smartrecruiters": threading.Lock(),
    "bamboohr": threading.Lock(),
}
_LAST_CALL: dict[str, float] = {
    "ashby": 0.0, "greenhouse": 0.0, "lever": 0.0,
    "smartrecruiters": 0.0, "bamboohr": 0.0,
}
_MIN_INTERVAL = 0.15  # sec между запросами к одному ATS — троттлинг


def _throttle(ats: str) -> None:
    with _RATE_LOCKS[ats]:
        delta = time.time() - _LAST_CALL[ats]
        if delta < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - delta)
        _LAST_CALL[ats] = time.time()


def _check(ats: str, url: str) -> bool:
    _throttle(ats)
    try:
        r = requests.get(url, timeout=15)
    except Exception:
        return False
    if r.status_code == 429:
        print(f"  [{ats}] 429 rate-limited, увеличь _MIN_INTERVAL")
        return False
    return r.status_code == 200


def check_ashby(t: str) -> bool:
    return _check("ashby", f"https://api.ashbyhq.com/posting-api/job-board/{t}?includeCompensation=true")


def check_gh(t: str) -> bool:
    return _check("greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs")


def check_lever(t: str) -> bool:
    return _check("lever", f"https://api.lever.co/v0/postings/{t}?mode=json")


def check_smartrecruiters(t: str) -> bool:
    # API отдаёт 200 на любой токен — существование = totalFound>0.
    _throttle("smartrecruiters")
    try:
        r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{t}/postings?limit=1", timeout=15)
        return r.status_code == 200 and r.json().get("totalFound", 0) > 0
    except Exception:
        return False


def check_bamboohr(t: str) -> bool:
    # Несуществующий субдомен → 302 на www. Существование = 200 + ключ result.
    _throttle("bamboohr")
    try:
        r = requests.get(f"https://{t}.bamboohr.com/careers/list", timeout=15, allow_redirects=False)
        return r.status_code == 200 and "result" in r.json()
    except Exception:
        return False


_ATS_CHECKS = {
    "ashby": check_ashby,
    "greenhouse": check_gh,
    "lever": check_lever,
    "smartrecruiters": check_smartrecruiters,
    "bamboohr": check_bamboohr,
}


def probe_name(name: str, existing: dict) -> dict:
    """Возвращает {ats: token | None} — первый успешный кандидат по каждому ATS."""
    out = {"name": name, **{ats: None for ats in _ATS_CHECKS}}
    cands = candidates(name)
    for c in cands:
        for ats, check in _ATS_CHECKS.items():
            if not out[ats] and c.lower() not in existing[ats] and check(c):
                out[ats] = c
        if all(out[ats] for ats in _ATS_CHECKS):
            break
    return out


PARSER_PATHS = {
    "ashby": Path(__file__).resolve().parent.parent / "parsers" / "ashby.py",
    "greenhouse": Path(__file__).resolve().parent.parent / "parsers" / "greenhouse.py",
    "lever": Path(__file__).resolve().parent.parent / "parsers" / "lever.py",
    "smartrecruiters": Path(__file__).resolve().parent.parent / "parsers" / "smartrecruiters.py",
    "bamboohr": Path(__file__).resolve().parent.parent / "parsers" / "bamboohr.py",
}


def _find_companies_end_lineno(source: str) -> int:
    """Возвращает строку с закрывающей ']' для COMPANIES. -1 если не найден."""
    tree = ast.parse(source)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
            if len(targets) == 1 and isinstance(targets[0], ast.Name) and targets[0].id == "COMPANIES":
                if isinstance(node.value, ast.List):
                    return node.value.end_lineno
    return -1


def append_to_parser(ats: str, tokens: list[str]) -> tuple[bool, str]:
    """Вписывает новые токены перед ']' списка COMPANIES.
    Возвращает (ok, message). Проверяет синтаксис после изменения."""
    path = PARSER_PATHS[ats]
    src = path.read_text(encoding="utf-8")
    end_line = _find_companies_end_lineno(src)
    if end_line < 0:
        return False, f"не найден COMPANIES в {path.name}"

    lines = src.splitlines(keepends=True)
    today = datetime.date.today().isoformat()
    comment = f"    # Авто-добавлено discover_ats_by_name.py {today}\n"
    chunks = [f'    "{t}",\n' for t in tokens]
    insertion = [comment] + chunks

    # end_line — индекс строки с ']'. Вставляем ПЕРЕД ней (lines 1-indexed)
    new_lines = lines[:end_line - 1] + insertion + lines[end_line - 1:]
    new_src = "".join(new_lines)

    # Проверка синтаксиса
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        return False, f"syntax error после вставки: {e}"

    path.write_text(new_src, encoding="utf-8")
    return True, f"добавлено {len(tokens)} токенов в {path.name}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=15)
    ap.add_argument("--apply", action="store_true",
                    help="вписать найденные токены прямо в parsers/{ats}.py")
    args = ap.parse_args()

    names = fetch_names()
    if args.limit:
        names = names[: args.limit]
    print(f"Имён компаний из README: {len(names)}")

    existing = {
        "ashby": {t.lower() for t in ASHBY_EXISTING},
        "greenhouse": {t.lower() for t in GH_EXISTING},
        "lever": {t.lower() for t in LEVER_EXISTING},
        "smartrecruiters": {t.lower() for t in SR_EXISTING},
        "bamboohr": {t.lower() for t in BH_EXISTING},
    }

    results: list[dict] = []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(probe_name, n, existing): n for n in names}
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
            done += 1
            if done % 50 == 0:
                hits = sum(1 for r in results if any(r[a] for a in _ATS_CHECKS))
                print(f"  ... {done}/{len(names)} (хиты: {hits})")

    print()
    failures: list[str] = []
    for ats in _ATS_CHECKS:
        valid = sorted({r[ats] for r in results if r[ats]})
        print(f"=== {ats}: новых валидных {len(valid)} ===")
        for t in valid:
            print(f"  + {t}")
        if args.apply and valid:
            ok, msg = append_to_parser(ats, valid)
            print(f"  -> {'OK' if ok else 'FAIL'}: {msg}")
            if not ok:
                failures.append(f"{ats}: {msg}")
        print()

    if not args.apply:
        print("Запусти с --apply чтобы автоматически вписать токены в parsers/*.py")

    if failures:
        print(f"ОШИБКИ при --apply: {len(failures)}", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
