# Промпт: перевести booking_requests.py на общий resync_appointment_jobs

Готовый промпт для мультиагентного workflow проекта
(`.claude/agents/workflow.md`: planner → researcher → implementer →
routine → verifier → reviewer). Скопируй раздел "Задача для агента".

Это пункт **3 из 4** согласованного плана. Пункты 1 (`docs/zombie_pending_fix_prompt.md`),
2 (`docs/slot_conflict_detection_prompt.md`) и 4
(`docs/admin_visibility_scope_prompt.md`) **уже реализованы** — этот
промпт обновлён под их актуальное состояние в коде (сверено ресерчем
после реализации, дата сверки актуальности — сразу после выката фиксов
1/2/4).

**Важное следствие уже реализованного пункта 1:** асимметрия
auto-confirm/expired между треками убрана — теперь **оба** трека
(`created_by=CLIENT` и `created_by=ADMIN`) при отсутствии согласия
становятся `EXPIRED`, а не только клиентский. `schedule_auto_confirm`
(`appointment_scheduler.py:194`) оставлен в коде как `[LEGACY]` метод
для обратной совместимости и **нигде не вызывается** — не
реинтегрировать его при рефакторинге. `cancel_auto_confirm`
(`appointment_scheduler.py:281`), наоборот, по-прежнему живой и
вызывается защитно во множестве мест (в т.ч. внутри самого
`resync_appointment_jobs`) — на случай, если в job-store планировщика
(`data/reminders.db`) остались старые персистентные job'ы этого типа с
прошлых версий кода. Это ожидаемо, трогать не нужно.

---

## ⚠️ Обязательное правило для всех агентов (в первую очередь researcher)

Если в процессе исследования или реализации обнаруживается **костыль,
несоответствие, дубликат логики, неочевидный edge-кейс или коллизия**
(например: номера строк ниже уже снова сместились; ручной вызов, который
на самом деле отличается по поведению от того, что делает
`resync_appointment_jobs`, сильнее, чем описано ниже; ещё одно место с
похожим ручным паттерном) — **агент обязан сразу сообщить об этом
текстом и остановиться**, дождавшись решения пользователя. Не
додумывать, не выбирать "разумный" вариант самостоятельно.

---

## Контекст проблемы

`bot/handlers/admin/appointment_management/booking_requests.py` — **единственный**
файл в проекте, который не использует общую точку пересчёта job'ов
планировщика `appointment_scheduler.resync_appointment_jobs()`. Вместо
этого в трёх местах вручную вызываются точечные `cancel_*`/`schedule_*`
методы. Все настоящие negotiation-хендлеры (обмен предложениями времени)
уже используют единый `resync_appointment_jobs`: `appointment_response.py`
(строки 220, 261, 370), `reschedule_requests.py` (60, 95, 199),
`appointment_reschedule.py` (243), `appointment_invite.py` (46, 98,
файл лежит в `bot/handlers/client/`, не в `admin/`),
`appointment_browser.py` (430, ветка `approve_new_datetime`).

Отдельно, в других (не-negotiation) флоу — отмене/смене статуса —
встречаются свои собственные ручные `cancel_*`-последовательности вне
`resync` (`appointment_response.py`: 178-184, 324-330, 436-442;
`appointment_browser.py`: `set_status` 230-244, `finish_delete` 325-328,
`finish_appointment` 620-623). **Это не в скоупе этой задачи** — там
своя специфика (отмена/удаление/завершение, не переговоры), не путать
и не трогать заодно, если явно не попросят отдельно.

`booking_requests.py` обрабатывает исключительно заявки клиентского
self-booking трека (`created_by == CreatedBy.CLIENT`) — ADMIN-трек в
этот файл не заходит вообще, так что ветка `resync_appointment_jobs` для
`created_by == ADMIN` (см. ниже) для этого рефакторинга не актуальна,
упомянута только для полноты картины.

## Задача для агента

Три места в `booking_requests.py` (номера строк подтверждены сверкой
после реализации пунктов 1/2/4 — но всё равно перепроверить перед
правкой, могли сместиться за время между сверкой и запуском этого
промпта):

### 1. `confirm_request` (строки 71-76)

Текущий код:

```python
if appointment_scheduler:
    await appointment_scheduler.cancel_pending_expiry(callback_data.appointment_id)
    await appointment_scheduler.cancel_proposal_reminder(callback_data.appointment_id)
    await appointment_scheduler.cancel_auto_confirm(callback_data.appointment_id)
    await appointment_scheduler.schedule_appointment_reminders(appointment)
    await appointment_scheduler.schedule_appointment_completion(appointment)
```

(после `appt_mng.confirm_pending_request(...)` на строке 61, которая
гарантирует `status == CONFIRMED` и `proposed_datetime is None` —
проверяется guard'ом `NegotiationInProgressError` внутри самого
сервисного метода).

Заменить на:

```python
await appointment_scheduler.resync_appointment_jobs(appointment)
```

### 2. `reject_request` (строки 103-106)

Текущий код:

```python
if appointment_scheduler:
    await appointment_scheduler.cancel_pending_expiry(callback_data.appointment_id)
    await appointment_scheduler.cancel_proposal_reminder(callback_data.appointment_id)
    await appointment_scheduler.cancel_auto_confirm(callback_data.appointment_id)
```

(после `appt_mng.reject_pending_request(...)` на строке 93 — статус
становится `CANCELLED`, `proposed_datetime` тем же guard'ом гарантированно
`None`).

Заменить на тот же единый вызов
`await appointment_scheduler.resync_appointment_jobs(appointment)`.

