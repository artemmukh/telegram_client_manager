# Аудит мёртвого кода — отчёт

Дата: 2026-07-08. Аудит проведён по процессу `prompt_dead_code_audit.md` (planner → researcher → reviewer), периметр — весь `bot/`. **Код на этапе аудита не менялся** — это отчёт, а не патч.

## Процесс

1. **Planner** — определил периметр (все поддиректории `bot/`), уточнил источник истины для регистрации роутеров (`bot/run.py`, не `bot/loader.py`), расписал по каждой из 9 категорий, где искать в первую очередь.
2. **Researcher** — прочитал вручную все файлы `bot/`, прогнал `ruff check bot/ --select F401,F841` и `vulture bot/ --min-confidence 60`, каждую находку инструмента перепроверил grep'ом (aiogram-декораторы дают у vulture массу ложных срабатываний — ~85 из ~100 находок отклонены как ложные: хендлеры, вызываемые диспетчером по декоратору, а не по имени).
3. **Reviewer** — независимо (без доверия формулировкам researcher'а) перепроверил все 39 строк итоговой таблицы собственными Read/Grep/ruff-прогонами. **Результат: 39 из 39 подтверждено, 0 отклонено, 0 понижено.** Reviewer нашёл 2 мелкие фактические неточности в тексте (не влияющие на выводы: счёт `include_router` — 14, не 13; счёт except-блоков для `JobSchedulingError`/`JobCancellationError` — 6, не 5) и 1 новую смежную находку (см. ниже, `config.py`).

## Таблица находок

| Файл:строка | Что | Категория | Доказательство (чем искал) | Уверенность | Рекомендация |
|---|---|---|---|---|---|
| `bot/handlers/client/client_handlers.py` (весь файл, 16 строк) | `create_client_router(user_repo, appointment_repo)` — ни одного handler'а внутри, функция нигде не вызывается | 1. Мёртвый модуль | grep `create_client_router\b` по репо — только определение; сверка всех 15 `def create_*_router` против 14 реальных `include_router` в `run.py` | высокая | Удалить файл целиком (функциональность перекрыта `client/appointment_response.py`, реально зарегистрированным в `run.py`) |
| `bot/middlewares/record.py` | Файл полностью пустой (0 байт) | 1. Мёртвый модуль | размер файла = 0; grep импортов — 0 | высокая | Удалить файл |
| `bot/middlewares/error.py:9` `ErrorMiddleware` | Рабочий класс (ValidationError → ответ, BotException → лог + "Произошла ошибка."), не зарегистрирован ни в `run.py`, ни в `create_bot.py` | 1. Мёртвый класс | grep `ErrorMiddleware` — только определение; `run.py` регистрирует только `UserContextMiddleware` | высокая | Спорный случай — см. ниже |
| `bot/middlewares/logging.py:5` `LoggingMiddleware` | Рабочий класс логирования update'ов, не зарегистрирован нигде | 1. Мёртвый класс | grep `LoggingMiddleware` — только определение | высокая | Спорный случай — см. ниже |
| `bot/exceptions/appointment_exceptions.py:5-7` `AppointmentAlreadyExistsError` | Объявлен, ни разу не `raise`/`except` | 7. Неиспользуемое исключение | grep по всему репо (вкл. tests) — только определение | высокая | Удалить |
| `bot/exceptions/appointment_exceptions.py:15-17` `BusyTimeError` | Объявлен, ни разу не `raise`/`except` | 7. Неиспользуемое исключение | grep по всему репо — только определение | высокая | Удалить |
| `bot/exceptions/appointment_exceptions.py:30-32` `SchedulerError` | Базовый класс, сам не `raise`ится напрямую | 7. Неиспользуемое исключение | grep `raise SchedulerError` — 0 | средняя | Оставить (используется как родитель `Job*Error`) |
| `bot/exceptions/appointment_exceptions.py:35-42` `JobSchedulingError`, `JobCancellationError` | Ловятся в `appointment_scheduler.py` (6 мест: строки 85, 109, 111, 147, 167, 169), но нигде не `raise`ятся — APScheduler кидает свои исключения, не эти | 7 + 8. Недостижимый except | grep `raise Job*Error` — 0; except — 6 совпадений | высокая (не raise'ится) / средняя (что делать) | Спорный случай — см. ниже |
| `bot/services/appointment/appointment_scheduler.py:174-176` `_send_reminder_job` | Docstring: "for backward compatibility with tests"; прод использует модульную `send_reminder_job` | 9. Используется только в tests | grep — только `tests/test_appointment_scheduler.py`, `tests/test_phase3_integration.py` | высокая | Используется только в tests — не удалять автоматически |
| `bot/services/appointment/appointment_scheduler.py:178-191` `_mark_appointment_completed_job` | Аналогично — только tests | 9. Используется только в tests | grep — только `test_appointment_scheduler.py`, `test_phase4_integration.py` | высокая | Используется только в tests — не удалять автоматически |
| `bot/repositories/appointment_repository.py:101-118` `get_appointments_by_telegram_id` | Не вызывается ни одним сервисом/хендлером, используется только в тесте; дублирует SQL `APPOINTMENT_SELECT` вручную | 4 + 5 + 9 | grep — только тест и определение | высокая (не используется в проде) | Спорный случай — см. ниже |
| `bot/repositories/appointment_repository.py:196-201` `count_appointments` | Не вызывается нигде — ни прод, ни тесты | 4. Мёртвый метод | grep по репо — только определение + упоминание в `prompt_appointment_browser_refactor.md:43` | средняя | Спорный случай — см. ниже |
| `bot/repositories/user_repository.py:92-100` `get_all_clients` | Не вызывается нигде — заменён `get_clients_page`/`count_all_clients` | 4. Мёртвый метод | grep по репо — только определение | высокая | Удалить |
| `bot/repositories/staff_repository.py:37-51` `add_staff` | Не вызывается нигде; сотрудники заводятся хардкодом 3 telegram_id в `init()` | 4. Мёртвый метод | grep — только определение | высокая | Спорный случай — см. ниже |
| `bot/repositories/staff_repository.py:53-61` `remove_staff` | Не вызывается нигде | 4. Мёртвый метод | grep — только определение | высокая | Спорный случай — см. ниже |
| `bot/repositories/staff_repository.py:77-87` `is_staff` | Не вызывается нигде — роль проверяется через `get_staff()` | 4. Мёртвый метод | grep — только определение | высокая | Спорный случай — см. ниже |
| `bot/repositories/clinic_repository.py:44-60` `get_clients_by_name` | Copy-paste из `UserRepository.get_clients_by_name`: ищет **клиники** (`FROM clinics`), но назван как метод поиска клиентов; не вызывается | 4 + 5. Мёртвый метод + copy-paste + неверное имя | grep `clinic_repo.get_clients_by_name` — 0; сравнение тел методов | высокая | Удалить |
| `bot/validators/validators.py:87-124` `validate_datetime_natural` | Полноценный валидатор "натурального" времени, не вызывается — реальный flow использует `datetime_processing()` + `parse_ru_datetime`/`format_datetime_for_db` | 9. Устаревший артефакт | grep по репо (вкл. tests) — только определение | высокая | Удалить |
| `bot/services/client/client_pagination_service.py:17-18` `has_prev`, `has_next` | Вычисляются, нигде не читаются — `client_browser.py` считает prev/next сам через `get_circular_page()` | 4/6. Мёртвые поля | grep `\.has_prev\|\.has_next` — 0 (кроме определения) | высокая | Удалить оба поля |
| `bot/states/client/appointment_states.py:5` `AppointmentResponseStates.confirm` | Объявлено, не используется (используется только `confirm_cancel`) | 2. Осиротевшее FSM-состояние | grep `\.confirm\b` — 0 | высокая | Удалить |
| `bot/states/client/appointment_states.py:6` `AppointmentResponseStates.cancel` | Аналогично | 2. Осиротевшее FSM-состояние | grep `\.cancel\b` — 0 | высокая | Удалить |
| `bot/handlers/admin/appointment_management/record_menu.py:18-32` ветка `back_to_main_clients` | `match` обрабатывает `"back_to_main_clients"`, но ни одна клавиатура такой callback_data не отправляет | 2. Осиротевший callback | grep `back_to_main_clients` по репо — только в этом файле; реально отправляется только `"back_to_main_records"` (`appointment_kb.py:94`) | высокая | Убрать ветку (или добавить недостающую кнопку, если это баг, а не мусор — решение за вами) |
| `bot/handlers/client/appointment_response.py:24-26` параметры `bot`, `user_repo`, `appointment_repo` в `create_client_appointment_router(...)` | Принимаются и реально передаются из `run.py:111-113`, но не используются в теле функции | 6. Неиспользуемые параметры фабрики | Построчный grep внутри файла (171 строка) — совпадения только в сигнатуре/импортах | высокая | Удалить 3 параметра из сигнатуры и вызова в `run.py` |
| `bot/handlers/admin/appointment_management/record_menu.py:9` параметр `appointment_repo` в `create_admin_record_router(...)` | Принимается, передаётся из `run.py:98`, не используется в теле (33 строки файла) | 6. Неиспользуемый параметр фабрики | Построчный просмотр всего файла | высокая | Удалить параметр из сигнатуры и вызова в `run.py` |
| `bot/create_bot.py:28-30` `Base = declarative_base(); Base.metadata.create_all(...)` | `Base` нигде больше не используется/не импортируется; `metadata.create_all()` с пустой metadata не создаёт таблиц — реальную таблицу job store создаёт `SQLAlchemyJobStore` | 1/8. No-op код | Read файла целиком | средняя | Спорный случай — см. ниже (проверить на живом запуске) |
| `bot/handlers/utils/admin_utils/input_helpers.py:7,9,12` глобальный `user_repo = UserRepository(db)` | Создаётся при импорте модуля, нигде не читается в теле функций (все принимают репозиторий через параметры); к тому же создан из `db` (`Database`), а не `aiosqlite.Connection` — при обращении был бы скрытый баг | 1/6. Мёртвая глобальная переменная + нарушение "Avoid global mutable state" (CLAUDE.md) | grep `user_repo` в файле (85 строк) — только импорт и строка создания | высокая | Удалить строки 7, 9, 12 |
| `bot/config/config.py:10,19-21,32` поле `Config.admin_ids` | Читается из `ADMIN_IDS`, нигде в `bot/` не читается — роль определяется через `staff`/`StaffRepository` | 6. Неиспользуемое поле конфигурации | grep `admin_ids` по `bot/` — только в `config.py` | высокая | Спорный случай — см. ниже (там же смежный баг, см. примечание) |
| `bot/handlers/admin/appointment_management/appointment_creation.py:108` переменная `client` | Присваивается, не используется дальше | 6. Неиспользуемая переменная (ruff F841) | ruff F841 + чтение функции целиком | высокая | Убрать присваивание, оставить вызов без `client =` |
| `bot/services/appointment/appointment_jobs.py:126,223` `except AppointmentNotFoundError as e` | `e` не используется (логи без `{e}`) | 6. Неиспользуемая переменная (ruff F841) | ruff F841 (2 совпадения) | высокая | Убрать `as e` в обоих местах |
| `bot/handlers/admin/appointment_management/appointment_delete.py:16` импорт `AppointmentScheduler` | Не используется (тип не аннотирован) | 6. Неиспользуемый импорт (ruff F401) | ruff F401 | высокая | Удалить импорт |
| `bot/handlers/admin/appointment_management/appointment_update.py:15` импорт `AppointmentScheduler` | Не используется | 6. Неиспользуемый импорт (ruff F401) | ruff F401 | высокая | Удалить импорт |
| `bot/handlers/admin/appointment_management/appointment_search.py:10` импорт `build_appointment_card` | Не вызывается напрямую (используется только внутри `format_appointments_list`) | 6. Неиспользуемый импорт (ruff F401) | ruff F401 | высокая | Убрать из импорта |
| `bot/handlers/admin/appointment_management/record_menu.py:6` импорт `start_admin_keyboard` | Не используется | 6. Неиспользуемый импорт (ruff F401) | ruff F401 | высокая | Удалить импорт |
| `bot/handlers/client/client_handlers.py:2-3` импорты `client_keyboard`, `record_keyboard` | Не используются (в мёртвом файле) | 6. Неиспользуемый импорт (ruff F401) | ruff F401 | высокая | Удалится вместе с файлом |
| `bot/handlers/utils/admin_utils/appointment_helpers.py:6` импорт `back_to_records_kb` | Не используется в этом файле (используется в других модулях отдельным импортом) | 6. Неиспользуемый импорт (ruff F401) | ruff F401 | высокая | Удалить импорт |
| `bot/handlers/utils/utils.py` (весь файл, 6 строк) | Только 2 неиспользуемых импорта (`FSMContext`, `Message`/`CallbackQuery`), ни одной функции/класса; сам модуль нигде не импортируется | 1 + 6. Мёртвый модуль | Read файла целиком + grep `handlers.utils.utils` — 0 | высокая | Удалить файл целиком |
| `bot/keyboards/admin/admin_main_menu_kb.py:1` импорт `InlineKeyboardMarkup` | Не используется (функция возвращает `ReplyKeyboardMarkup`) | 6. Неиспользуемый импорт (ruff F401) | ruff F401 | высокая | Удалить импорт |
| `bot/services/appointment/appointment_scheduler.py:21` импорт `AppointmentStatus` | Не используется в файле | 6. Неиспользуемый импорт (ruff F401) | ruff F401 | высокая | Удалить импорт |
| `bot/services/client/client_management.py:11` импорт `SEARCH_NAME_PATTERN` | Не используется (используется `FULL_NAME_PATTERN`) | 6. Неиспользуемый импорт (ruff F401) | ruff F401 | высокая | Удалить из импорта |
| `bot/run.py:130` `print("Bot stopped.")` | Единственный `print(` во всём `bot/`, используется в `except KeyboardInterrupt` | 8. Стилистическая непоследовательность | grep `print(` по `bot/` — единственное совпадение | низкая | Не мусор в строгом смысле — на усмотрение (заменить на `logger.info` для консистентности или оставить) |

### Проверено, находок нет

Полностью сверены и подтверждены рабочими (без замечаний):

- Все callback'и/клавиатуры `client_management` (`client_browser_cb.py`, `client_browser_kb.py`, `client_creation_kb.py`, `client_main_menu_kb.py`) — каждый callback_data имеет парный handler.
- Все callback'и `record_management` (`record_main_menu_kb.py`, `appointment_kb.py`, `appointment_search_kb.py`) кроме `back_to_main_clients` (см. находки).
- Все callback'и клиентского flow записей (`client/appointment_management_kb.py`, `appointment_response_kb.py`, `client_main_keyboard.py`).
- `keyboards/utils/utils_kb.py` — все функции используются.
- Все FSM-состояния (`ClientBrowserStates`, `ClientCreationStates`, `AppointmentCreationStates`, `AppointmentSearchStates`, `AppointmentDeletionStates`, `AppointmentUpdateStates`, `RegisterStates`) кроме `AppointmentResponseStates.confirm`/`.cancel` (см. находки).
- Модели `Clinic`, `Staff` — подключены к архитектуре (используются в сервисах/репозиториях), не мёртвые, как и предполагалось планировщиком.
- Все исключения кроме перечисленных в находках (`PaginationError`, `RoleError`, `NotificationDeliveryError`, `SamePhoneError`, `UserAlreadyExistsError`, `PhoneAlreadyExistsError`, `InvalidFullNameError`, `InvalidPhoneError`, `InvalidPurposeError`, `InvalidDatetimeError`, `AppointmentNotFoundError`, `BotException`, `ValidationError`).
- Все публичные методы `AppointmentManagement`, `ClientManagement`, `RegistrationService`, `AuthService`, `resolve_staff_clinic` — используются.
- `ClientPaginationService.paginate_clients` и поля `PaginationResult` кроме `has_prev`/`has_next`.
- TODO/FIXME/закомментированный код — не найдено ни одного во всём `bot/`.
- Дубли SQL — единственный найден в `get_appointments_by_telegram_id`; остальные репозитории переиспользуют общие SELECT-константы корректно.
- `input_helpers.py` vs `client_browser_helpers.py`, `client_creation_kb.py` vs `client_browser_kb.py` vs `client_main_menu_kb.py` — пересечений логики нет, разделение оправдано архитектурой после рефакторинга client management.

### Инструменты

- `ruff check bot/ --select F401,F841` — 16 находок, все подтверждены вручную (не подвержены aiogram-декораторным ложным срабатываниям), reviewer перезапустил и получил тот же результат.
- `vulture bot/ --min-confidence 60` — ~100 находок, из которых ~85 отклонены как ложные срабатывания (aiogram-хендлеры, вызываемые диспетчером по декоратору `@router.message(...)`/`@router.callback_query(...)`, а не по прямому имени). Оставшиеся ~15 подтверждены вручную grep'ом и вошли в таблицу выше.

## Важная находка вне рамок аудита (не мёртвый код — живой баг)

**`bot/services/appointment/appointment_notifications.py:32,52`** — вызов `self.user_repo.get_user_by_id(appointment.doctor_id)`. Метод `get_user_by_id` **не существует** в `UserRepository` (полный список методов: `get_user_by_telegram_id`, `get_clients_by_name`, `get_all_clients`, `get_client_by_phone`, `update_client`, `update_user_telegram_id`, `delete_client`, `get_client_by_id`, `user_exists`, `phone_exists`, `get_user_role`, `get_clients_page`, `count_all_clients`, `get_clients_by_name_page`, `count_clients_by_name`). Вызов упадёт с `AttributeError` в любой момент, когда у записи на приём заполнен `doctor_id` — а после сегодняшнего фикса (`appointment_management.py`, резолвинг `admin_id` при создании записи) это теперь реально достижимый путь. Рекомендация: добавить в `UserRepository` метод получения пользователя по внутреннему `id` без фильтра по роли (`get_client_by_id` фильтрует `WHERE u.role = 'client'`, поэтому не подходит для админа), либо передавать уже загруженные данные администратора иначе. **Нужен отдельный фикс, не входит в объём этого аудита.**

## Сводка

- Строк в таблице находок: **39**, из них независимым reviewer'ом подтверждено **39/39**, отклонено **0**, понижено **0**.
- Безопасных удалений (высокая уверенность, без архитектурной развилки) — **~24 находки**, суммарно **≈120 строк кода** (включая удаление файлов `client_handlers.py` и `handlers/utils/utils.py` целиком).
- Спорных случаев, требующих решения — **6** (см. ниже), затрагивают ещё ~90-100 строк, которые трогать без вашего решения не стоит.
- Обнаружен 1 смежный живой баг (`get_user_by_id`) и 1 смежный краш-сценарий (`config.py`, отсутствие `ADMIN_IDS` в `.env` роняет запуск бота ещё до дружелюбной проверки) — оба вне периметра "мусорного кода", но стоит знать о них при следующей правке этих файлов.

### Топ-5 самых безопасных удалений

1. `bot/handlers/client/client_handlers.py` — весь файл (16 строк), полностью мёртвый роутер без единого handler'а.
2. `bot/middlewares/record.py` — пустой файл (0 байт).
3. `bot/handlers/utils/utils.py` — весь файл (6 строк), только 2 неиспользуемых импорта.
4. `bot/validators/validators.py:87-124` `validate_datetime_natural` — 38 строк, полностью вытеснен текущим flow валидации даты/времени.
5. `bot/repositories/clinic_repository.py:44-60` `get_clients_by_name` — 17 строк, copy-paste-баг (ищет клиники, а не клиентов, никем не вызывается).

## Спорные случаи (нужно ваше решение)

1. **`count_appointments`, `get_appointments_by_telegram_id`** (`appointment_repository.py`) — не используются в проде, но упомянуты в `prompt_appointment_browser_refactor.md` как возможная база для будущего рефакторинга appointment_browser (аналог client_browser). Удалить сейчас (пересоздать при реализации фичи) или оставить как задел?
2. **`ErrorMiddleware` / `LoggingMiddleware`** (`bot/middlewares/`) — оба полностью рабочие, нигде не подключены. Подключить (уберёт часть дублирующихся `except BotException`/`except ValidationError` в хендлерах) или удалить как забытый прототип?
3. **`_send_reminder_job` / `_mark_appointment_completed_job`** (`appointment_scheduler.py`) — используются только в тестах (сам docstring признаёт это). Удалить с переписыванием ~30 тестовых вызовов на модульные `send_reminder_job`/`mark_appointment_completed_job`, или оставить как согласованный компромисс ради простоты тестирования?
4. **`add_staff`, `remove_staff`, `is_staff`** (`staff_repository.py`) **+ `Config.admin_ids`** — вместе намекают на недостроенное управление персоналом (сейчас сотрудники заводятся хардкодом 3 telegram_id в `init()`). Это забытая заготовка под будущую фичу управления персоналом (тогда не удалять, а доделать) или чистый мусор (тогда удалить всё вместе, включая `ADMIN_IDS` из `.env`)? Отдельно: при удалении `admin_ids` стоит убрать и парсинг `os.getenv("ADMIN_IDS").split(",")` в `config.py:19-21` — он упадёт с `AttributeError`, если `ADMIN_IDS` не задана в `.env`, ещё до дружелюбной проверки токена.
5. **`bot/create_bot.py:28-30`** (`Base = declarative_base()` / `Base.metadata.create_all(...)`) — похоже на no-op (пустая metadata ничего не создаёт, реальную таблицу job store создаёт `SQLAlchemyJobStore`), но это код инициализации при старте бота — рекомендую проверить на живом запуске перед удалением, а не полагаться только на статический анализ.
6. **`JobSchedulingError` / `JobCancellationError`** (`appointment_exceptions.py`) — ловятся в 6 местах `appointment_scheduler.py`, но никогда не поднимаются (APScheduler кидает свои исключения). Обернуть реальные вызовы `scheduler.add_job`/`remove_job` в try/except с raise этих доменных исключений (тогда except-ветки станут осмысленными), или убрать недостижимые except-блоки и ловить исключения APScheduler напрямую?
