# CloudGallery API

Галерея с проверкой изображений и заменяемым локальным/S3-хранилищем.

Локальный режим не требует аккаунта. Скопируй `.env.example` в `.env` и запусти:

```bash
uv sync --frozen --dev
uv run fastapi dev app/main.py
```

Реальные S3-ключи храни только в `.env`. Проверка: `uv run pytest`.
