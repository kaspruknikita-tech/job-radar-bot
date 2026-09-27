"""
Скрейпит списки компаний-визовых-спонсоров с трёх сайтов и кладёт в БД
(таблица visa_sponsors). Матч вакансии с этим списком даёт +2 к score и
подсветку «🛂✅ В списке визовых спонсоров» в карточке модератора.

Источники:
  1. ellis.com/visa-sponsors  — Next.js __NEXT_DATA__, 180k работодателей,
     отсортированы по объёму H-1B. Есть website_domain + naics_code →
     фильтруем по индустрии (tech/product/research, кто реально нанимает
     ресерчеров), не тянем аутстафф-консалтинг.
  2. h1bdata.info/topcompanies.php — HTML-таблица, ~2000 топ-спонсоров.
  3. myvisajobs.com/reports/h1b/ — HTML-таблица, топ-спонсоры H-1B.

Опционально (--harvest): прогоняет собранные имена через discover_ats_by_name —
ищет оригинальные джоб-борды (Ashby/Greenhouse/Lever) и пишет токены в БД.

Usage:
    python3 tools/visa_sponsors_scrape.py
    python3 tools/visa_sponsors_scrape.py --ellis-pages 200
    python3 tools/visa_sponsors_scrape.py --harvest
    python3 tools/visa_sponsors_scrape.py --dry-run        # не писать в БД
"""
import argparse
import concurrent.futures
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import database

UA = "Mozilla/5.0 (compatible; ux-jobs-bot/1.0)"

# NAICS-семейства компаний, которые реально нанимают product/UX-ресерчеров.
# Префиксы: 5112/513 software publishers, 518 data/hosting, 519 web/info,
# 5415 computer systems design, 5417 R&D, 334 computer/electronics mfg.
ELLIS_NAICS_PREFIXES = ("5112", "513", "518", "519", "5415", "5417", "334", "5161")


