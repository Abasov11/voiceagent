"""Сборка текста WhatsApp-сообщения из редактируемых блоков и активных акций.

Контент берётся из тех же `content_blocks` (scope=whatsapp) и
`promotions` (scope=whatsapp), что и в звонке. Клиент через `/admin/*`
управляет содержимым в одном месте, а WhatsApp и звонарь автоматически
подхватывают.

Используется `shared.green_api.GreenApiClient.send_message(text=...)`.
Фоллбэк-шаблон жёстко зашит здесь — на случай если клиент удалил всё.
"""
from __future__ import annotations

from dataclasses import dataclass

from shared import agent_config


@dataclass
class WhatsAppContext:
    lead_name: str | None = None
    branch_address: str | None = None
    trial_when: str | None = None  # человекочитаемая строка, e.g. "в четверг в 17:00"


def _greeting(ctx: WhatsAppContext, agent_name: str, school_name: str) -> str:
    name = (ctx.lead_name or "").strip()
    salutation = f"Здравствуйте, {name}!" if name else "Здравствуйте!"
    return (
        f"{salutation} Это {agent_name} из детской футбольной школы "
        f"{school_name}, мы только что разговаривали."
    )


def _trial_block(ctx: WhatsAppContext) -> str:
    parts: list[str] = []
    if ctx.trial_when:
        parts.append(f"Записали Вас на пробную тренировку: {ctx.trial_when}.")
    if ctx.branch_address:
        parts.append(f"Адрес: {ctx.branch_address}.")
    if not parts:
        parts.append("Напомните, пожалуйста, удобное время — и мы запишем Вас на пробную.")
    return " ".join(parts)


def _format_promos(promos) -> str:
    if not promos:
        return ""
    lines = ["📣 Сейчас у нас:"]
    for p in promos:
        lines.append(f"• {p.title}")
        body = (p.body or "").strip()
        if body:
            lines.append(f"  {body}")
    return "\n".join(lines)


def _format_blocks(blocks) -> str:
    if not blocks:
        return ""
    return "\n\n".join(b.body.strip() for b in blocks if b.body.strip())


def render_lead_message(ctx: WhatsAppContext | None = None) -> str:
    """Собирает финальный текст WhatsApp-сообщения для тёплого лида.

    Структура:
      1. Приветствие (имя клиента + имя агента + школа)
      2. Trial-блок (когда/где пробная) — если данные есть
      3. content_blocks scope=whatsapp (например, product_facts)
      4. Активные promotions scope=whatsapp
      5. Закрывающая фраза
    """
    ctx = ctx or WhatsAppContext()

    agent_name = agent_config.get_setting("agent_name", "Камила")
    school_name = agent_config.get_setting("school_name", "Олимп")

    blocks = agent_config.get_blocks(scope="whatsapp")
    promos = agent_config.get_active_promotions(scope="whatsapp")

    sections = [
        _greeting(ctx, agent_name, school_name),
        _trial_block(ctx),
        _format_blocks(blocks),
        _format_promos(promos),
        "Если будут вопросы — напишите сюда, ответим.",
    ]
    return "\n\n".join(s for s in sections if s and s.strip())
