# Промпт: напоминание клиенту принять предложенное время (за 3ч до записи)

Готовый промпт для мультиагентного workflow проекта
(`.claude/agents/workflow.md`: planner → researcher → implementer →
routine → verifier → reviewer). Скопируй раздел "Задача для агента".

---

## Контекст проблемы

Сценарий: клиент отправил заявку на самозапись (self-booking, статус
PENDING), админ вместо подтверждения/отклонения предложил другое время
(`propose_new_datetime` в `bot/services/appointment/appointment_management.py`,
вызывается из "propose" экшена в
`bot/handlers/admin/appointment_management/booking_requests.py`). Клиенту
уходит **одно** сообщение с новым временем и кнопками "✅ Согласен на
новое время" / "❌ Не подходит" (`notify_client_reschedule_proposed` →
`reschedule_proposal_kb`). Дальше — тишина.

Если клиент не ответит, заявка молча превращается в `EXPIRED` ровно за
**2 часа** до предложенного времени (`schedule_pending_expiry`,
job `appt_{id}_expire`, см. `appointment_scheduler.py`). Единственный
шанс клиента среагировать — не пропустить то самое первое сообщение;
если оно потерялось в чате, следующий контакт — уже постфактум,
уведомление об истечении.

Нужно добавить промежуточное напоминание **за 3 часа до предложенного
времени** (то есть за 1 час до того, как заявка сгорит), которое ещё
раз покажет клиенту предложенное время и повторит кнопки
согласия/отклонения.

## Область действия (важно не перепутать сценарии)

Это напоминание относится **только** к случаю, когда админ предложил
новое время по PENDING-заявке клиента:
`appointment.status == PENDING and appointment.proposed_datetime is not None
and appointment.proposed_by == CreatedBy.ADMIN`.

Не путать с другим, отдельным сценарием — клиент сам предлагает перенос
уже подтверждённой (CONFIRMED) записи (`request_reschedule_by_client`,
`proposed_by == CreatedBy.CLIENT`, обрабатывается в
`reschedule_requests.py`). Там ждёт ответа **админ**, а не клиент, и в
эту задачу это не входит — трогать `expire_reschedule_request_job` и
связанные с ним job'ы не нужно.

Также не путать с обычными 24ч/2ч напоминаниями о самой записи
(`schedule_appointment_reminders`) — те работают только для уже
CONFIRMED/PENDING записей с обычным `datetime`, это отдельный механизм.

## Задача для агента

### 1. Новый job

