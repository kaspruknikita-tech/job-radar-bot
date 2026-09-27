"""
Локальная проверка фикса hirify (без LLM-ключа).
Тянет вакансию с api.hirify.me, прогоняет через парсер и показывает,
что именно увидит brand scorer (поле inp.company).

Запуск: poetry run python preview_hirify.py [vacancy_slug]
По умолчанию — 587660-staff-ux-researcher-ai (Cohere, твой пример).
"""
import sys
from dotenv import load_dotenv
load_dotenv()

from parsers.hirify import _make_session, _authenticate, _normalize, _fetch_description
from scoring import _make_inp, _clean_company

slug = sys.argv[1] if len(sys.argv) > 1 else "587660-staff-ux-researcher-ai"

s = _make_session()
mode = _authenticate(s)
print(f"[auth] mode={mode}\n")

r = s.get("https://api.hirify.me/api/vacancies",
          params={"search": "ux researcher", "per_page": 50, "page": 1}, timeout=15)
v = next((x for x in (r.json().get("data") or []) if x.get("slug") == slug), None)
if not v:
    print(f"вакансия {slug} не на первой странице — попробуй другой slug")
    sys.exit(1)

desc = _fetch_description(s, slug)
vac = _normalize(v, desc)
vac["id"] = int(v["id"])
vac["source"] = "hirify"
vac["channel"] = "global"

print(f"[parser raw]    company_title = {v.get('company_title')!r}")
print(f"[parser raw]    linkedin      = {v.get('linkedin')!r}")
print(f"[parser out]    company       = {vac['company']!r}")

inp = _make_inp(vac, vac["id"])
print(f"\n[scoring inp]   inp.company   = {inp.company!r}")
print(f"[scoring guard] clean('%hirify_global%')  = {_clean_company('%hirify_global%')!r}")
print(f"[scoring guard] clean('hirify')           = {_clean_company('hirify')!r}")

if inp.company:
    print(f"\nрезультат: brand scorer ПОЛУЧИТ '{inp.company}' и заресёрчит реальную компанию.")
else:
    print("\nрезультат: компания пуста → brand scorer ПРОПУЩЕН, brand_tag='Неизвестный', boost=0.")
print("в любом случае hirify.global скорить больше не будет.")
