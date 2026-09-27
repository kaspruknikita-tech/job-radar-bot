"""
Шаблоны постов для Telegram-каналов.
Формат: HTML (Telegram parse_mode="HTML").
"""

import html
import re
from urllib.parse import urlparse

_LLM_LABEL_RE = re.compile(
    r"^\s*(tl;?dr|summary|overview|about the role|о роли|резюме)\s*[:\-–]?\s*\n*",
    re.IGNORECASE,
)

from bs4 import BeautifulSoup


def _safe_url(url: str) -> str:
    try:
        scheme = urlparse(url).scheme
        if scheme not in ("http", "https"):
            return "#"
    except Exception:
        return "#"
    return html.escape(url, quote=True)


def _normalize(text: str) -> str:
    """Заменяет типографские апострофы/кавычки на ASCII для сравнения."""
    return text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')

CURRENCY_SYMBOLS = {
    "RUR": "₽",
    "RUB": "₽",
    "USD": "$",
    "EUR": "€",
    "KZT": "₸",
    "BYR": "Br",
    "BYN": "Br",
    "UAH": "₴",
    "GEL": "₾",
}


def _format_salary(vacancy: dict) -> str | None:
    sal_min = vacancy.get("salary_min")
    sal_max = vacancy.get("salary_max")
    currency_code = (vacancy.get("currency") or "").upper()
    currency = CURRENCY_SYMBOLS.get(currency_code, currency_code)

    def fmt(n: int) -> str:
        return f"{n:,}".replace(",", " ")

    if sal_min and sal_max:
        return f"{fmt(sal_min)} — {fmt(sal_max)} {currency}".strip()
    if sal_min:
        return f"от {fmt(sal_min)} {currency}".strip()
    if sal_max:
        return f"до {fmt(sal_max)} {currency}".strip()
    return None


def _first_sentence(text: str, max_len: int = 200) -> str:
    cut = text[:max_len]
    dot = cut.rfind(". ")
    if dot > 60:
        return cut[:dot + 1]
    return cut


_ICON_RE = re.compile(r"\s*_[a-z][a-z_]*_\s*")


def _clean(text: str) -> str:
    """Removes Material Design / Adzuna icon tokens like _place_, _corporate_fare_."""
    return _ICON_RE.sub(" ", text).strip()


def _smart_bullet(text: str) -> str:
    return _clean(text)


def _parse_sections(raw_html: str) -> dict:
    """Разбирает HTML на секции: intro + именованные разделы с буллетами.
    Если HTML-структуры нет (plain text) — возвращает текст как intro."""
    if not raw_html:
        return {}

    # Greenhouse stores descriptions as pre-escaped HTML entities (&lt;p&gt; instead of <p>)
    if "&lt;" in raw_html and "<" not in raw_html:
        import html as _html
        raw_html = _html.unescape(raw_html)

    soup = BeautifulSoup(raw_html, "html.parser")

    # Adzuna оборачивает контент в <section> или <div> — заходим внутрь
    top_tags = [c for c in soup.children if hasattr(c, "name") and c.name]
    root = top_tags[0] if len(top_tags) == 1 and top_tags[0].name in ("section", "div", "article") else soup

    def _iter_blocks(node):
        """Плоский итератор: рекурсивно заходит в div/article/section-обёртки."""
        for child in node.children:
            if not hasattr(child, "name"):
                yield child
                continue
            if child.name in ("div", "article", "section"):
                yield from _iter_blocks(child)
            else:
                yield child

    sections = {}
    current = None
    intro = ""

    for tag in _iter_blocks(root):
        if not hasattr(tag, "name"):
            continue

        # Текстовая нода — заголовок или буллет-пункт через символ ●/•
        if tag.name is None:
            text = str(tag).strip()
            if not text:
                continue
            if text[0] in "●•·◦▪▸►★":
                # Символьный буллет (Adzuna и др.) — добавляем как пункт в текущую секцию
                if current is not None:
                    item = text.lstrip("●•·◦▪▸►★ ").strip().rstrip(";.")
                    if item and len(item) > 3:
                        sections[current].append(item)
            elif len(text) < 80 and not text.endswith("?") and text not in sections:
                current = text.rstrip(":")
                sections[current] = []
            continue

        if tag.name in ("h2", "h3", "h4", "h5", "h6"):
            text = tag.get_text().strip().rstrip(":")
            # Заголовки с ! — тегслоганы (напр. "Help shape...!"), не разделы
            if text and len(text) < 80 and not text.endswith("!"):
                current = text
                sections[current] = []

        elif tag.name == "p":
            strong = tag.find("strong") or tag.find("b")
            text = tag.get_text().strip()
            if not text:
                continue
            is_header = (strong and len(text) <= 60) or text.endswith(":")
            if is_header:
                current = text.rstrip(":")
                sections[current] = []
            elif current:
                # Контентный параграф внутри секции (Arbeitnow, WeWorkRemotely и др.)
                if not text.endswith("?") and len(text) > 20:
                    sections[current].append(text)
            elif not intro and len(text) >= 40 and not text.endswith("?") and not text.startswith("*") and not text.startswith("-"):
                intro = _first_sentence(text)

        elif tag.name in ("strong", "b"):
            # Голый <strong>/<b> без <p> — заголовок раздела
            text = tag.get_text().strip().rstrip(":")
            if text and len(text) < 80:
                current = text
                sections[current] = []

        elif tag.name in ("ul", "ol") and current:
            for li in tag.find_all("li", recursive=False):
                text = li.get_text().strip()
                if text:
                    sections[current].append(text)

    if intro:
        sections["__intro__"] = intro
    elif not any(v for k, v in sections.items() if k == "__intro__"):
        # Если intro не нашли явно — берём первый длинный параграф из любой секции
        for k, items in sections.items():
            if items and len(items[0]) >= 80:
                sections["__intro__"] = _first_sentence(items[0])
                sections[k] = items[1:]  # убираем его из секции чтобы не дублировать
                break

    if not sections:
        # Plain text без HTML-структуры (например, Adzuna)
        plain = soup.get_text(" ", strip=True)
        if plain:
            sections["__intro__"] = _first_sentence(plain)

    return sections


