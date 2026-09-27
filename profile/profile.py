"""Профиль соискателя. Правится только этот файл и role-profile.md — код не трогается.

Пример ниже — профиль Technical PM / Operations / Affiliate (геймдев, iGaming, martech).
Замените списки на свои. Подробно — README, раздел «Настройка под себя»."""

# ============================================================
# 1. ЧТО ИСКАТЬ — поисковые запросы источников
# ============================================================

SEARCH_HH = [
    # --- TPM: техническая координация, интеграции, MarTech/данные ---
    '"Technical Project Manager"',
    '"Technical Program Manager"',
    '"IT Project Manager"',
    '"Digital Project Manager"',
    '"Integration Manager"',
    '"MarTech Manager"',
    '"Marketing Operations"',
    '"Data Platform Manager"',
    '"Analytics Manager"',
    "Технический менеджер проектов",
    "Технический проджект-менеджер",
    "Менеджер по интеграциям",
    "Менеджер по внедрению",
    "ИТ-менеджер проектов",
    # --- DEL: delivery, программы, PMO-исполнение ---
    '"Project Manager"',
    '"Delivery Manager"',
    '"Delivery Lead"',
    '"Service Delivery Manager"',
    '"Head of Delivery"',
    '"Program Manager"',
    '"Programme Manager"',
    '"Scrum Master"',
    '"Agile Coach"',
    "Менеджер проектов",
    "Менеджер проекта",
    "Проектный менеджер",
    "Проджект-менеджер",
    "Проджект менеджер",
    "Руководитель проектов",
    "Руководитель проекта",
    "Руководитель программы",
    "Менеджер программ",
    "Скрам-мастер",
    # --- OPS: операционка, product/business/partner ops ---
    '"Operations Manager"',
    '"Head of Operations"',
    '"Product Operations"',
    '"Business Operations"',
    '"Growth Operations"',
    '"Partner Operations"',
    '"Revenue Operations"',
    '"Affiliate Manager"',
    '"Partnerships Manager"',
    '"Vendor Manager"',
    "Операционный менеджер",
    "Операционный директор",
    "Руководитель операционного отдела",
    "Менеджер по партнерским программам",
    "Партнерский менеджер",
    "Менеджер по процессам",
    # --- PERF: enablement, sales/support ops, обучение ---
    '"Enablement Manager"',
    '"Sales Operations"',
    '"Support Operations"',
    '"Learning Operations"',
    '"Customer Success Manager"',
    # --- TRANS: трансформация, PMO, стратегические инициативы ---
    '"Transformation Manager"',
    '"Head of PMO"',
    '"Project Management Office"',
    "Руководитель PMO",
    "Менеджер по трансформации",
    "Руководитель проектного офиса",
]

SEARCH_HH_TITLE_ONLY = [
    # RU
    "менеджер проектов",
    "менеджер проекта",
    "проектный менеджер",
    "руководитель проектов",
    "руководитель проекта",
    "проджект",
    "операционный менеджер",
    "проектный офис",
    "менеджер по внедрению",
    "менеджер по интеграциям",
    "партнерский менеджер",
    "бизнес-аналитик",
    "аккаунт-менеджер",
    # EN
    "project manager",
    "program manager",
    "delivery manager",
    "operations manager",
    "product ops",
    "business operations",
    "pmo",
    "scrum master",
    "affiliate manager",
    "account manager",
    "business analyst",
    "transformation",
]

SEARCH_HH_AREAS = [2, 1, 113]

SEARCH_HABR_CAREER = [
    "менеджер проектов",
    "проектный менеджер",
    "руководитель проектов",
    "проджект менеджер",
    "операционный менеджер",
    "менеджер по внедрению",
    "бизнес-аналитик",
    "project manager",
    "program manager",
    "delivery manager",
    "operations manager",
    "product operations",
    "scrum master",
]

SEARCH_RABOTARU = [
    "менеджер проектов",
    "руководитель проектов",
    "операционный менеджер",
    "project manager",
    "delivery manager",
    "менеджер по внедрению",
    "партнерский менеджер",
]