def scrape_ellis(max_pages: int) -> list[tuple[str, str]]:
    """Топ-N работодателей ellis, отфильтрованных по NAICS. (display, domain)."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        url = f"https://www.ellis.com/visa-sponsors?page={page}"
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
            r.raise_for_status()
        except Exception as e:
            print(f"  [ellis] стр {page} ошибка: {e}")
            break
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if not m:
            print(f"  [ellis] стр {page}: нет __NEXT_DATA__, стоп")
            break
        emps = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("initialEmployers", [])
        if not emps:
            break
        for e in emps:
            naics = str(e.get("naics_code") or "")
            if not naics.startswith(ELLIS_NAICS_PREFIXES):
                continue
            display = (e.get("trade_name") or e.get("canonical_name") or "").strip()
            domain = (e.get("website_domain") or "").strip()
            if not display:
                continue
            key = display.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((display, domain))
        time.sleep(0.3)
        if page % 25 == 0:
            print(f"  [ellis] ... стр {page}, релевантных {len(out)}")
    print(f"  [ellis] {len(out)} релевантных (NAICS-фильтр)")
    return out


def scrape_h1bdata() -> list[tuple[str, str]]:
    """topcompanies.php — имя компании из ссылки. domain нет."""
    try:
        r = requests.get("https://h1bdata.info/topcompanies.php",
                         headers={"User-Agent": UA}, timeout=25)
        r.raise_for_status()
    except Exception as e:
        print(f"  [h1bdata] ошибка: {e}")
        return []
    names = re.findall(r'index\.php\?year=\d+&amp;em=[^"]+">([^<]+)</a>', r.text)
    out = [(n.strip(), "") for n in names if n.strip()]
    print(f"  [h1bdata] {len(out)} компаний")
    return out


def scrape_myvisajobs() -> list[tuple[str, str]]:
    """/reports/h1b/ — таблица rank|employer|lca|salary. employer идёт за rank-цифрой."""
    try:
        r = requests.get("https://www.myvisajobs.com/reports/h1b/",
                         headers={"User-Agent": UA}, timeout=25)
        r.raise_for_status()
    except Exception as e:
        print(f"  [myvisajobs] ошибка: {e}")
        return []
    cells = [re.sub(r"<[^>]+>", "", c).strip()
             for c in re.findall(r"<td[^>]*>(.*?)</td>", r.text, re.S)]
    out: list[tuple[str, str]] = []
    for i, c in enumerate(cells[:-1]):
        if c.isdigit():                       # rank-ячейка → следующая = employer
            emp = cells[i + 1].strip()
            if emp and not emp.isdigit() and not emp.startswith("$"):
                out.append((emp, ""))
    print(f"  [myvisajobs] {len(out)} компаний")
    return out


SOURCES = [
    ("ellis", None),                          # вызывается отдельно (нужен max_pages)
    ("h1bdata", scrape_h1bdata),
    ("myvisajobs", scrape_myvisajobs),
]


_ATS_VALIDATORS = {}        # заполняется лениво в _harvest (импорт requests-валидаторов)
_ATS_MODULES = {
    "ashby": "parsers.ashby",
    "greenhouse": "parsers.greenhouse",
    "lever": "parsers.lever",
    "smartrecruiters": "parsers.smartrecruiters",
    "bamboohr": "parsers.bamboohr",
}


def _harvest(names: list[str], workers: int) -> None:
    """Пробивает имена по 5 ATS (Ashby/Greenhouse/Lever/SmartRecruiters/BambooHR),
    валидные токены пишет в БД. SR/BambooHR валидируются по контенту (отдают
    200/302 на любой токен), поэтому используем валидаторы из discover_ats_from_repo."""
    import importlib
    from tools.discover_ats_by_name import candidates
    from tools.discover_ats_from_repo import (
        validate_ashby, validate_bamboohr, validate_gh,
        validate_lever, validate_smartrecruiters,
    )
    validators = {
        "ashby": validate_ashby,
        "greenhouse": validate_gh,
        "lever": validate_lever,
        "smartrecruiters": validate_smartrecruiters,
        "bamboohr": validate_bamboohr,
    }
    existing: dict[str, set[str]] = {}
    for ats, modpath in _ATS_MODULES.items():
        mod = importlib.import_module(modpath)
        existing[ats] = {t.lower() for t in mod.COMPANIES} | {
            t.lower() for t in database.load_ats_tokens(ats)
        }

    def probe(name: str) -> dict[str, str | None]:
        out: dict[str, str | None] = {ats: None for ats in validators}
        for c in candidates(name):
            cl = c.lower()
            for ats, val in validators.items():
                if out[ats] is None and cl not in existing[ats] and val(c):
                    out[ats] = c
            if all(out.values()):
                break
        return out

    # Чекпойнт: пропускаем имена, уже пробитые в прошлых прогонах (ats="visa5").
    # Делает харвест резюмируемым — рестарт продолжает с места обрыва.
    probed = {n for (n, a) in database.get_probed_pairs() if a == "visa5"}
    todo = [n for n in names if n.lower() not in probed]
    print(f"\n=== HARVEST по 5 ATS (Ashby/Greenhouse/Lever/SmartRecruiters/BambooHR) ===")
    print(f"имён всего {len(names)}, уже пробито {len(names) - len(todo)}, осталось {len(todo)}")

    # Одно переиспользуемое соединение + батч-запись + реконнект. Раньше открывали
    # по соединению на имя (2353 шт) — Railway сбрасывал под нагрузкой.
    import time as _t
    state = {"conn": database._get_connection()}

    def _flush(token_rows, probed_rows):
        for attempt in range(4):
            try:
                conn = state["conn"]
                with conn.cursor() as cur:
                    for ats, tok in token_rows:
                        cur.execute(
                            "INSERT INTO ats_discovered_tokens (ats, token, source) "
                            "VALUES (%s, %s, 'visa_sponsors') ON CONFLICT (ats, lower(token)) DO NOTHING",
                            (ats, tok))
                    for nm, result in probed_rows:
                        cur.execute(
                            "INSERT INTO ats_probed_names (name, ats, result) "
                            "VALUES (%s, 'visa5', %s) ON CONFLICT (lower(name), ats) DO NOTHING",
                            (nm, result))
                conn.commit()
                return
            except Exception as e:
                print(f"  [flush] обрыв БД, реконнект {attempt + 1}/4: {e}")
                try:
                    state["conn"].close()
                except Exception:
                    pass
                _t.sleep(3)
                state["conn"] = database._get_connection()
        print("  [flush] батч не записан после 4 попыток — имена перепробуются позже")

    found_total = {ats: 0 for ats in validators}
    tbuf: list[tuple[str, str]] = []
    pbuf: list[tuple[str, str]] = []
    done = 0
    FLUSH = 25
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(probe, n): n for n in todo}
        for f in concurrent.futures.as_completed(futures):
            name = futures[f]
            res = f.result()
            hits = []
            for ats in validators:
                tok = res[ats]
                if tok:
                    tbuf.append((ats, tok)); found_total[ats] += 1; hits.append(f"{ats}:{tok}")
            pbuf.append((name, "hit:" + ",".join(hits) if hits else "miss"))
            done += 1
            if len(pbuf) >= FLUSH:
                _flush(tbuf, pbuf); tbuf, pbuf = [], []
            if done % 100 == 0:
                print(f"  ... {done}/{len(todo)} (токенов найдено: {sum(found_total.values())})")
    _flush(tbuf, pbuf)  # хвост
    try:
        state["conn"].close()
    except Exception:
        pass
    for ats in validators:
        if found_total[ats]:
            print(f"  + {ats}: {found_total[ats]}")
    print(f"=== HARVEST готово: токенов найдено {sum(found_total.values())} ===")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ellis-pages", type=int, default=120,
                    help="страниц ellis (24 комп/стр); 120 ≈ топ-2880 до NAICS-фильтра")
    ap.add_argument("--harvest", action="store_true",
                    help="прогнать собранные имена через ATS-харвест")
    ap.add_argument("--harvest-only", action="store_true",
                    help="только харвест по именам из реестра БД (без re-скрейпа); резюмируемо")
    ap.add_argument("--workers", type=int, default=15)
    ap.add_argument("--dry-run", action="store_true", help="не писать в БД")
    args = ap.parse_args()

    if not args.dry_run:
        from dotenv import load_dotenv
        load_dotenv()
        database.init_visa_sponsors()

    # Резюмируемый харвест: имена из реестра БД, чекпойнт пропускает пробитые.
    if args.harvest_only:
        names = database.get_visa_sponsor_names()
        print(f"[harvest-only] имён в реестре: {len(names)}")
        _harvest(names, args.workers)
        return

    collected: list[tuple[str, str, str]] = []   # (display, domain, source)
    print("[ellis]")
    for display, domain in scrape_ellis(args.ellis_pages):
        collected.append((display, domain, "ellis"))
    for label, fn in SOURCES:
        if fn is None:
            continue
        print(f"[{label}]")
        for display, domain in fn():
            collected.append((display, domain, label))

    if not collected:
        print("Ничего не собрано — проверь сеть/доступ к сайтам", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print(f"\n[dry-run] собрано {len(collected)} записей, в БД не пишу")
    else:
        records = [(display, source, domain or None) for display, domain, source in collected]
        added = database.save_visa_sponsors_bulk(records)
        print(f"\nЗаписано в БД: новых ключей {added}, всего в реестре {database.count_visa_sponsors()}")

    if args.harvest:
        # Дедуп имён, чтобы не пробивать одно и то же.
        seen: set[str] = set()
        names: list[str] = []
        for display, _domain, _source in collected:
            k = display.lower()
            if k not in seen:
                seen.add(k)
                names.append(display)
        _harvest(names, args.workers)


if __name__ == "__main__":
    main()