def _expand_bullets(items: list) -> list:
    """Split items that use ● as inline sub-bullets (hh.ru style)."""
    out = []
    for item in items:
        if "●" in item:
            out.extend(p.strip() for p in item.split("●") if p.strip())
        else:
            out.append(item)
    return out


def _fmt_bullets(items: list, n: int = 6) -> str:
    return "\n".join("— " + _smart_bullet(i) for i in _expand_bullets(items)[:n])


def _fmt_conditions(items: list, n: int = 6) -> str:
    return "\n".join("— " + i.strip().rstrip(";.") for i in _expand_bullets(items)[:n])


def _build_post(vacancy: dict, apply_label: str, is_ru: bool, enrichment: dict | None = None) -> str:
    title = html.escape(vacancy.get("title") or "")
    company = html.escape(vacancy.get("company") or "")
    location = html.escape(vacancy.get("location") or "")
    work_format = html.escape(vacancy.get("work_format") or "")

    header = f"<b>{title}</b>"
    if company:
        header += f" в {company}" if is_ru else f" at {company}"

    lines = [header, ""]

    info_parts = [p for p in [work_format, location] if p]
    if info_parts:
        lines.append("📍 " + " · ".join(info_parts))

    salary = _format_salary(vacancy)
    if not salary and enrichment and enrichment.get("formatted_salary"):
        salary = enrichment["formatted_salary"]
    if salary:
        lines.append(f"💰 {salary}")

    description = vacancy.get("description") or ""
    snippet = vacancy.get("snippet") or ""

    if description:
        sections = _parse_sections(description)

        intro = sections.get("__intro__")
        if not intro and enrichment and enrichment.get("summary"):
            summary = enrichment["summary"]
            if "<" in summary:
                summary = BeautifulSoup(summary, "html.parser").get_text(strip=True)
            intro = _LLM_LABEL_RE.sub("", summary).strip()
        if intro:
            lines += ["", f"<b>{'О роли' if is_ru else 'About the role'}</b>", html.escape(_clean(intro))]

        tasks_key = next((k for k in sections if k != "__intro__" and
                          any(w in _normalize(k.lower()) for w in [
                              "обязанност", "задач", "responsi", "duties",
                              "нужно будет делать", "будете делать", "нужно делать",
                              "что делать", "функции", "чем предстоит",
                              "что предстоит", "тебе предстоит", "вам предстоит",
                              "что ты будешь делать", "что вы будете делать",
                              "о вакансии",
                              "what you'll do", "what you will do", "you will be responsible",
                              "what you'll be doing", "you'll be doing", "you will be doing",
                              "what you'll focus", "focus on", "you will focus",
                              "role overview", "the role", "your role",
                              "ищем специалист", "ищем кандидат", "который будет",
                          ])), None)
        reqs_key = next((k for k in sections if k != "__intro__" and k != tasks_key and
                         any(w in _normalize(k.lower()) for w in [
                             "требован", "require", "qualif", "опыт",
                             "нам важно", "для нас важно", "что важно",
                             "ожидаем", "наши ожидания", "нам нужен", "нам нужна",
                             "идеальный кандидат", "вы наш", "если у вас",
                             "нам подойдёт", "нам подойдет",
                             "кого мы ищем", "кого ищем",
                             "будет плюсом", "будет преимуществом",
                             "знания и навык", "необходимые знания",
                             "мы ждем от", "мы ждём от", "ждем от тебя", "ждём от тебя",
                             "ждем от вас", "ждём от вас", "что ждем", "что ждём",
                             "для этого нужно", "что для этого",
                             "what we're looking for", "what we are looking for",
                             "what you'll need", "you'll need",
                             "what you bring", "you bring", "you should bring", "bring to the table",
                             "what you should", "should have", "ideally you",
                             "must have", "must-have", "essential", "requirements",
                             "to be successful", "about you", "who you are",
                         ])), None)
        cond_key = next((k for k in sections if k != "__intro__" and
                         any(w in _normalize(k.lower()) for w in [
                             "услови", "offer", "benefit", "мы предлага",
                             "предлагаем", "работа с нами", "у нас вы",
                             "что мы даём", "что даём", "что получите",
                             "what we offer", "perks", "compensation", "why join",
                             "highlights",
                         ])), None)

        tasks_items = (sections.get(tasks_key) or []) if tasks_key else []
        if len(tasks_items) < 2 and enrichment and enrichment.get("key_tasks"):
            tasks_items = enrichment["key_tasks"]
        if len(tasks_items) >= 2:
            lines += ["", f"<b>{'Задачи' if is_ru else 'Responsibilities'}</b>",
                      html.escape(_fmt_bullets(tasks_items))]

        reqs_items = (sections.get(reqs_key) or []) if reqs_key else []
        if len(reqs_items) < 2 and enrichment and enrichment.get("key_requirements"):
            reqs_items = enrichment["key_requirements"]
        if len(reqs_items) >= 2:
            lines += ["", f"<b>{'Требования' if is_ru else 'Requirements'}</b>",
                      html.escape(_fmt_bullets(reqs_items))]

        if cond_key and sections[cond_key]:
            lines += ["", f"<b>{'Условия' if is_ru else 'Benefits'}</b>",
                      html.escape(_fmt_conditions(sections[cond_key]))]
        elif enrichment and enrichment.get("key_benefits"):
            lines += ["", f"<b>{'Условия' if is_ru else 'Benefits'}</b>",
                      html.escape(_fmt_conditions(enrichment["key_benefits"]))]

    elif snippet:
        lines += ["", html.escape(snippet)]
    elif enrichment and enrichment.get("summary"):
        label = "О роли" if is_ru else "About the role"
        clean_summary = _LLM_LABEL_RE.sub("", enrichment["summary"]).strip()
        lines += ["", f"<b>{label}</b>", html.escape(clean_summary)]
        if enrichment.get("key_requirements"):
            reqs_label = "Требования" if is_ru else "Requirements"
            lines += ["", f"<b>{reqs_label}</b>",
                      html.escape(_fmt_bullets(enrichment["key_requirements"]))]
        if enrichment.get("key_benefits"):
            cond_label = "Условия" if is_ru else "Benefits"
            lines += ["", f"<b>{cond_label}</b>",
                      html.escape(_fmt_conditions(enrichment["key_benefits"]))]

    lines += ["", f'🔗 <a href="{_safe_url(vacancy["url"])}">{apply_label}</a>']

    return "\n".join(lines)


def format_ru(vacancy: dict, enrichment: dict | None = None) -> str:
    return _build_post(vacancy, "Откликнуться на hh.ru", is_ru=True, enrichment=enrichment)


def format_global(vacancy: dict, enrichment: dict | None = None) -> str:
    return _build_post(vacancy, "Apply", is_ru=False, enrichment=enrichment)