SEARCH_YANDEXJOBS = [
    "менеджер проектов",
    "руководитель проектов",
    "операционный менеджер",
    "project manager",
    "аккаунт-менеджер",
]

SEARCH_HIRIFY = [
    "ux researcher",
    "user researcher",
    "cx researcher",
    "service designer",
    "usability researcher",
    "research ops",
]

SEARCH_JOBICY_TAGS = [
    "project manager",
    "program manager",
    "delivery manager",
    "operations manager",
    "product operations",
]

SEARCH_REMOTEROCKETSHIP = [
    "Project Manager",
    "Program Manager",
    "Delivery Manager",
    "Operations Manager",
    "Product Operations",
    "Technical Project Manager",
]

SEARCH_HITMARKER = [
    "project manager",
    "program manager",
    "operations manager",
    "delivery manager",
]

SEARCH_WANTAPPLY_CATEGORIES = ["ux-researcher", "customer-support"]

SEARCH_WANTAPPLY_TITLES = [
    "researcher", "research", "ux", "cx", "usability",
    "service designer", "voice of customer", "ux strategist",
    "research ops", "cx analyst", "customer experience",
]

SEARCH_LINKEDIN = [
    "Technical Project Manager",
    "Technical Program Manager",
    "Delivery Manager",
    "Operations Manager",
    "Project Manager iGaming",
]

# ============================================================
# 2. ФИЛЬТР ЗАГОЛОВКОВ — что пускать в базу
# ============================================================

WHITELIST = [
    # --- Проектное управление (TPM, DEL) ---
    "project",
    "проект",
    "проджект",
    "program",
    "программ",
    "delivery",
    "pmo",
    "tpm",
    "scrum master",
    "скрам-мастер",
    # --- Операционное управление (OPS, PERF) ---
    "operation",
    "операц",
    "ops",
    "опс",
    # --- Трансформация (TRANS) ---
    "transformation",
    "трансформац",
    # --- Техническая координация (TPM) ---
    "integration",
    "интеграц",
    "внедрени",
    "enablement",
    # --- Смежные роли, оцениваются по содержанию (см. ops_content в скоринге) ---
    "business analyst",
    "бизнес-аналитик",
    "бизнес аналитик",
    "account manager",
    "аккаунт",
    "partner",
    "партнер",
    "партнёр",
    "affiliate",
    "продаж",
    "sales manager",
]

BLACKLIST = [
    # Аналитики (кроме бизнес-аналитика — он в белом списке)
    "data analyst",
    "аналитик данных",
    "продуктовый аналитик",
    "product analyst",
    "системный аналитик",
    "system analyst",
    "systems analyst",
    # Дизайн
    "ux",
    "ui",
    "дизайнер",
    "designer",
    # Разработка (синонимы developer: без них "program" ловит "programmer")
    "разработчик",
    "developer",
    "программист",
    "programmer",
    "programming",
    "software engineer",
    "backend",
    "frontend",
    "fullstack",
    "full stack",
    # HR / рекрутинг
    "hr",
    "рекрутер",
    "recruiter",
    "talent acquisition",
    "people ops",
    "people operations",
    # Контент
    "копирайтер",
    "copywriter",
    "smm",
]

# ============================================================
# 3. СЛОВАРИ СКОРИНГА — вес заголовка, плюсы и минусы описания
# ============================================================

