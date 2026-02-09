import json
import os
from functools import lru_cache

# путь к JSON конфигу
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "app_config.json")


@lru_cache
def get_app_config() -> dict:
    """
    Загружает конфиг версий приложения.
    Использует кеш, чтобы не читать файл каждый запрос.
    """

    if not os.path.exists(CONFIG_PATH):
        raise RuntimeError(f"Config file not found: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)