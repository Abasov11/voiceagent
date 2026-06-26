"""CLI-симулятор диалога звонаря — позволяет итерировать промпты без Voximplant.

Без OPENAI_API_KEY работает в rule-based режиме: печатает stage_instruction.
С ключом — реально гонит через OpenAI (gpt-4.1-mini по умолчанию).

Запуск (внутри контейнера):
    docker exec -it voiceagent-backend python -m zvonar.simulate
    docker exec -it voiceagent-backend python -m zvonar.simulate --transcript tests/fixtures/dialog_interested.txt

Опции:
    --auto             — прогнать сценарий из transcript-файла без ручного ввода
    --transcript PATH  — путь к диалогу (формат `client: ...` / `agent: ...` построчно)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from shared.settings import get_settings
from zvonar.prompts import Stage, stage_instruction, system_prompt

STAGES: list[Stage] = [
    "greet", "confirm_request", "qualify", "present", "objection", "close", "goodbye"
]


async def _llm_reply(client_text: str, stage: Stage, history: list[dict]) -> str:
    s = get_settings()
    if not s.openai_api_key:
        return f"[stage={stage} | rule-based]\n" + stage_instruction(stage)
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=s.openai_api_key)
    sys_text = system_prompt() + "\n\nТекущая стадия: " + stage + "\n" + stage_instruction(stage)
    messages: list[dict] = [{"role": "system", "content": sys_text}]
    messages.extend(history)
    messages.append({"role": "user", "content": client_text})
    resp = await client.chat.completions.create(
        model=s.llm_short_model,
        max_tokens=200,
        messages=messages,
    )
    return (resp.choices[0].message.content or "").strip()


def _next_stage(current: Stage, client_text: str, qualify_count: int) -> Stage:
    """Эвристика переходов по скрипту «по заявке».

    qualify_count — сколько квалификационных вопросов уже задано (0..5).
    После 5 вопросов выходим из qualify в present.
    """
    t = client_text.lower()
    if any(w in t for w in ("не интересно", "не нужно", "не звоните")):
        return "goodbye"
    if any(w in t for w in ("дорого", "далеко", "подумаем", "сомневаюсь")):
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


async def run_interactive() -> None:
    history: list[dict] = []
    stage: Stage = "greet"
    qualify_count = 0
    print(f"=== VoiceAgent dialogue simulator ===")
    print(f"FAKE_LLM={'no key — rule-based' if not get_settings().openai_api_key else 'real LLM'}")
    print("Введите реплику клиента; пустая строка — выход.\n")

    # Первая реплика агента (приветствие)
    agent = await _llm_reply("(start)", stage, history)
    print(f"AGENT [{stage}]: {agent}\n")
    history.append({"role": "assistant", "content": agent})

    while True:
        try:
            client_text = input("CLIENT: ").strip()
        except EOFError:
            break
        if not client_text:
            break
        history.append({"role": "user", "content": client_text})
        if stage == "qualify":
            qualify_count += 1
        stage = _next_stage(stage, client_text, qualify_count)
        agent = await _llm_reply(client_text, stage, history)
        history.append({"role": "assistant", "content": agent})
        print(f"AGENT [{stage}]: {agent}\n")
        if stage == "goodbye":
            break


async def run_from_transcript(path: Path) -> None:
    history: list[dict] = []
    stage: Stage = "greet"
    qualify_count = 0
    print(f"=== Прогон сценария: {path} ===\n")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("client:"):
            client_text = line.split(":", 1)[1].strip()
            print(f"CLIENT: {client_text}")
            history.append({"role": "user", "content": client_text})
            if stage == "qualify":
                qualify_count += 1
            stage = _next_stage(stage, client_text, qualify_count)
            agent = await _llm_reply(client_text, stage, history)
            history.append({"role": "assistant", "content": agent})
            print(f"AGENT [{stage}]: {agent}\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--transcript", type=Path, help="прогнать сценарий из файла")
    args = p.parse_args()

    if args.transcript:
        if not args.transcript.exists():
            print(f"transcript not found: {args.transcript}", file=sys.stderr)
            sys.exit(2)
        asyncio.run(run_from_transcript(args.transcript))
    else:
        asyncio.run(run_interactive())


if __name__ == "__main__":
    main()
