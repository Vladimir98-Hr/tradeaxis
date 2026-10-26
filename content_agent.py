"""
Фоновый "агент статей" — раз в сутки генерирует через DeepSeek черновик
статьи о психологии трейдера (см. deepseek.py) и сохраняет его в БД для
просмотра админом (см. draft_routes.py). Ротация темы — по кругу, без
повторов, пока список не закончится, затем заново.
"""

import asyncio
import logging
import random

from config import DEEPSEEK_API_KEY
from database import async_session, ArticleDraft
from deepseek import generate_article

logger = logging.getLogger(__name__)

TOPICS = [
    "Страх упустить прибыль (FOMO) и как он разрушает торговый план",
    "Почему трейдеры отменяют стоп-лосс в последний момент",
    "Переторговка после серии убыточных сделок",
    "Эйфория после удачной сделки и её влияние на следующий вход",
    "Как отличить интуицию от самообмана при принятии торгового решения",
    "Месть рынку: откуда берётся revenge trading и как его остановить",
    "Перфекционизм в трейдинге — враг последовательности",
    "Почему просадка на счёте бьёт по уверенности сильнее, чем кажется",
    "Синдром самозванца у начинающего трейдера",
    "Как вести дневник сделок, чтобы он помогал психике, а не только статистике",
    "Жадность против дисциплины: конфликт на уровне одного решения",
    "Привязанность к цене входа и неумение признать ошибку",
    "Как долгие серии прибыли расслабляют риск-менеджмент",
    "Паралич анализа: когда слишком много индикаторов мешают решиться",
    "Эмоциональное восстановление после крупного убытка",
    "Сравнение себя с другими трейдерами в сообществах — польза и вред",
    "Почему трейдеру важно разделять личность и результат одной сделки",
    "Выгорание от постоянного мониторинга графиков",
    "Торговля на отыгрыш: как одна эмоция тащит за собой пять ошибок",
    "Как формируется торговая дисциплина — привычка, а не воля",
    "Ложное чувство контроля при торговле на новостях",
    "Почему пауза после убытка эффективнее, чем немедленный новый вход",
    "Психология риска: чем отличается осознанный риск от азарта",
    "Как ожидания от трейдинга (быстрые деньги) разрушают терпение",
    "Групповое мышление в чатах трейдеров и потеря своей стратегии",
]

_used_topics: list[str] = []


def _next_topic() -> str:
    """Следующая тема по кругу без повторов, пока список не закончится."""
    available = [t for t in TOPICS if t not in _used_topics]
    if not available:
        _used_topics.clear()
        available = TOPICS
    topic = random.choice(available)
    _used_topics.append(topic)
    return topic


async def generate_one_draft() -> ArticleDraft:
    """Генерирует один черновик и сохраняет его в БД. Используется и фоновым циклом, и ручным запросом админа."""
    topic = _next_topic()
    content = await generate_article(topic)
    async with async_session() as session:
        draft = ArticleDraft(topic=topic, content=content)
        session.add(draft)
        await session.commit()
        await session.refresh(draft)
        return draft


async def run_article_draft_generator() -> None:
    """Фоновый цикл: один черновик в сутки."""
    if not DEEPSEEK_API_KEY:
        return
    while True:
        try:
            await generate_one_draft()
        except Exception:
            logger.warning("article draft generation failed", exc_info=True)
        await asyncio.sleep(24 * 3600)
