# Промпт: проверка владения записью при действиях с карточкой (card-level ownership check)

Готовый промпт для мультиагентного workflow проекта
(`.claude/agents/workflow.md`: planner → researcher → implementer →
routine → verifier → reviewer). Скопируй раздел "Задача для агента".

Продолжение `docs/admin_visibility_scope_prompt.md` (реализован и принят
reviewer'ом) — это найденный при финальном ревью **residual-баг**, не
входивший в исходный scope той задачи. Независим по коду от остальных
задач (`docs/zombie_pending_fix_prompt.md`,
`docs/slot_conflict_detection_prompt.md`,
`docs/booking_requests_resync_refactor_prompt.md`), но опирается на уже
реализованный `resolve_admin_appointment_filter`
(`bot/services/appointment/appointment_management.py:80`).

---

## ⚠️ Обязательное правило для всех агентов (в первую очередь researcher)

Если в процессе исследования или реализации обнаруживается **костыль,
несоответствие, дубликат логики, неочевидный edge-кейс или коллизия**
(например: ещё один хендлер/сервисный метод, работающий с записью по ID
без проверки владения, не упомянутый ниже; расхождение в том, что
`resolve_admin_appointment_filter` возвращает для конкретного пользователя)
— **агент обязан сразу сообщить об этом текстом и остановиться**,
дождавшись решения пользователя. Не додумывать, не выбирать "разумный"
вариант самостоятельно, не выкатывать дефолтное поведение без
подтверждения.

---

## Контекст проблемы

`docs/admin_visibility_scope_prompt.md` защитил три точки входа в "Обзор
записей" (список/статусы, поиск по имени, поиск по телефону) — админ с
`visibility_scope='own'` теперь видит в списке только свои записи, с
`'clinic'` — все записи своей клиники.

Но список — это не единственный способ получить доступ к записи по ID.
Все действия над уже открытой карточкой берут `appointment_id`
из callback-данных (`ApptActionCB`/`ApptCardCB`, простой, предсказуемый,
**не подписанный** формат от aiogram `CallbackData` factory) и обращаются
к записи напрямую **без проверки, что она входит в разрешённый для этого
админа `clinic_id`/`doctor_id`**:

- `bot/handlers/admin/appointment_management/appointment_browser.py`:
  `open_card` (:204), `set_status` (:213), `start_delete`/`confirm_delete`/
  `finish_delete` (:259, :282, :304), `start_edit_datetime`/
  `approve_new_datetime` (:346, :384), `start_edit_purpose`/
  `approve_new_purpose` (:430, :473), `start_edit_price`/`approve_new_price`
  (:496, :539), `finish_appointment` (:560).
- Также обнаружены (при подготовке этого промпта, требуют подтверждения
  researcher'ом — используют `staff_telegram_id`, но нигде не сверяют его
  с записью): `AppointmentManagement.confirm_pending_request`,
  `reject_pending_request`, `propose_new_datetime`,
  `accept_client_reschedule`, `reject_client_reschedule`
  (`bot/services/appointment/appointment_management.py:277-439`),
  вызываемые из `bot/handlers/admin/appointment_management/
  reschedule_requests.py` и `booking_requests.py`.

`appointment_id` — обычный автоинкрементный `int` (не UUID), легко
угадываем/перебираем. Поскольку callback-данные не подписаны и не
привязаны к личности отправителя ничем, кроме `RoleFilter("admin")`,
технически подкованный `'own'`-админ (или `'clinic'`-админ чужой клиники)
может отправить боту поддельный callback с чужим `appointment_id` (через
любую библиотеку, умеющую говорить с Telegram Bot API от имени
пользователя) и получить доступ на чтение/изменение/удаление записи,
которую в списке ему не показывают.

Похожий защищённый паттерн **уже существует** для клиентской стороны:
`AppointmentManagement.get_appointment_for_client(appointment_id,
telegram_user_id)` (`bot/services/appointment/
appointment_management.py:222`) — возвращает запись только если она
принадлежит клиенту с данным `telegram_user_id`, иначе `None`. Новую
проверку для админской стороны стоит делать по аналогии.

## Согласованная модель (предложена, требует финального решения пользователя на планировании)

- Новый метод в `AppointmentManagement`, аналогичный
  `get_appointment_for_client`:

  ```python
  async def get_appointment_for_admin(
      self, appointment_id: int, admin_telegram_id: int
  ) -> Appointment | None:
      """Возвращает запись только если она входит в разрешённый для этого
      админа scope (clinic_id + doctor_id из resolve_admin_appointment_filter).
      None, если запись не найдена или вне scope."""
  ```

  Внутри: получить `(clinic_id, doctor_id)` через уже существующий
  `resolve_admin_appointment_filter(admin_telegram_id)`, получить запись
  через `get_appointment_by_id`, сверить `appointment.clinic_id ==
  clinic_id` и (если `doctor_id is not None`) `appointment.doctor_id ==
  doctor_id`. Вернуть `None` при несовпадении — единообразно с
  `get_appointment_for_client`, чтобы вызывающий код мог кидать уже
  существующий `AppointmentNotFoundError`, не путая с "запись реально не
  существует" на уровне UX (сообщение пользователю может быть одинаковым
  — "запись не найдена").

- Все перечисленные выше admin-хендлеры в `appointment_browser.py`,
  которые сейчас вызывают `get_appointment_by_id`/`_get_or_raise`
  напрямую по `callback_data.appointment_id`, должны вместо этого
  проверять владение через `get_appointment_for_admin` **до** выполнения
  действия (чтение карточки, смена статуса, удаление, перенос даты,
  правка цели/цены, завершение приёма).

