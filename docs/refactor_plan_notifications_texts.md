# План рефакторинга: баг меню, error middleware, notification-сервисы, i18n текстов

Статус: черновик, ожидает одобрения по фазам.

Все фазы идут через обязательный workflow проекта (`.claude/agents/workflow.md`):
planner → researcher → implementer → [aiogram-expert / database-expert при необходимости]
→ test-expert → routine → reviewer. Порядок фаз ниже выбран по зависимостям и риску:
сначала прод-баг, потом снижение риска (middleware), потом изолированный сервисный
рефакторинг, и в конце — самая объёмная, но наименее рискованная механическая правка текстов.

---

## Фаза 1 — баг show_main_client_menu

Баг: `bot/handlers/common/start.py:35` вызывает `show_main_client_menu(message, current_user.full_name)`
с двумя аргументами, а `bot/utils/info.py:15` требует три —
`(message, full_name, clinic_name)`. При повторном `/start` у уже зарегистрированного
клиента (`Role.CLIENT`) падает `TypeError`.

Задача: передать `current_user.clinic_name` третьим аргументом в вызове `start_client()`.
Проверить, нет ли других мест с тем же несовпадением сигнатуры
(`grep show_main_client_menu`).

Workflow: planner → researcher (найти все call sites) → implementer → test-expert
(добавить regression-тест на `/start` для уже зарегистрированного клиента, см. skill
`.claude/skills/repo-test-fakes`) → reviewer.
aiogram-expert не требуется (это несовпадение сигнатуры функции, не Telegram-логика).

---

## Фаза 2 — ErrorMiddleware: catch-all

`bot/middlewares/error.py` сейчас ловит только `ValidationError` и `BotException`.
Любое другое непредвиденное исключение (`TypeError`, `KeyError` и т.п.) не
перехватывается централизованно — либо падает сырым traceback, либо тихо глушится
bare `except Exception: pass` в отдельных хендлерах
(`bot/handlers/client/appointment_booking.py:226,248`,
`bot/handlers/admin/appointment_management/appointment_creation.py:346`).

