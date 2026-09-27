"""
Google-таблица личного поиска работы.

Две вкладки:
- «Вакансии» — всё, что ушло в чат. Кнопки «Откликаюсь / Не подходит» обновляют
  решение, причину и дату в строке по ID.
- «Забраковано ботом» — всё, что до чата не дошло (тир C, стоп-слово, фильтр), с причиной.
  Любое значение в колонке «Вернуть» — и на следующем цикле вакансия уходит в чат.

Без GOOGLE_SHEET_ID экспорт выключен: функции ничего не делают.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import gspread
from google.oauth2.service_account import Credentials

import config

logger = logging.getLogger(__name__)

VACANCIES_SHEET = "Вакансии"
REJECTED_SHEET = "Забраковано ботом"

VACANCY_HEADERS = [
    "ID", "Решение", "Причина", "Дата решения",
    "Тир", "Скор", "ATS", "Архетип", "Гео",
    "Вакансия", "Компания", "Вилка", "Формат", "Локация", "Источник", "Ссылка",
    "Опубликована", "Найдена", "Почему (бот)",
]
REJECTED_HEADERS = [
    "ID", "Вернуть", "Причина отказа бота",
    "Тир", "Скор", "ATS", "Архетип", "Гео",
    "Вакансия", "Компания", "Вилка", "Формат", "Локация", "Источник", "Ссылка",
    "Найдена", "Возвращена",
]
# Значения колонки «Вернуть», которые возвратом не считаются (пустой чекбокс даёт FALSE).
_NOT_RETURN = {"", "false", "нет", "0", "-"}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
_MSK = timezone(timedelta(hours=3))


def enabled() -> bool:
    return bool(config.GOOGLE_SHEET_ID)


def _gc():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
        gc = gspread.authorize(creds)
    else:
        gc = gspread.service_account(filename=config.GOOGLE_CREDENTIALS_FILE)
    # По умолчанию gspread ждёт ответа вечно: после сна Mac SSL_read повис на 36 часов
    # и держал цикл вместе с отправкой карточек.
    gc.http_client.set_timeout((10, 60))
    return gc


def _worksheet(name: str, headers: list[str]):
    spreadsheet = _gc().open_by_key(config.GOOGLE_SHEET_ID)
    try:
        sheet = spreadsheet.worksheet(name)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=name, rows=2000, cols=len(headers))
        logger.info("Создан лист: %s", name)
    if not sheet.row_values(1):
        sheet.append_row(headers)
    return sheet


def _now_msk() -> str:
    return datetime.now(_MSK).strftime("%d.%m.%Y %H:%M")


def _date(value) -> str:
    return str(value)[:10] if value else ""


def _salary(vacancy: dict) -> str:
    from bot.templates import _format_salary
    return _format_salary(vacancy) or ""


def scoring_dict(vacancy: dict) -> dict:
    scoring = vacancy.get("_scoring")
    if hasattr(scoring, "model_dump"):
        return scoring.model_dump()
    return scoring or {}


def _common(vacancy: dict, scoring: dict) -> dict:
    return {
        "ID": vacancy.get("id", ""),
        "Тир": scoring.get("tier", ""),
        "Скор": scoring.get("score", ""),
        "ATS": scoring.get("ats_score") or "",
        "Архетип": scoring.get("archetype", ""),
        "Гео": scoring.get("geo_bucket", ""),
        "Вакансия": vacancy.get("title", ""),
        "Компания": vacancy.get("company") or "",
        "Вилка": _salary(vacancy),
        "Формат": vacancy.get("work_format") or "",
        "Локация": vacancy.get("location") or "",
        "Источник": vacancy.get("source", ""),
        "Ссылка": vacancy.get("url", ""),
        "Опубликована": _date(vacancy.get("published_at")),
        "Найдена": _date(vacancy.get("parsed_at")),
    }


def vacancy_row(vacancy: dict, scoring: dict, headers: list[str],
                decision: str = "", reason: str = "", decided_at: str = "") -> list:
    data = _common(vacancy, scoring) | {
        "Решение": decision, "Причина": reason, "Дата решения": decided_at,
        "Почему (бот)": scoring.get("reason", ""),
    }
    return [data.get(h, "") for h in headers]


def rejected_row(vacancy: dict, scoring: dict, reason: str, headers: list[str]) -> list:
    data = _common(vacancy, scoring) | {"Причина отказа бота": reason, "Вернуть": "", "Возвращена": ""}
    return [data.get(h, "") for h in headers]


def _append_new(sheet, headers: list[str], rows: list[tuple]) -> int:
    """Добавляет строки, ID которых ещё нет на листе. rows = [(id, row)]."""
    id_col = headers.index("ID") + 1 if "ID" in headers else None
    existing = set(sheet.col_values(id_col)[1:]) if id_col else set()
    new = []
    for vacancy_id, row in rows:
        key = str(vacancy_id)
        if key and key not in existing:
            new.append(row)
            existing.add(key)
    if new:
        sheet.append_rows(new, value_input_option="USER_ENTERED")
    return len(new)


def export_to_sheets(vacancies: list[dict]) -> None:
    """«Вакансии»: то, что ушло в чат модерации."""
    if not enabled() or not vacancies:
        return
    try:
        sheet = _worksheet(VACANCIES_SHEET, VACANCY_HEADERS)
        headers = sheet.row_values(1)
        added = _append_new(sheet, headers, [
            (v.get("id"), vacancy_row(v, scoring_dict(v), headers)) for v in vacancies
        ])
        if added:
            logger.info("Добавлено в «%s»: %d", VACANCIES_SHEET, added)
    except Exception as exc:
        logger.error("Ошибка экспорта в «%s»: %s", VACANCIES_SHEET, exc)


def export_rejected_to_sheets(vacancies: list[dict]) -> None:
    """«Забраковано ботом»: тир C, стоп-слова и отсев фильтром — с причиной."""
    if not enabled() or not vacancies:
        return
    try:
        sheet = _worksheet(REJECTED_SHEET, REJECTED_HEADERS)
        headers = sheet.row_values(1)
        rows = []
        for v in vacancies:
            scoring = scoring_dict(v)
            reason = v.get("_reject_reason") or scoring.get("reason") or "тир C"
            rows.append((v.get("id"), rejected_row(v, scoring, reason, headers)))
        added = _append_new(sheet, headers, rows)
        if added:
            logger.info("Добавлено в «%s»: %d", REJECTED_SHEET, added)
    except Exception as exc:
        logger.error("Ошибка экспорта в «%s»: %s", REJECTED_SHEET, exc)


def _find_row(sheet, column: int, value: str):
    try:
        cell = sheet.find(value, in_column=column)
    except Exception as exc:  # gspread 5 бросает CellNotFound, gspread 6 возвращает None
        if type(exc).__name__ != "CellNotFound":
            raise
        cell = None
    return cell.row if cell else None


def update_decision(vacancy: dict, scoring: dict, decision: str, reason: str = "") -> None:
    """Решение из карточки → строка во «Вакансиях» (если строки нет — добавляем)."""
    if not enabled():
        return
    sheet = _worksheet(VACANCIES_SHEET, VACANCY_HEADERS)
    headers = sheet.row_values(1)
    decided_at = _now_msk()
    row_number = _find_row(sheet, headers.index("ID") + 1, str(vacancy["id"])) if "ID" in headers else None
    if row_number is None:
        sheet.append_row(vacancy_row(vacancy, scoring, headers, decision, reason, decided_at),
                         value_input_option="USER_ENTERED")
        return
    updates = [
        {"range": gspread.utils.rowcol_to_a1(row_number, headers.index(name) + 1), "values": [[value]]}
        for name, value in (("Решение", decision), ("Причина", reason), ("Дата решения", decided_at))
        if name in headers
    ]
    if updates:
        sheet.batch_update(updates, value_input_option="USER_ENTERED")


def returns_from_values(values: list[list[str]]) -> tuple[list[int], list[int]]:
    """Разбор листа «Забраковано ботом»: (ID к возврату, номера строк для отметки «Возвращена»)."""
    if not values:
        return [], []
    headers = values[0]
    if not {"ID", "Вернуть", "Возвращена"} <= set(headers):
        return [], []
    col = {h: i for i, h in enumerate(headers)}

    def cell(row, name):
        i = col[name]
        return row[i].strip() if i < len(row) else ""

    ids, rows = [], []
    for number, row in enumerate(values[1:], start=2):
        wants = cell(row, "Вернуть").lower() not in _NOT_RETURN
        if wants and not cell(row, "Возвращена") and cell(row, "ID").isdigit():
            ids.append(int(cell(row, "ID")))
            rows.append(number)
    return ids, rows


def pull_returns() -> list[int]:
    """ID вакансий, отмеченных «Вернуть»; отмечает их «Возвращена», чтобы не вернуть дважды."""
    if not enabled():
        return []
    sheet = _worksheet(REJECTED_SHEET, REJECTED_HEADERS)
    values = sheet.get_all_values()
    ids, rows = returns_from_values(values)
    if rows:
        column = values[0].index("Возвращена") + 1
        stamp = _now_msk()
        sheet.batch_update(
            [{"range": gspread.utils.rowcol_to_a1(r, column), "values": [[stamp]]} for r in rows],
            value_input_option="USER_ENTERED",
        )
        logger.info("Возвращено из «%s»: %d", REJECTED_SHEET, len(ids))
    return ids
