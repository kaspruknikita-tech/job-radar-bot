"""
Общий low-level хелпер для Telegram Bot API через requests.
Маскирует токен в URL при логировании и в тексте исключений,
чтобы он не утекал в логи / Sentry / трейсбэки.
"""

from __future__ import annotations

import logging
import re
import time

import requests

import config

logger = logging.getLogger(__name__)

_TOKEN_IN_URL_RE = re.compile(r"/bot[^/]+/")
# Без VPN TLS-рукопожатие с api.telegram.org занимает 6–17 с (оно входит в таймаут подключения).
CONNECT_TIMEOUT = 30
READ_TIMEOUT = 30
CONNECT_RETRIES = 2


def _mask(text: str) -> str:
    """Заменяет /bot<TOKEN>/ на /bot***/."""
    return _TOKEN_IN_URL_RE.sub("/bot***/", text)


def call(method: str, **kwargs) -> dict:
    """POST в Telegram Bot API. Возвращает payload['result'] или бросает RuntimeError.
    В сообщении исключения токен замаскирован."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"
    resp = None
    for attempt in range(CONNECT_RETRIES + 1):
        try:
            resp = requests.post(url, json=kwargs, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            break
        except requests.ConnectionError as e:
            # Не подключились — запрос точно не ушёл, повтор безопасен.
            # ReadTimeout сюда не попадает: сообщение могло уйти, повтор дал бы дубль карточки.
            if attempt < CONNECT_RETRIES and not isinstance(e, requests.exceptions.ReadTimeout):
                logger.warning("Telegram [%s]: нет соединения, повтор %d", method, attempt + 1)
                time.sleep(2)
                continue
            raise RuntimeError(f"Telegram request failed [{method}]: {_mask(str(e))}") from None
        except requests.RequestException as e:
            raise RuntimeError(f"Telegram request failed [{method}]: {_mask(str(e))}") from None
    try:
        data = resp.json()
    except ValueError:
        body = (resp.text or "")[:200]
        raise RuntimeError(
            f"Telegram non-JSON response [{method}]: HTTP {resp.status_code} {body!r}"
        )
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error [{method}]: {data.get('description')}")
    return data
