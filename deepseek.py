"""
Простой клиент для DeepSeek API (OpenAI-совместимый формат) —
используется только для генерации черновиков статей (см. content_agent.py).
"""

import httpx
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

SYSTEM_PROMPT = (
    "Ты — соавтор статей о психологии и психике трейдера для блога на "
    "торговой платформе и для Дзен-канала. Автор — практик, не профессиональный "
    "психолог, поэтому: проверяй термины, объясняй простыми словами, избегай "
    "клише вроде «контролируйте эмоции» без конкретики, давай примеры и "
    "практические приёмы. Пиши живым языком, без заголовков-кликбейта. "
    "Статья должна быть самодостаточной: с заголовком и текстом, объёмом "
    "примерно 600-900 слов."
)


async def generate_article(topic: str) -> str:
    """Генерирует текст статьи по теме через DeepSeek chat completions."""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY не задан")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Напиши статью на тему: {topic}"},
                ],
                "temperature": 1.0,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