В `bot/services/appointment/appointment_jobs.py` добавь функцию по
образцу `expire_pending_request_job`/`auto_confirm_pending_job`
(создаёт свои bot/repositories/notification_service, т.к. должна
планироваться APScheduler'ом по ссылке на модуль):

```python
async def send_proposal_reminder_job(appointment_id: int) -> None:
    """Remind the client to accept/reject the clinic's proposed time.

    Fires 3 hours before the proposed datetime (1 hour before the
    request would auto-expire via expire_pending_request_job).
    """
```

Внутри — та же защита от гонок, что и у `expire_pending_request_job`:
если `appointment is None`, или `status != PENDING`, или
`created_by != CreatedBy.CLIENT`, или `proposed_datetime is None`, или
`proposed_by != CreatedBy.ADMIN` — тихо выйти (заявка уже решена/не та).

Отправка — через новый метод нотификации (см. пункт 2), логировать
успех/неудачу по аналогии с остальными job'ами.

### 2. Новый метод уведомления

В `bot/services/appointment/appointment_notifications.py` добавь метод
рядом с `notify_client_reschedule_proposed`, например
`notify_client_proposal_reminder(appointment) -> bool`. Переиспользуй
`reschedule_proposal_kb(appointment.id)` для кнопок — они уже ведут в
`accept_proposal`/`reject_proposal` в `appointment_response.py`, ничего
менять в обработке ответа не нужно. Текст — короткое напоминание с
указанием предложенного времени и что заявка скоро "сгорит", если не
ответить (без указания точного числа часов до истечения — не дублируй
цифру, чтобы не рассинхронизировать тексты при будущих изменениях
константы).

### 3. Планирование в scheduler

В `bot/services/appointment/appointment_scheduler.py` добавь пару
методов по образцу `schedule_pending_expiry`/`cancel_pending_expiry`:

- `schedule_proposal_reminder(appointment)` — планирует
  `send_proposal_reminder_job` на `proposed_dt - timedelta(hours=3)`
  (используй `appointment.datetime`, как и `schedule_pending_expiry`,
  которому на входе уже передают `proposal_target` с
  `datetime=proposed_datetime`, см. пункт 4 — сохраняй этот же
  контракт вызова, не меняй сигнатуру). Стандартный skip-if-past-due,
  как во всех остальных `schedule_*` методах. Job ID:
  `appt_{id}_propose_reminder`.
- `cancel_proposal_reminder(appointment_id)` — снимает этот job, по
  образцу `cancel_pending_expiry`.

Хардкодь `timedelta(hours=3)` прямо в методе — это соответствует
текущему стилю проекта (24ч/2ч/1ч офсеты у остальных job'ов тоже заданы
инлайн в `appointment_scheduler.py`, отдельных именованных констант для
них нет). Не вводи новую абстракцию/константу, если её нет в
соседнем коде — придерживайся текущего стиля.

### 4. Точки вызова (найти все существующие вызовы `schedule_pending_expiry` / `cancel_pending_expiry` и продублировать рядом)

Сейчас это:

- `bot/handlers/admin/appointment_management/booking_requests.py`:
  - `confirm_request` — после `cancel_pending_expiry` добавь
    `cancel_proposal_reminder`.
  - `reject_request` — аналогично.
  - `approve_propose_datetime` — после
    `cancel_pending_expiry` + `schedule_pending_expiry(proposal_target)`
    добавь `cancel_proposal_reminder` (снять старый, если это
    повторное предложение) и `schedule_proposal_reminder(proposal_target)`.
- `bot/handlers/client/appointment_response.py` — во всех 5 местах, где
  сейчас вызывается `cancel_pending_expiry` (клиент принял/отклонил
  предложение, отменил запись и т.д.) — добавь рядом
  `cancel_proposal_reminder`.
- `bot/handlers/client/appointment_booking.py` (строка со
  `schedule_pending_expiry(appointment)` при создании самой заявки) —
  **не трогать**: на этом этапе `proposed_datetime` ещё нет (заявка
  без предложения), напоминание планировать не на что.

Обязательно перепроверь через `grep -rn "cancel_pending_expiry\|schedule_pending_expiry"`,
что все точки найдены — список выше актуален на момент написания
промпта, но мог измениться.

### 5. Тесты

- `tests/test_appointment_scheduler.py` — добавь тесты на
  `schedule_proposal_reminder`/`cancel_proposal_reminder` по образцу
  существующих тестов для `schedule_pending_expiry`/`cancel_pending_expiry`
  (создание job'а, job ID, skip-if-past-due, отмена).
- Тесты на сам `send_proposal_reminder_job` (по образцу тестов на
  `expire_pending_request_job`/`auto_confirm_pending_job`, если такие
  есть) — проверь все guard-условия (заявка не найдена, статус не
  PENDING, `proposed_by != ADMIN`, `proposed_datetime is None`).
- Тест на полный сценарий: админ предлагает время → напоминание
  запланировано на `proposed_dt - 3ч` → если клиент принимает/отклоняет
  раньше — job напоминания отменяется и не срабатывает.
- Обнови `docs/manual_qa_checklist.md`, если там есть сценарий с
  предложением времени клиенту без ответа — добавь шаг с ожиданием
  3-часового напоминания.

### Порядок выполнения (обязателен по workflow.md)

1. **planner** — фиксирует scope (см. "Область действия" выше, не
   расширять на reschedule-от-клиента сценарий).
2. **researcher** — находит все вызовы `schedule_pending_expiry`/
   `cancel_pending_expiry`, читает `appointment_jobs.py`,
   `appointment_notifications.py`, `appointment_scheduler.py`,
   `tests/test_appointment_scheduler.py` для соблюдения стиля.
3. **implementer** — добавляет job, метод уведомления, методы
   scheduler'а, проставляет вызовы во всех найденных точках.
4. **test-expert** — пишет/прогоняет тесты, включая граничные случаи
   (заявка решена раньше, чем сработало напоминание; время предложено
   меньше чем за 3ч до записи — напоминание не планируется вовсе).
5. **reviewer** — сверяет с CLAUDE.md (бизнес-логика только в Service/
   job-функциях, никакой логики в хендлерах, кроме вызова методов),
   проверяет, что новый job симметрично отменяется во всех точках, где
   отменяется `pending_expiry`.

### Definition of Done

- Клиенту, которому предложили новое время и он не ответил, за 3 часа
  до предложенного времени приходит повторное напоминание с кнопками
  принять/отклонить.
- Job напоминания корректно снимается при любом раннем разрешении
  заявки (принял, отклонил, админ подтвердил/отклонил/удалил запись).
- Не затронута логика reschedule-от-клиента (`proposed_by == CLIENT`).
- `pytest` зелёный, включая новые тесты.

---

# Задача 2 (отдельная, независимая от задачи выше): дата создания клиентов отстаёт от записей на 5 часов

Это самостоятельный баг, не связанный с напоминанием о принятии
предложенного времени выше — planner должен вести его отдельным
пунктом плана, не смешивать реализацию с Задачей 1.

## Диагноз (уже найден, перепроверить перед правкой)

- `bot/repositories/appointment_repository.py`: таблица `appointments`
  имеет `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP` в схеме, но
  это значение по умолчанию **никогда не используется** — сервис
  (`AppointmentManagement.create_appointment` /
  `create_self_booking` в `appointment_management.py`) всегда явно
  передаёт `created_at=get_current_tashkent_time()`
  (`bot/services/utils/date_parser.py`, таймзона `Asia/Tashkent`,
  UTC+5) в INSERT. Поэтому даты у записей верные.
- `bot/repositories/user_repository.py`: таблица `users` тоже имеет
  `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`, но `create_user()`
  **не передаёт** `created_at` в INSERT вообще — колонка молча
  заполняется SQLite-дефолтом `CURRENT_TIMESTAMP`, а он всегда в
  **UTC**, а не в Asia/Tashkent. Отсюда системное расхождение ровно на
  5 часов (UTC+5) между `users.created_at` и `appointments.created_at`.
- Дополнительно: `USER_SELECT`/`_row_to_user` в `user_repository.py`
  вообще не читают и не маппят `created_at` в модель `User`
  (`bot/models/user.py` — поля `created_at` там сейчас нет). Это не
  сама причина бага, но без этого поля дату создания клиента и не
  показать/не проверить на уровне приложения — нужно завести.

## Задача для агента

### 1. Код: пофиксить регион для новых клиентов (Python-уровень, не SQL default)

По аналогии с тем, как это уже сделано для `Appointment`:

- Добавить `created_at: str | None = None` в `bot/models/user.py`.
- В `bot/repositories/user_repository.py`:
  - добавить `created_at` в `USER_SELECT` и в `_row_to_user`;
  - `create_user()` — добавить `created_at` в список колонок/`VALUES`
    INSERT и передавать `user.created_at`.
- Во всех местах, где создаётся `User(...)` для последующей записи в
  БД (найдено через `grep -rn "User(" bot/services bot/handlers/registration.py`,
  перепроверь на актуальность — на момент написания промпта это три
  места):
  - `bot/services/client/client_management.py` (`create_client`)
  - `bot/services/utils/registration.py` (регистрация клиента)
  - `bot/services/appointment/appointment_management.py`
    (fallback-ветка в `check_or_create_client`, если
    `client_management` не инжектирован)

  — проставить `created_at=get_current_tashkent_time()`, ровно как
  это делает `AppointmentManagement.create_appointment`. Не изобретай
  новый способ получения времени — переиспользуй существующую
  `get_current_tashkent_time()` из `bot/services/utils/date_parser.py`.
- **Не трогай** `appointments.created_at`/`status_updated_at` и логику
  их вычисления — там уже всё верно, это не часть бага.
- **Не трогай** таймзону/конфиг самого `AsyncIOScheduler`
  (`timezone='Asia/Tashkent'` в `bot/create_bot.py`) — это отдельный,
  корректно работающий механизм, задача его не касается.

### 2. Разовая миграция данных: прибавить 5 часов существующим клиентам

Нужно одноразово исправить исторические данные:
`UPDATE users SET created_at = datetime(created_at, '+5 hours')`
(или эквивалент через Python/`aiosqlite`, если так проще протестировать).

Критически важные ограничения (заказчик явно подчеркнул это отдельно):

- Миграция должна быть **идемпотентной / выполняться ровно один раз**.
  `UserRepository.init()` уже сейчас выполняется на **каждом** старте
  бота (см. существующий паттерн `ALTER TABLE ADD COLUMN IF NOT EXISTS`
  через `PRAGMA table_info`) — если просто вставить туда безусловный
  `UPDATE ... +5 hours`, при каждом перезапуске бота время будет
  съезжать ещё на 5 часов. Нужен явный guard (например, отдельная
  служебная таблица/строка-метка о применённых миграциях, или
  одноразовый скрипт вне `init()`, который явно запускается один раз
  и это документируется) — конкретный механизм выбирает
  planner/implementer, но обязаны объяснить в плане, как гарантируется
  однократность.
- Миграция трогает **только** колонку `users.created_at` в основной
  БД бота (файл из `DATA_BASE` в `.env`, класс `Database` в
  `bot/models/database.py`). Она никак не должна касаться
  `appointments.created_at`/`status_updated_at` (те уже верны).
- **Отдельная, отдельно лежащая БД для APScheduler**
  (`bot/create_bot.py`: `SQLAlchemyJobStore` поверх
  `data/reminders.db`, где физически живут уже запланированные jobs —
  reminders, auto-confirm, completion, pending/reschedule expiry) —
  эта миграция НЕ должна её трогать вообще, это другой файл БД и
  другая система хранения.

### 3. Обязательная проверка (то самое "!!!!" в запросе заказчика): не сломать текущие jobs/reminders

Явно подтверди и зафиксируй в плане/ревью, а не просто предположи, что:

- Все текущие и future job'ы в `data/reminders.db`
  (`schedule_appointment_reminders`, `schedule_appointment_completion`,
  `schedule_auto_confirm`, `schedule_pending_expiry`,
  `schedule_reschedule_expiry` и т.д. в `appointment_scheduler.py`)
  планируются на основе `appointment.datetime`/`proposed_datetime`, а
  **не** на основе `users.created_at` — то есть эта миграция и фикс
  логически их не задевают.
- Тем не менее, до и после применения миграции на реальной/staging БД
  нужно явно сравнить список активных job'ов через API scheduler'а
  (`scheduler.get_jobs()`) — до и после — и убедиться, что набор
  job'ов идентичен (ни один не потерялся, не задвоился и не поменял
  `run_date`). Это шаг ручной/скриптовой проверки, добавь его в
  `docs/manual_qa_checklist.md` как отдельный пункт.
- Если в процессе исследования обнаружится, что миграция/фикс всё же
  может задеть что-то, что использует `users.created_at` для
  планирования (сейчас, по всем найденным местам, такого нет) —
  остановиться и явно предупредить в выводе planner/reviewer, а не
  тихо чинить на месте.

### 4. Тесты

- `tests/test_user_repository.py` — тест, что `create_user` пишет
  `created_at` в Tashkent-времени (а не полагается на SQL-дефолт),
  по аналогии с тем, как это уже проверяется для `Appointment` в
  `tests/test_appointment_repository.py`.
- Тест на саму миграцию: применить на БД с "испорченными" (UTC)
  датами, убедиться что после миграции даты клиентов сопоставимы
  (в пределах разумного) с датами записей, и что повторный запуск
  миграции/повторный `init()` **не** сдвигает даты ещё раз.
- Тест/проверка (можно смоделировать через `AppointmentScheduler` с
  тестовым `AsyncIOScheduler`, как в `tests/test_appointment_scheduler.py`),
  что список запланированных job'ов не меняется до/после фикса —
  формально зафиксировать инвариант "миграция users.created_at не
  влияет на расписание APScheduler".

### Definition of Done (Задача 2)

- Новые клиенты получают `created_at` в Asia/Tashkent времени, как и
  записи — фикс на уровне Python-кода (Service), не на SQL-дефолте.
- Существующим клиентам одноразово и безопасно (без риска повторного
  применения) пересчитан `created_at` (+5 часов).
- Явно подтверждено (в плане и в `docs/manual_qa_checklist.md`), что
  текущие запланированные reminders/jobs в `data/reminders.db` не
  затронуты и не требуют миграции — они и так считаются от
  `appointment.datetime`, а не от `users.created_at`.
- `appointments.created_at`/`status_updated_at` и таймзона самого
  scheduler'а не тронуты.
- `pytest` зелёный, включая новые тесты.
