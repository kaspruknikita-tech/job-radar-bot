"""
Запускается ОДИН РАЗ локально для получения TG_SESSION_STRING.
Полученную строку вставить в переменную окружения TG_SESSION_STRING на Railway.

Запуск:
    python gen_tg_session.py
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("TG_API_ID: ").strip())
api_hash = input("TG_API_HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    session_string = client.session.save()

print("\nСкопируй строку ниже в TG_SESSION_STRING на Railway:\n")
print(session_string)
