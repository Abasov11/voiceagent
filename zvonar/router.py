"""FastAPI router AI-звонаря.

Эндпоинты, которые дёргает Voximplant VoxEngine сценарий:
  POST /zvonar/dialogue/turn   — следующая реплика на основе userSpeech
  POST /zvonar/dialogue/finish — финальный outcome звонка

И служебные:
  POST /zvonar/dial            — поставить лид в очередь обзвона (admin only — добавим позже)

Стейт диалога живёт в process-local dict, key=session_id (Voximplant
session длится ≤15 минут, помещается в одного uvicorn-воркера).
Если масштабируемся на несколько воркеров — выносим в Redis.
"""
from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from shared.alfacrm_push import push_outcome
from shared.db import db_session, get_db
from shared import elevenlabs_client
from shared.green_api import GreenApiClient
from shared.models import ApiCallLog, CallOutcome, Lead, ZvonarCall
from shared.settings import get_settings
from shared.whatsapp_template import WhatsAppContext, render_lead_message
from zvonar.prompts import Stage, stage_instruction, system_prompt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/zvonar", tags=["zvonar"])


class TurnIn(BaseModel):
    lead_id: int
    session_id: str
    turn: int
    user_speech: str


class TurnOut(BaseModel):
    text: str
    audio_url: str | None = None
    outcome: str | None = None
    hangup: bool = False


class FinishIn(BaseModel):
    lead_id: int
    session_id: str
    outcome: str
    code: int = 0
    failure_class: str | None = None
    error: str | None = None


def _check_token(x_token: str | None) -> None:
    expected = get_settings().secret_key
    if not x_token or x_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad token")


# Process-local стейт диалога: session_id → {stage, qualify_count, history, lead}
_SESSIONS: dict[str, dict[str, Any]] = {}

# Эвристики триггеров — ровно как в zvonar.simulate, чтобы поведение совпадало.
# Внимание: «перезвоните» НЕ refusal, а callback — клиент просит перенести
# звонок, не отказывается. Все формы («перезвонит», «перезвоните», «перезвонить»)
# ловятся подстрокой «перезвонит» в _BUSY_WORDS.
_REFUSAL_WORDS = ("не интересно", "не нужно", "не звоните", "до свидания")
_OBJECTION_WORDS = ("дорого", "далеко", "подумаем", "сомневаюсь", "не уверен")
_BUSY_WORDS = ("за рулем", "за рулём", "позже", "перезвонит")


def _next_stage(current: Stage, client_text: str, qualify_count: int) -> Stage:
    t = client_text.lower()
    if any(w in t for w in _REFUSAL_WORDS):
        return "goodbye"
    if any(w in t for w in _OBJECTION_WORDS):
        return "objection"
    transitions: dict[Stage, Stage] = {
        "greet": "confirm_request",
        "confirm_request": "qualify",
        "qualify": "qualify" if qualify_count < 5 else "present",
        "present": "close",
        "objection": "close",
        "close": "goodbye",
        "goodbye": "goodbye",
    }
    return transitions.get(current, "goodbye")


def _outcome_for_stage(stage: Stage, client_text: str) -> str | None:
    t = client_text.lower()
    if any(w in t for w in _REFUSAL_WORDS):
        return CallOutcome.not_interested.value
    if any(w in t for w in _BUSY_WORDS):
        return CallOutcome.callback.value
    if stage == "goodbye":
        return CallOutcome.interested.value
    return None


def _natural_fallback(stage: Stage, qualify_count: int) -> str:
    """Натуральные реплики на случай отсутствия OpenAI-ключа или его падения.

    На прод ВСЕГДА должен быть LLM; это safety net чтобы клиент не услышал
    мета-инструкцию вида «Задай следующий вопрос…».
    """
    if stage == "greet":
        return (
            "Здравствуйте! Меня зовут Камила, звоню с детской футбольной "
            "школы Олимп. Удобно ли минуту поговорить?"
        )
    if stage == "confirm_request":
        return (
            "Вы оставляли заявку на футбольную секцию для ребёнка? "
            "Хочу уточнить пару моментов и записать на пробную."
        )
    if stage == "qualify":
        questions = [
            "Скажите, ребёнок раньше тренировался?",
            "Сколько лет ребёнку и в каком районе вы живёте?",
            "В какое время удобнее — утром, вечером или после обеда?",
            "Когда хотели бы прийти на пробную тренировку?",
            "Расскажите, почему решили отдать на футбол?",
        ]
        idx = max(0, min(qualify_count, len(questions) - 1))
        return questions[idx]
    if stage == "present":
        return (
            "Понятно. Подберу подходящий филиал и время — тренер свяжется "
            "с вами для подтверждения. Подскажите, WhatsApp на этом номере?"
        )
    if stage == "objection":
        return (
            "Понимаю Вас. Первая тренировка у нас бесплатная — давайте "
            "запишу, посмотрите, а потом уже решите. Хорошо?"
        )
    if stage == "close":
        return (
            "Записала. Тренер свяжется в ближайшее время для подтверждения, "
            "адрес и расписание пришлю в WhatsApp на этот же номер. "
            "Хорошего дня!"
        )
    if stage == "goodbye":
        return "Спасибо за разговор, хорошего Вам дня!"
    return "Спасибо."


