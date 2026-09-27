"""
Открывает браузер, даёт залогиниться через Google, сохраняет cookies.
Запуск: python gen_hirify_cookies.py
"""

import json
from playwright.sync_api import sync_playwright

BASE_URL = "https://hirify.me"


def main():
    print("Открываю браузер. Залогинься через Google, затем вернись сюда и нажми Enter.")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(BASE_URL)

        input("\nНажми Enter когда залогинишься в Hirify...")

        cookies = ctx.cookies()
        browser.close()

    cookie_str = json.dumps(cookies)
    print("\n=== Скопируй это значение в Railway как HIRIFY_COOKIES ===\n")
    print(cookie_str)
    print("\n=== Конец ===\n")


if __name__ == "__main__":
    main()