TITLE_STRONG = [
    ("technical project manager", 45), ("technical program manager", 45),
    ("технический менеджер проект", 45), ("технический руководитель проект", 45),
    ("delivery manager", 42), ("delivery lead", 40),
    ("program manager", 38), ("менеджер программ", 34),
    ("product operations", 42), ("product ops", 42),
    ("business operations", 38), ("business ops", 38),
    ("marketing operations", 40), ("growth operations", 40), ("martech", 42),
    ("integration manager", 38), ("менеджер по интеграц", 38), ("интеграционный менеджер", 38),
    ("руководитель проектного офиса", 34), ("pmo", 30),
    ("операционный менеджер", 32), ("operations manager", 34),
    ("менеджер по операц", 30), ("руководитель операционн", 32),
    ("операционный директор", 26), ("head of operations", 30),
    ("it project manager", 40), ("менеджер ит-проект", 40), ("менеджер ит проект", 40),
    ("руководитель ит-проект", 40), ("руководитель it-проект", 40),
    ("project manager", 32), ("менеджер проектов", 30), ("руководитель проектов", 30),
    ("менеджер проекта", 28), ("менеджер по проектам", 28), ("head of delivery", 40),
    ("руководитель отдела проектов", 30), ("руководитель направления проект", 30),
    ("проектный менеджер", 30), ("руководитель проекта", 26),
    ("менеджер по процессам", 28), ("process manager", 28),
    ("руководитель партнерск", 26), ("partner operations", 32),
    ("analytics manager", 26), ("менеджер по аналитике", 24),
    ("agile coach", 20), ("scrum master", 18),
    ("transformation manager", 30), ("менеджер по трансформац", 28),
]

TITLE_BAD = [
    "продаж", "строитель", "строительн", "смр", "монтаж", "электромонтаж", "ремонт",
    "розниц", "склад", "общепит", "ресторан", "кафе", "повар", "медицин", "клиник",
    "фарм", "юрист", "бухгалт", "недвижим", "автосалон", "нефт", "газ", "энергет",
    "агро", "машиностро", "судострой", "госзакуп", "тендер", "1с", "стажер",
    "стажёр", "junior", "младший", "ассистент", "помощник", "интерьер", "ландшафт",
    "水", "вахт", "механик", "сварщ", "буров", "шахт", "металлург", "пищев",
    "фитнес", "салон красоты", "образовательн программ", "мебел", "текстил",
    "typescript", "разработчик", "developer", "инженер-", "сметчик", "снабжен",
    "закупк", "логист", "таможен", "вэд", "туроператор",
]

DESC_POS = {
    "igaming": 14, "gambling": 12, "беттинг": 12, "казино": 10, "букмекер": 10,
    "affiliate": 14, "партнерск": 8, "партнёрск": 8, "cpa": 8,
    "gamedev": 12, "мобильных игр": 12, "игровой индустр": 10, "free-to-play": 12,
    "travel": 8, "тревел": 8, "туризм": 6,
    "martech": 14, "adtech": 12, "attribution": 12, "атрибуц": 12,
    "appsflyer": 12, "adjust": 8, "amplitude": 8, "mixpanel": 8,
    "cdp": 10, "crm": 6, "customer data platform": 12,
    "data platform": 12, "дата-платформ": 12, "хранилищ данных": 8, "dwh": 8,
    "etl": 6, "sql": 6, "bi": 4, "tableau": 4, "power bi": 4, "метабейс": 4,
    "api": 8, "интеграц": 8, "микросервис": 4, "вебхук": 4, "webhook": 4,
    "sla": 8, "инцидент": 8, "itil": 8, "мониторинг": 5, "алертинг": 5,
    "roadmap": 7, "роадмап": 7, "дорожн карт": 6, "бэклог": 6, "backlog": 6,
    "приоритизац": 8, "стейкхолдер": 8, "кросс-функционал": 8, "кроссфункционал": 8,
    "jira": 6, "confluence": 5, "agile": 4, "scrum": 4, "kanban": 4,
    "автоматизац": 7, "оптимизац процесс": 8, "регламент": 5, "процессн": 5,
    "метрик": 6, "дашборд": 5, "unit-эконом": 6, "юнит-эконом": 6,
    "продуктов команд": 6, "product owner": 5,
    "маркетинг": 5, "performance marketing": 8, "digital": 5,
    "saas": 5, "e-commerce": 5, "финтех": 3,
    "английск": 6, "english": 5, "международн команд": 8, "international": 5,
    "удаленн": 6, "удалённ": 6, "remote": 6, "релокац": 3,
}

