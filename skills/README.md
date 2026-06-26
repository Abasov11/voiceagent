# Skills — операционные runbook'и VoiceAgentа

Применяется по принципу «больше раза в день — переносить в skill, не копи-паст промпта» (, мультипромпт Claude Code).

## Список

| Skill | Когда |
|---|---|
| [re-seed-dashboard-users](re-seed-dashboard-users/SKILL.md) | После ребилда docker / потерян `seed-passwords.txt` / 401 в дашборде |
| [fake-providers-dryrun](fake-providers-dryrun/SKILL.md) | Smoke-проверка pipeline без реальных API ключей |
| [healthcheck-smoke](healthcheck-smoke/SKILL.md) | Утром / перед демо / после рестарта VPS / алёрт от cron |
| [backup-verify](backup-verify/SKILL.md) | Раз в неделю / перед опасной миграцией / после странностей в БД |
| [dialogue-simulator](dialogue-simulator/SKILL.md) | После правок диалоговой логики / новый скрипт от клиента / подозрение на петлю |

## Как добавлять новые skills

1. Триггер: «делал руками больше раза в день» ИЛИ «делал руками ≥3 раз за неделю».
2. Структура: `skills/<kebab-name>/SKILL.md` с frontmatter (name, description-триггер).
3. Содержимое: When to use → Pre-checks → Steps → Verify → Связано.
4. Описание (description) формулируется как **триггер** — что я ищу в речи команды/себе чтобы вспомнить про этот skill.

## Связано

- [docs/TELEPHONY_FAILURES.md](../docs/TELEPHONY_FAILURES.md)