Задача: добавить catch-all `except Exception` в `ErrorMiddleware` с `logger.exception`
и единым сообщением пользователю ("Произошла ошибка, мы уже разбираемся"), не убирая
существующую обработку `ValidationError`/`BotException`. Не трогать точечные
`except Exception` в notification-путях — там это осознанный graceful degradation
(если сомнение — уточнить у reviewer'а, зачем).

Workflow: planner → researcher → aiogram-expert (это `BaseMiddleware`, aiogram-специфика)
→ implementer → test-expert → reviewer.

---

## Фаза 3 — вынести Telegram-вызовы из notification-сервисов в адаптер

`bot/services/appointment/appointment_notifications.py` (749 строк) и
`bot/services/client/client_notifications.py` (112 строк) держат объект aiogram `Bot`
и напрямую вызывают Telegram API (`TelegramBadRequest`, `ReplyParameters`) —
нарушение правила CLAUDE.md "Services never know about Telegram objects".

Задача: создать `TelegramNotifier` (`bot/services/utils/telegram_notifier.py` или
`bot/services/notification/`), перенести туда все прямые `Bot`-вызовы и обработку
`TelegramBadRequest`. `AppointmentNotificationService` и `ClientNotificationService`
получают `TelegramNotifier` через DI вместо `Bot`, публичные методы (сигнатуры)
не менять — 22 места использования в проекте не должны требовать правок, кроме
DI-проводки в `bot/loader.py` и `bot/create_bot.py`.

Обязательно прочитать `.claude/skills/python-backend-guidelines/SKILL.md` перед
правкой (async I/O, архитектура бэкенда) — включить путь в промпт implementer'а
и test-expert'а.

Workflow: planner → researcher (найти все 22 usage) → implementer (+ skill
python-backend-guidelines) → aiogram-expert (Bot/Telegram-логика затронута) →
test-expert (+ skill repo-test-fakes, т.к. это сервис-слой) → routine (обновить
импорты/докстроки) → reviewer.

---

## Фаза 4 — централизация текстов интерфейса (i18n-слой)

275+ строковых литералов на русском разбросаны по 28 файлам `handlers/` без
единого слоя сообщений (частично вынесены в `bot/utils/info.py`, но большинство —
inline). Дублирование тона ("Помощь" vs "Справка" для одной и той же функции у
клиента и админа), блокер для будущей мультиязычности.

Задача: завести `bot/utils/messages.py` (или пакет `bot/messages/` по доменам:
registration, booking, admin) с константами/функциями текстов. Мигрировать
handlers один домен за раз (booking → registration → admin client_management →
admin appointment_management → common), не трогая бизнес-логику и не меняя сами
тексты (только перенос, не редактирование формулировок — это отдельная задача,
если понадобится).

Это самая крупная фаза — предлагается бить её на под-фазы по доменам, чтобы
каждый PR был маленьким и review проходил быстро.

Workflow (на каждый под-домен): planner → researcher → implementer → test-expert
→ routine (механический перенос строк — можно поручить Routine agent целиком,
раз это "mechanical work: formatting, renames") → reviewer.
Использовать `SuperPowers` (`.claude/skills/SuperPowers`) для первого под-домена,
чтобы зафиксировать паттерн (plan → spec → TDD → implement → review), дальше
переиспользовать паттерн без полного цикла SuperPowers.

### Зафиксированная конвенция (по итогам домена booking, применять к остальным)

- Структура: пакет `bot/messages/`, один файл на домен (`booking.py`, `registration.py`,
  ...), админ-домены — под `bot/messages/admin/` (`client_management.py`,
  `appointment_management.py`), зеркалируя `bot/handlers/admin/`. `bot/messages/__init__.py`
  остаётся пустым, реэкспортов нет — импортировать всегда из конкретного подмодуля.
- Импорт везде единообразно: `import bot.messages.<domain> as msg`, обращение
  `msg.CONSTANT` / `msg.some_prompt(...)`. Не использовать `from ... import ИМЯ`.
- Именование: plain-текст без интерполяции — `UPPER_SNAKE_CASE` константа без
  доменного префикса (модуль уже даёт контекст через `msg.`), например `CHOOSE_DAY`,
  `INVALID_DATE`, `SUBMITTED`. Текст с интерполяцией/композицией — функция
  `snake_case(...) -> str`.
- Правило анти-дедупликации: если один и тот же литерал повторяется в нескольких
  билдерах клавиатур (например "❌ Отмена" в 5 разных кнопках), не сводить к одной
  константе — каждой присваивается отдельное имя с префиксом виджета-владельца
  (`<KB_ИМЯ_ФУНКЦИИ>_<ДЕЙСТВИЕ>`, например `BOOKING_CANCEL_KB_CANCEL`,
  `BOOKING_DAY_KB_BACK`). Значения остаются идентичными, но перенос остаётся
  прослеживаемым по каждому call site.
- Форматирующая/рендер-логика (например таблица дней недели и её date-based
  f-строка в `booking_kb.py`) не переносится — это не текстовый литерал, а логика
  отображения клавиатуры, остаётся на месте.
- Тексты кнопок/сообщений общих виджетов, используемых несколькими доменами
  (пример: `appointment_manage_empty_kb`, используется booking/response/reschedule),
  временно кладутся в домен, который их мигрировал первым; при выполнении под-фазы
  `common` — рассмотреть перенос в `bot/messages/common.py`.
- Конструктор-строки доменных исключений (`bot/services/**/exceptions`,
  `bot/validators/validators.py`) остаются вне этой миграции — они уже вынесены в
  именованные константы на уровне сервисов/валидаторов, и перенос в
  `bot/messages/` (слой, используемый handlers/keyboards) размыл бы границу
  Service/Handler из CLAUDE.md.

---

## Следующий шаг

Ожидает одобрения: подтвердить фазы как есть, или указать правки по содержанию,
порядку, либо с какой фазы начинать выполнение.