DESC_NEG = {
    "1с": 12, "гост": 10, "снип": 14, "сметн": 14, "чертеж": 14, "autocad": 14,
    "строительн": 16, "монтажн": 14, "производственн площадк": 10, "цех": 10,
    "холодные звонк": 16, "план продаж": 14, "воронка продаж": 8, "выполнение kpi по продажам": 12,
    "госзакуп": 10, "44-фз": 14, "223-фз": 14, "тендерн": 10,
    "водительск": 12, "вахтов": 14, "личный автомобиль": 12,
}

# ============================================================
# 4. АРХЕТИПЫ, ДОМЕН, ГЕОГРАФИЯ — регулярные выражения
# ============================================================

# Порядок важен: от узких архетипов к широкому.
ARCHETYPES = [
    ("TRANS", [r"\bpmo\b", r"transformation", r"трансформац", r"проектного офиса", r"strategic"]),
    ("PERF", [r"enablement", r"sales operations", r"support operations", r"learning", r"customer success"]),
    ("TPM", [r"technical (project|program)", r"\btpm\b", r"техническ\w* (менеджер|проджект|руководител)", r"integration", r"интеграц", r"внедрени", r"martech", r"data platform", r"analytics manager", r"\bbi\b"]),
    ("OPS", [r"operation", r"операцион", r"product ops", r"business ops", r"partner ops", r"revenue ops", r"\bops\b"]),
    ("DEL", [r"project manager", r"менеджер\w* проект", r"руководител\w* проект", r"проджект", r"проектн\w* менеджер", r"delivery", r"program(me)? manager", r"scrum", r"скрам", r"agile coach", r"руководител\w* программ", r"проект", r"project", r"координатор", r"coordinator", r"\bpm\b"]),
]

ADJACENT_ROLE = [r"продаж", r"\bsales\b", r"аккаунт", r"account manager", r"партн[её]р", r"partner", r"affiliate", r"бизнес.?аналитик", r"business analyst"]

OPS_CONTENT = [r"процесс", r"интеграц", r"\bcrm\b", r"\bapi\b", r"отч[её]тн", r"\bsla\b", r"автоматизац", r"аналитик", r"данны[хм]", r"партн[её]рск\w* программ"]

COLD_SALES = [r"холодн\w* (звон|продаж)", r"обзвон", r"скрипт\w* продаж"]

DOMAIN = [r"igaming", r"gambling", r"беттинг", r"betting", r"казино", r"casino", r"affiliate", r"арбитраж", r"\bcpa\b", r"gamedev", r"геймдев", r"\bигр(ы|овой|овых|ах)\b", r"\bgames?\b", r"f2p", r"travel", r"туризм", r"путешеств", r"авиабилет", r"martech", r"adtech", r"performance.?маркет", r"digital.?маркет", r"\bdwh\b", r"data platform", r"data engineering"]

RELOC_COUNTRIES = [r"тбилиси", r"батуми", r"грузи[ия]", r"georgia", r"белград", r"серби[ия]", r"serbia", r"кипр", r"cyprus", r"лимассол", r"limassol", r"пафос", r"никоси"]

HOME_CITY = [r"санкт-петербург", r"петербург", r"\bспб\b", r"petersburg"]

SECOND_CITY = [r"москв", r"moscow"]

# ============================================================
# 5. ГЕОГРАФИЯ — очки за город и формат работы
# ============================================================
# Бакеты: home_city — основной город (HOME_CITY), second_city — второй (SECOND_CITY),
# reloc — страны из RELOC_COUNTRIES, region — прочие города РФ, foreign — прочие страны.
GEO_POINTS = {
    "home_city": 18,
    "second_city": -10,
    "second_city_office": -40,   # офис во втором городе — жёстко вниз
    "reloc": 18,
    "reloc_package": 12,         # в вакансии есть релокационный пакет
    "region": -25,
    "foreign": -25,
    "us_only": -40,
    "remote": 25,                # удалёнка снимает штраф города
    "hybrid": 4,
}
GEO_LABELS = {"home_city": "СПб", "second_city": "Москва", "reloc": "Грузия/Сербия/Кипр"}