def _llm_or_stub(
    stage: Stage,
    history: list[dict],
    client_name: str | None,
    qualify_count: int,
) -> str:
    """Вернёт реплику агента — LLM если есть ключ, иначе натуральный fallback."""
    s = get_settings()
    if not s.openai_api_key:
        return _natural_fallback(stage, qualify_count)
    try:
        from openai import OpenAI

        client = OpenAI(api_key=s.openai_api_key)
        sys_text = (
            system_prompt(client_name)
            + f"\n\nТекущая стадия диалога: {stage}\n"
            + stage_instruction(stage)
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": sys_text}]
        messages.extend(history if history else [{"role": "user", "content": "(start)"}])
        resp = client.chat.completions.create(
            model=s.llm_short_model,
            max_tokens=180,
            messages=messages,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        log.warning("zvonar llm_fail stage=%s err=%s — natural fallback", stage, exc)
        return _natural_fallback(stage, qualify_count)


async def _synthesize_audio(text: str) -> str | None:
    s = get_settings()
    if not (s.elevenlabs_api_key and s.elevenlabs_voice_id):
        log.warning("elevenlabs not configured — returning text-only reply")
        return None
    try:
        audio_dir = Path(s.tts_audio_dir)
        audio_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = await elevenlabs_client.synthesize(
            text, api_key=s.elevenlabs_api_key, voice_id=s.elevenlabs_voice_id,
        )
        fname = f"{uuid.uuid4().hex}.mp3"
        dest = audio_dir / fname
        shutil.move(str(tmp_path), str(dest))
        dest.chmod(0o644)
        return f"{s.dashboard_base_url}{s.tts_audio_url_prefix}/{fname}"
    except Exception as exc:
        log.error("elevenlabs synth failed: %s", exc)
        return None


@router.post("/dialogue/turn", response_model=TurnOut)
async def dialogue_turn(
    payload: TurnIn,
    x_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> TurnOut:
    _check_token(x_token)
    sess = _SESSIONS.setdefault(
        payload.session_id,
        {"stage": "greet", "qualify_count": 0, "history": [], "lead_id": payload.lead_id},
    )

    lead = db.get(Lead, payload.lead_id)
    client_name = getattr(lead, "name", None) if lead else None

    # Семантика sess["stage"] = «стадия, на которой агент ГОВОРИТ ЭТУ РЕПЛИКУ».
    # После того как реплика сказана — обновляем sess["stage"] на следующую.

    # Turn 0 — приветствие, user_speech ещё нет.
    if payload.turn == 0:
        text = _llm_or_stub("greet", [], client_name, 0)
        sess["history"].append({"role": "assistant", "content": text})
        sess["stage"] = "confirm_request"
        audio_url = await _synthesize_audio(text)
        return TurnOut(text=text, audio_url=audio_url, outcome=None, hangup=False)

    # Turn N>0: получили реплику клиента. Решаем, что говорить дальше.
    sess["history"].append({"role": "user", "content": payload.user_speech})
    text_lc = payload.user_speech.lower()

    # Override по триггерам в речи клиента — кроме самых первых стадий,
    # где «дорого/далеко/подумаем» ещё не имеет смысла.
    if any(w in text_lc for w in _REFUSAL_WORDS):
        sess["stage"] = "goodbye"
    elif any(w in text_lc for w in _OBJECTION_WORDS) and sess["stage"] not in (
        "greet", "confirm_request", "goodbye"
    ):
        sess["stage"] = "objection"

    current_stage: Stage = sess["stage"]
    text = _llm_or_stub(current_stage, sess["history"], client_name, sess["qualify_count"])
    sess["history"].append({"role": "assistant", "content": text})
    outcome = _outcome_for_stage(current_stage, payload.user_speech)

    # Продвигаемся к следующей стадии.
    if current_stage == "qualify":
        sess["qualify_count"] += 1
        if sess["qualify_count"] >= 5:
            sess["stage"] = "present"
        # иначе остаёмся на "qualify" и зададим следующий вопрос
    else:
        sess["stage"] = _next_stage(current_stage, payload.user_speech, sess["qualify_count"])

    hangup = current_stage == "goodbye"
    if hangup:
        _SESSIONS.pop(payload.session_id, None)

    audio_url = await _synthesize_audio(text)
    return TurnOut(text=text, audio_url=audio_url, outcome=outcome, hangup=hangup)


@router.post("/dialogue/finish")
def dialogue_finish(
    payload: FinishIn,
    background: BackgroundTasks,
    x_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _check_token(x_token)
    lead = db.get(Lead, payload.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="lead not found")
    if payload.outcome not in {o.value for o in CallOutcome}:
        outcome = CallOutcome.error.value
    else:
        outcome = payload.outcome
    raw: dict[str, Any] = {}
    if payload.failure_class:
        raw["failure_class"] = payload.failure_class
    if payload.error:
        raw["error"] = payload.error[:1024]
    # Сохраняем транскрипт диалога если он лежал в process-local стейте.
    sess = _SESSIONS.pop(payload.session_id, None)
    transcript = None
    if sess and sess.get("history"):
        transcript = "\n".join(
            f"{m['role']}: {m['content']}" for m in sess["history"]
        )[:8000]
    z = ZvonarCall(
        lead_id=lead.id,
        voximplant_session_id=payload.session_id,
        started_at=datetime.now(timezone.utc),
        duration_s=0,
        outcome=outcome,
        transcript=transcript,
        raw=raw or None,
    )
    if outcome == CallOutcome.interested.value:
        lead.interested = True
    db.add(z)
    db.commit()
    log.info(
        "zvonar finish: lead=%s outcome=%s session=%s code=%s class=%s",
        lead.id, outcome, payload.session_id, payload.code, payload.failure_class,
    )
    if get_settings().alfa_crm_push_outcome:
        background.add_task(push_outcome, z.id)
    if outcome == CallOutcome.interested.value:
        background.add_task(send_interested_whatsapp, lead.id)
    return {"status": "ok", "zvonar_call_id": z.id, "failure_class": payload.failure_class}


async def send_interested_whatsapp(lead_id: int) -> None:
    """Шлёт лиду WhatsApp-сообщение после звонка с outcome=interested.

    Запускается background-задачей из `/zvonar/dialogue/finish`. Если Green
    API не сконфигурирован — пишет ApiCallLog(status=skipped) и выходит.
    Сетевые ошибки ловятся и пишутся в ApiCallLog(status=error), исключения
    наружу не пробрасываются — это пост-процесс, не должен ломать ответ.
    """
    s = get_settings()
    with db_session() as db:
        lead = db.get(Lead, lead_id)
        if not lead:
            log.warning("whatsapp dispatch: lead %s not found", lead_id)
            return

        phone_tail = (lead.phone or "")[-4:] or None

        if not (s.green_api_instance_id and s.green_api_token):
            log.info("whatsapp dispatch skipped (no green api creds), lead=%s", lead_id)
            db.add(ApiCallLog(
                provider="greenapi",
                operation="send_message",
                status="skipped",
                request={"lead_id": lead_id, "reason": "no creds"},
            ))
            return

        text = render_lead_message(WhatsAppContext(lead_name=lead.name))
        client = GreenApiClient(s.green_api_instance_id, s.green_api_token)
        try:
            resp = await client.send_message(phone=lead.phone, text=text)
        except Exception as exc:
            log.error("whatsapp send failed for lead=%s: %s", lead_id, exc)
            db.add(ApiCallLog(
                provider="greenapi",
                operation="send_message",
                status="error",
                error=str(exc)[:2048],
                request={"lead_id": lead_id, "phone_tail": phone_tail},
            ))
            return
        finally:
            await client.aclose()

        db.add(ApiCallLog(
            provider="greenapi",
            operation="send_message",
            status="ok",
            request={"lead_id": lead_id, "phone_tail": phone_tail},
            response={"idMessage": resp.get("idMessage")},
        ))
        log.info("whatsapp sent to lead=%s", lead_id)
