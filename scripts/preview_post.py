"""
Превью поста: показывает как выглядит шаблон на реальных данных.
Запуск: poetry run python preview_post.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from bot.templates import format_ru

# Тестовые вакансии — разные комбинации заполненности полей
EXAMPLES = [
    {
        "title": "UX Researcher",
        "company": "Яндекс",
        "location": "Москва",
        "work_format": "Гибрид",
        "salary_min": 200000,
        "salary_max": 280000,
        "currency": "RUR",
        "url": "https://hh.ru/vacancy/123456",
        "snippet": "Проведение качественных и количественных исследований. Работа с продуктовыми командами. | Опыт от 3 лет в UX-исследованиях, знание методов интервью и юзабилити-тестирования.",
    },
    {
        "title": "Product Researcher",
        "company": "Тинькофф",
        "location": "Санкт-Петербург",
        "work_format": "Удалёнка",
        "salary_min": 150000,
        "salary_max": None,
        "currency": "RUR",
        "url": "https://hh.ru/vacancy/234567",
        "snippet": "Исследование потребностей пользователей, анализ клиентского пути. | ",
    },
    {
        "title": "CX Researcher",
        "company": "Сбер",
        "location": "Москва",
        "work_format": None,
        "salary_min": None,
        "salary_max": None,
        "currency": None,
        "url": "https://hh.ru/vacancy/345678",
        "snippet": "",
    },
]

SEP = "─" * 40

for i, vacancy in enumerate(EXAMPLES, 1):
    print(f"\nПример {i}:")
    print(SEP)
    # Убираем HTML-теги для читаемости в терминале
    text = format_ru(vacancy)
    text = text.replace("<b>", "").replace("</b>", "")
    text = text.replace('<a href="' + vacancy["url"] + '">', "").replace("</a>", "")
    print(text)
    print(SEP)