- При отказе — не молчаливый `AppointmentNotFoundError` без объяснений;
  сохранить текущий UX (то же сообщение, что и для "записи не существует"
  вообще), чтобы не раскрывать факт существования чужой записи через
  разницу в поведении ("не найдена" vs "нет доступа").

## Открытые вопросы (не додумывать — планировщик и researcher должны либо
подтвердить объём, либо вернуться к пользователю)

1. Нужно ли расширять эту защиту также на
   `confirm_pending_request`/`reject_pending_request`/
   `propose_new_datetime`/`accept_client_reschedule`/
   `reject_client_reschedule` (вызываются из `reschedule_requests.py` и
   `booking_requests.py`, тоже принимают `staff_telegram_id`/
   `appointment_id` без сверки) — это тот же класс уязвимости, но другой
   набор хендлеров, не входивших в исходную находку reviewer'а. Решить на
   этапе planner/researcher, входит ли это в scope одного фикса или нужен
   отдельный промпт.
2. `update_status`, `delete_appointment`, `update_datetime`,
   `update_purpose`, `update_price` в `appointment_management.py` — общие
   методы, вызываемые и из клиентских, и из админских флоу через разные
   входные точки. Нужно решить, где именно ставить проверку владения: на
   уровне вызывающего хендлера (после `get_appointment_for_admin`, вызов
   остаётся прежним) или встраивать проверку scope внутрь самих
   `update_*`/`delete_appointment` (потребовало бы прокидывать
   `admin_telegram_id` в сигнатуры, что шире по изменению). Предпочтителен
   первый вариант (хендлер проверяет владение перед вызовом), чтобы не
   трогать сигнатуры общих сервисных методов — но зафиксировать это должен
   planner, не implementer по ходу дела.
3. Нужно ли одновременно чинить те же admin-facing хендлеры в
   `reschedule_requests.py`/`booking_requests.py`, если ответ на п.1 —
   "да", или это выносится в отдельный follow-up промпт после того, как
   этот фикс будет принят.

## Задача для агента

### 1. Research — полный список точек, требующих проверки владения

`researcher` должен:
- Перепроверить и подтвердить (или дополнить) список хендлеров из раздела
  "Контекст проблемы", включая `reschedule_requests.py`/
  `booking_requests.py` — какие из них реально достижимы через
  `RoleFilter("admin")` без дополнительной проверки владения.
- Проверить реальную схему `Appointment` (`bot/models/appointment.py`) —
  подтвердить точные имена полей `clinic_id`/`doctor_id`, используемые для
  сверки.
- Проверить, есть ли уже тесты на `get_appointment_for_client` (стиль,
  который нужно повторить для `get_appointment_for_admin`).

### 2. Service — `get_appointment_for_admin`

Добавить в `bot/services/appointment/appointment_management.py` по
аналогии с `get_appointment_for_client` (см. модель выше).

### 3. Handler — обернуть все точки доступа к карточке

В `bot/handlers/admin/appointment_management/appointment_browser.py`
заменить прямые вызовы `get_appointment_by_id`/`_get_or_raise`-путь (через
`update_status`/`delete_appointment` и т.д.) на предварительную проверку
`get_appointment_for_admin` в каждом хендлере, перечисленном в "Контексте
проблемы", с единообразной обработкой отказа (то же сообщение, что и для
"запись не найдена").

### 4. Определиться с реестром reschedule_requests.py/booking_requests.py

По результатам ответа на "Открытый вопрос 1" — либо включить в эту же
задачу, либо явно зафиксировать как отдельный follow-up с указанием, что
уязвимость там та же и её нужно закрыть отдельным промптом.

### 5. Тесты

`test-expert`: покрыть — `'own'`-админ не может прочитать/изменить/удалить
запись другого врача той же клиники через прямой `appointment_id`;
`'own'`-админ не может получить доступ к записи чужой клиники;
`'clinic'`-админ может работать с любой записью своей клиники, но не
чужой; несуществующий `appointment_id` и "чужой" `appointment_id` дают
одинаковый ответ пользователю (нет утечки через разницу в поведении).

### 6. Reviewer

Сверить с CLAUDE.md: проверка владения — бизнес-правило, должно жить в
Service (`get_appointment_for_admin`), а не в хендлере; хендлер только
вызывает метод и обрабатывает `None`. Подтвердить, что **все**
перечисленные в scope точки закрыты, а не только часть.

## Порядок выполнения (обязателен по workflow.md)

1. **planner** — фиксирует итоговый scope, включая явное решение по
   "Открытым вопросам" 1-3 (не додумывать — если нужно решение
   пользователя, остановиться и спросить).
2. **researcher** — раздел "Задача для агента, п.1".
3. **implementer** — `get_appointment_for_admin` + обёртка хендлеров.
4. **test-expert** — тесты по п.5.
5. **reviewer** — финальная проверка полноты покрытия и архитектуры.

## Definition of Done

- `'own'`-админ не может прочитать, изменить статус, удалить, перенести
  дату/цель/цену или завершить запись, которая не входит в его
  собственный `doctor_id`-scope — ни через список, ни через прямой
  `appointment_id` в callback.
- `'clinic'`-админ ограничен своей клиникой (тем же способом) во всех
  действиях с карточкой, но не привязан к конкретному врачу.
- Попытка обратиться к чужой записи и к несуществующей записи дают
  одинаковый ответ пользователю.
- Открытые вопросы 1-3 закрыты явным решением (пользователя или
  planner'а с обоснованием), не предположены implementer'ом по ходу дела.
- `pytest` зелёный.