### 3. `approve_propose_datetime` (строки 200-205)

Текущий код:

```python
if appointment_scheduler:
    await appointment_scheduler.cancel_pending_expiry(callback_data.appointment_id)
    await appointment_scheduler.cancel_proposal_reminder(callback_data.appointment_id)
    proposal_target = replace(appointment, datetime=appointment.proposed_datetime)
    await appointment_scheduler.schedule_pending_expiry(proposal_target)
    await appointment_scheduler.schedule_proposal_reminder(proposal_target)
```

(после `appt_mng.propose_new_datetime(...)` на строке 187 — статус
остаётся `PENDING`, устанавливается `proposed_datetime`/
`proposed_by=ADMIN`).

Заменить на `await appointment_scheduler.resync_appointment_jobs(appointment)`.

### 4. Важно: замена НЕ побайтово идентична — она "эквивалентна по итоговому состоянию"

Это отличается от более раннего черновика этого промпта, где утверждалось
дословное совпадение — перепроверено ресерчем построчно на актуальном
коде, и это неточная формулировка. `resync_appointment_jobs` в каждом из
трёх мест делает **строго больше** отмен, чем ручной код, но каждая
дополнительная отмена — это no-op при гарантированных предусловиях сразу
после `confirm_pending_request`/`reject_pending_request`/
`propose_new_datetime` (заявка, которая никогда не была `CONFIRMED`, не
могла обзавестись job'ами reminders/completion; `proposed_datetime`
гарантированно `None` сразу после confirm/reject). Явно фиксируй эти
дельты в реализации (например, комментарием в PR/коммите), а не
представляй рефакторинг как "ничего не изменилось":

- **`confirm_request`** → ветка `CONFIRMED` в `resync`
  (`appointment_scheduler.py:582-598`) добавляет сверх трёх ручных
  cancel + двух ручных schedule: `cancel_reschedule_expiry` (no-op,
  `proposed_datetime is None`), плюс `cancel_appointment_reminders`/
  `cancel_appointment_completions` непосредственно перед их же
  `schedule_*` (защитная отмена перед постановкой, а не баг).
- **`reject_request`** → терминальная ветка `resync`
  (`appointment_scheduler.py:568-580`, покрывает
  `CANCELLED`/`COMPLETED`/`NO_SHOW`/`EXPIRED`) добавляет **три**
  отмены сверх трёх ручных: `cancel_reschedule_expiry`,
  `cancel_appointment_reminders`, `cancel_appointment_completions` — все
  no-op, поскольку у заявки, которая никогда не становилась `CONFIRMED`,
  этих job'ов и не может быть.
- **`approve_propose_datetime`** → ветка `PENDING`/`CLIENT`/
  `proposed_by=ADMIN` в `resync` (`appointment_scheduler.py:608-613`,
  актуальный номер строк — раньше в черновике промпта ошибочно
  указывались строки 596-601) добавляет `cancel_auto_confirm`,
  `cancel_reschedule_expiry`, `cancel_appointment_reminders`,
  `cancel_appointment_completions` поверх пересчёта
  `pending_expiry`/`proposal_reminder`, который ручной код уже делал.

### 5. Проверка эквивалентности поведения

Это **рефакторинг с строго дополнительными (но безопасными) отменами**,
не байт-в-байт замена. Обязательно либо вручную протрассировать (для
каждого из трёх call site — что именно отменяется/ставится до и после
замены, включая новые no-op отмены из пункта 4), либо написать
регресс-тест, фиксирующий, что итоговое множество **активных** job'ов
после каждого действия совпадает до и после рефакторинга (лишние
отмены несуществующих job'ов не влияют на итоговое состояние).

## Порядок выполнения (обязателен по workflow.md)

1. **planner** — фиксирует scope строго по трём местам выше.
2. **researcher** — перепроверяет, что номера строк в
   `booking_requests.py` (71-76, 103-106, 200-205) и в
   `appointment_scheduler.py` (568-580, 582-598, 608-613) не сместились
   с момента последней сверки; перепроверяет, что guard'ы
   (`proposed_datetime is None` сразу после confirm/reject) всё ещё в
   силе — от них зависит безопасность дельт из пункта 4. **Если
   обнаружится расхождение — см. правило в начале документа: сообщить и
   ждать решения, не продолжать.**
3. **implementer** — вносит замену в трёх местах, явно фиксирует в
   коммите дельты из пункта 4 задачи (не как "ничего не изменилось").
4. **test-expert** — пишет/прогоняет регресс-тест на эквивалентность
   итогового набора активных job'ов до/после для всех трёх call site.
5. **reviewer** — сверяет с CLAUDE.md (никакой логики в хендлере, кроме
   вызова сервисных методов), убеждается, что `booking_requests.py`
   больше не содержит ручных `cancel_*`/`schedule_*` вызовов напрямую,
   и что дельты из пункта 4 явно упомянуты, а не скрыты.

## Definition of Done

- `confirm_request`, `reject_request`, `approve_propose_datetime`
  вызывают `resync_appointment_jobs` ровно один раз каждый и больше не
  вызывают `cancel_*`/`schedule_*` методы напрямую.
- Итоговое множество активных job'ов после каждого действия совпадает
  до и после рефакторинга — подтверждено трассировкой или тестом; лишние
  no-op отмены задокументированы, а не выданы за "без изменений".
- `booking_requests.py` больше не единственное исключение среди
  negotiation-хендлеров, использующих `resync_appointment_jobs`.
- `pytest` зелёный.
