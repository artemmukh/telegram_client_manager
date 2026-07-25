# Промпт: автогенерация истории болезни (docx) через Ollama при завершении записи

Готовый промпт для мультиагентного workflow проекта
(`.claude/agents/workflow.md`: planner → researcher → implementer →
aiogram-expert / database-expert → test-expert → routine → reviewer).
Скопируй раздел "Задача для агента".

---

## Контекст и уже принятые решения

Нужно: после завершения записи (`AppointmentStatus.COMPLETED`) автоматически
сгенерировать заполненную медкарту (`.docx`) на основе данных клиента,
услуги и диагноза, используя локальную Ollama (`qwen3:8b`) для написания
свободнотекстовых полей. Готовый файл не рассылается пушем — он лежит на
диске и отдаётся по кнопке из карточки записи.

Ниже — что уже обсуждено и согласовано с заказчиком, менять без явного
запроса не нужно:

1. **Архитектура** — отдельная job + сервис (`MedicalRecordService`) +
   таблица `medical_records` для отслеживания статуса генерации
   (идемпотентность, ретраи, ответ на кнопку "документ готовится").
   Генерация не должна блокировать и не должна ронять смену статуса
   записи на `COMPLETED`, если Ollama недоступна или упала.
2. **Доставка** — файл только сохраняется на диск, никакого автоматического
   `send_document` врачу или клиенту ("иначе будет спам"). Вместо этого —
   кнопка **"📄 Получить историю болезни"** в карточке завершённой записи,
   видна **и админу/врачу, и клиенту**. По нажатию:
   - если документ готов — отправить файл (`send_document`);
   - если генерация ещё не закончена — ответить алертом вида "Документ
     ещё готовится, попробуйте через пару минут";
   - если генерации почему-то не было (edge case, статус `COMPLETED`, но
     записи в `medical_records` нет) — запустить генерацию по требованию
     как fallback и ответить "Документ ещё не создан, генерируем,
     попробуйте через пару минут".
3. **Триггер генерации** — сразу при переходе записи в `COMPLETED`, вне
   зависимости от того, каким путём это произошло:
   - админ нажал "Изменить" (`open_edit`) на T+1ч подсказке после приёма —
     генерация сразу после успешного `complete_appointment_by_admin`;
   - админ нажал "Пропустить" (`skip_edit`) на той же подсказке — тоже
     сразу, запись всё равно становится `COMPLETED`;
   - админ проигнорировал подсказку — на T+2ч сработает автокомплит
     (`auto_complete_appointment_job`) — генерация сразу после успешного
     `complete_confirmed_appointment`;
   - есть также редкий path в `AppointmentScheduler.schedule_appointment_autocomplete`
     (ветка "past-due" — если время автокомплита уже прошло на момент
     `resync_appointment_jobs`, статус меняется на `COMPLETED` немедленно,
     минуя job) — сгенерировать и там.

   Итого: единая точка правды — "сразу после того, как
   `complete_appointment_by_admin` или `complete_confirmed_appointment`
   вернули не-`None` (успешно перевели запись в `COMPLETED`)". Перед
   реализацией **обязательно перепроверить через
   `grep -rn "complete_appointment_by_admin\|complete_confirmed_appointment"`**,
   что других вызовов этих двух методов нет (на момент ресёрча их ровно 3:
   `appointment_completion.py::open_edit`, `appointment_completion.py::skip_edit`,
   `appointment_jobs.py::auto_complete_appointment_job` — плюс
   `appointment_scheduler.py::schedule_appointment_autocomplete`, которая
   тоже дёргает `complete_confirmed_appointment` напрямую в past-due ветке).
4. **Fallback при сбое Ollama** — ретрай (2–3 попытки с бэкоффом), если не
   помогло — сгенерировать документ **без** ИИ-полей (просто пустые
   строки в `complaints`/`diseases`/`examination`/`treatment`/`diagnosis`,
   как и предусмотрено промптом ниже: "если информации недостаточно —
   оставь пустую строку"). Ничего не должно "теряться" — документ в любом
   случае создаётся и помечается готовым, врач дозаполняет вручную. Статус
   в `medical_records` в этом случае можно пометить как `ready_partial`
   или просто `ready` (решает planner/implementer, не критично) — важно
   не заблокировать выдачу файла по кнопке.

## Плейсхолдеры реального шаблона

Шаблон — `data/history_of_illness/medical_card_wisdom_tooth.docx`
(докстрока `INPUT_FILE` в `pydocx.py` указывает неверный путь
`bot/data/...` — поправить). Плейсхолдеры `{{ }}` (docxtpl), подтверждены
скриншотом от заказчика:

```
{{ appointment_date }}   -- дата приёма
{{ full_name }}          -- ФИО клиента
{{ gender }}             -- пол
{{ birth_date }}         -- дата рождения
{{ phone }}              -- телефон
{{ diagnosis }}          -- развёрнутый диагноз (дополнять не надо, готовый диагноз уже пишет врач, например "37C")
{{ complaints }}         -- жалобы (генерит LLM)
{{ diseases }}           -- перенесённые и сопутствующие заболевания (генерит LLM)
{{ examination }}        -- объективный осмотр (генерит LLM)
{{ treatment }}          -- лечение (генерит LLM)
```

Плюс отдельная (не через docxtpl, а через прямую правку таблицы
`python-docx` после рендера) отметка зуба на зубной карте — уже частично
реализовано в `pydocx.py::find_tooth`/`find_marker`/`mark_tooth`, логику
переиспользовать, только исправить баги (см. пункт 2 ниже).

## Готовый промпт для Ollama (LLM-запрос, предоставлен заказчиком)

Заказчик уже сформулировал системный промпт и структуру JSON-ответа.
Использовать как есть, только подставить актуальные плейсхолдеры шаблона
и зафиксировать маппинг полей ответа → полей docx-шаблона (см. ниже,
это ключевой момент, не переставить местами):

```
Ты врач стоматолог.
На основе диагноза и шаблона заполни поля.
Верни ТОЛЬКО JSON.
Никаких пояснений.
Структура:
{
    "complaints": "",
    "anamnesis": "",
    "objective": "",
    "diagnosis_reason": "",
    "treatment_plan": ""
}
Пациент:
{patient}
Диагноз:
{diagnosis}
Шаблон:
{template}

Верни строго JSON.
Запрещено:
- Markdown
- ```json
- комментарии
- пояснения
Все ключи должны присутствовать.
Если информации недостаточно —
оставь пустую строку.
```

Где:

- `{patient}` — короткая сводка нужных для контекста полей пациента:
  `full_name`, `gender`, `birth_date` (LLM не должна выдумывать возраст
  из головы, если дата рождения известна — но также не обязана считать
  точный возраст, это не задача этого промпта).
- `{diagnosis}` — исходный текст диагноза/услуги, как его ввёл админ
  (`appointment.purpose`, ограничение 2–100 символов, см.
  `validate_purpose` в `bot/validators/validators.py`; это НЕ развёрнутый
  медицинский диагноз, а короткая формулировка вида "Средний кариес 37
  зуба" или "Консультация").
- `{template}` — можно передать не весь docx, а просто список полей,
  которые нужно заполнить, с краткими подписями из шаблона (Жалобы,
  Перенесённые и сопутствующие заболевания, Объективный осмотр, Диагноз,
  Лечение) — это и есть "инструкция по формату", не нужно скармливать
  модели XML/бинарник шаблона.

**Маппинг ответа LLM → плейсхолдеров шаблона** (важно, ключи в JSON и в
шаблоне называются по-разному):

| Ключ JSON от LLM | Плейсхолдер в `.docx` |
|---|---|
| `complaints` | `{{ complaints }}` |
| `anamnesis` | `{{ diseases }}` |
| `objective` | `{{ examination }}` |
| `diagnosis_reason` | `{{ diagnosis }}` |
| `treatment_plan` | `{{ treatment }}` |

`{{ appointment_date }}`, `{{ full_name }}`, `{{ gender }}`,
`{{ birth_date }}`, `{{ phone }}` заполняются напрямую из `Appointment`/
`User`, без участия LLM (эти данные уже надёжны и структурированы, LLM
их не трогает и не переформулирует).

Определение зуба/маркера для зубной карты (`find_tooth`/`find_marker` в
`pydocx.py`) должно работать по **исходному короткому** `{diagnosis}`
(тому, что ввёл админ), а не по сгенерированному `diagnosis_reason` —
короткая формулировка надёжнее для regex-поиска номера зуба и ключевого
слова, чем сгенерированный LLM развёрнутый текст.

## Задача для агента

### 0. Область действия — что НЕ трогать

- Не менять сам docx-шаблон `data/history_of_illness/medical_card_wisdom_tooth.docx`.
- Не менять логику `complete_appointment_by_admin`/`complete_confirmed_appointment`
  (условия перехода в `COMPLETED`) — только добавить вызов генерации
  документа **после** их успешного выполнения.
- Не добавлять автоматическую рассылку файла — только генерация +
  сохранение на диск + выдача по кнопке.
- Не трогать существующие reminder/expiry job'ы в `appointment_scheduler.py`/
  `appointment_jobs.py`, кроме точек, куда добавляется вызов генерации
  документа.

### 1. Ollama-клиент (`bot/services/llm/agent.py`)

Текущий `ChatLLM` нерабочий, переписать (по возможности сохранить имя
класса/модуль, если это не мешает архитектуре — иначе создать новый
файл рядом, например `bot/services/llm/medical_record_llm.py`, решает
planner):

- Исправить URL: `POST {base_url}/api/chat` (Ollama chat endpoint), а не
  голый `http://host:port`. `base_url` (`http://192.168.0.106:11434`) и
  модель (`qwen3:8b`) вынести в `Config`/`.env`
  (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`), не хардкодить IP в коде — по
  аналогии с тем, как уже вынесены `BOT_TOKEN`/`DATA_BASE` в
  `bot/config/config.py`.
- Метод должен быть **stateless** (без накопления `self.messages` между
  вызовами — каждая генерация документа независима, история диалога не
  нужна и вредна: раздувает контекст и может тянуть данные предыдущего
  пациента в следующий запрос).
- Передавать `messages=[{"role": "user", "content": <строка-промпт>}]` —
  `content` обязан быть строкой, а не dict.
- Указать `"format": "json"` в теле запроса к Ollama — это заставляет
  модель вернуть валидный JSON и снимает часть проблем с
  `<think>...</think>` у `qwen3` (thinking-моделей). Дополнительно после
  получения ответа явно вырезать возможный `<think>...</think>` блок
  регэкспом перед `json.loads`, на случай если `format: json` не до конца
  подавит reasoning-вывод у конкретной версии модели — не полагаться на
  один механизм.
- Реализовать ретраи (2–3 попытки, экспоненциальный бэкофф) на: сетевые
  ошибки httpx, `response.raise_for_status()`, невалидный JSON в ответе,
  отсутствие обязательных ключей (`complaints`, `anamnesis`, `objective`,
  `diagnosis_reason`, `treatment_plan`) в распарсенном JSON.
- Если все попытки исчерпаны — вернуть явный сигнал сбоя (например,
  `None` или кастомное исключение из `bot/exceptions/`), а не бросать
  наверх сырые httpx/JSON-ошибки — по правилам `CLAUDE.md`
  ("Raise domain exceptions... Never expose implementation details").
  Заведи в `bot/exceptions/` (или переиспользуй подходящее место) новое
  исключение, например `MedicalRecordGenerationError`, не создавай
  параллельную иерархию — расширяй существующие модули.
- Таймаут запроса — оставить щедрым (текущие 120с адекватны для 8B
  модели на локальном сервере), но не блокировать event loop бота:
  вызов уже `async`/`httpx.AsyncClient`, это ок, просто убедиться, что
  сам сервис-слой тоже вызывается из контекста джобы (см. пункт 3), а не
  из handler'а напрямую.

### 2. Генератор docx (`bot/services/document_generator/pydocx.py`)

Переписать с учётом реального рабочего кода проекта (см. пункт 0 списка
багов из ресёрча) и слоя Service/Repository, а не отдельным
скриптом с демо-данными:

- Убрать модульные демо-данные (`full_name = "Иванов Иван Иванович"` и
  т.п.) — они мёртвый код и не должны остаться.
- Убрать `from bot.run import logger` (циклический импорт, тянет весь
  бот) — использовать `logging.getLogger(__name__)` как везде в проекте.
- Исправить путь к шаблону: `data/history_of_illness/medical_card_wisdom_tooth.docx`
  (без `bot/` в начале) и сделать его независимым от текущей рабочей
  директории (например, через `pathlib.Path(__file__).resolve().parents[N]`
  или через конфиг — посмотри, как в проекте уже резолвятся пути к
  `data/price_list/*`, `data/location/*` в `price_list.py`/`geolocation.py`,
  и следуй тому же паттерну ради консистентности).
- Исправить `data.get(['diagnosis'])` → `data.get("diagnosis")` (баг с
  списком вместо строки, `TypeError: unhashable type: 'list'`) в обоих
  местах (`find_tooth`, `find_marker`).
- Исправить `logger.warning("Причинный зуб:", tooth)` →
  `logger.info("Причинный зуб: %s", tooth)` (и аналогично для маркера) —
  текущий вызов ломает форматирование logging.
- Имя выходного файла не должно содержать пробелы/двоеточия (проблема на
  Windows-хосте) — использовать `appointment.id` в имени файла вместо
  ФИО+datetime как есть сейчас, например:
  `medical_card_{appointment_id}.docx`. Директорию `.../temp/` создавать
  явно (`Path.mkdir(parents=True, exist_ok=True)`), если её нет.
- f-строка с вложенными одинарными кавычками (Python 3.12+ синтаксис) —
  переписать без вложенных кавычек одного типа, чтобы работало и на
  3.11 (в проекте есть `__pycache__` под 3.11 и 3.13 — целимся на
  совместимость с обеими).
- Синхронные `doc.save()`/`Document(...)` внутри `async def` блокируют
  event loop — обернуть тяжёлые синхронные вызовы в
  `asyncio.to_thread(...)` (стандартный способ не блокировать луп для
  CPU/IO-bound синхронного кода в асинхронном проекте на aiogram 3).
- `doc.tables[1]` — если это единственная зубная таблица в шаблоне,
  оставить, но добавить defensive-проверку (`IndexError`) с логом, а не
  падать без объяснения.
- Удалить временный файл (`TEMP_FILE`) после того, как из него собран
  `OUTPUT_FILE`, либо вообще не создавать промежуточный файл на диске —
  рассмотреть, можно ли работать через `io.BytesIO` для промежуточного
  шага (`docxtpl` рендерит в поток, `python-docx` открывает поток,
  отметка зуба, финальный `.save()` на диск только один раз) — предпочтительнее,
  меньше файлового мусора. Решает implementer, не критично, если сроки
  поджимают — тогда просто гарантированно удалять temp-файл в `finally`.
- Функция должна **возвращать** путь к готовому файлу (сейчас ничего не
  возвращает) — вызывающий код (сервис) должен получить путь для записи
  в `medical_records.file_path`.
- Функция должна принимать уже готовый `dict` с всеми пятью
  ИИ-сгенерированными полями (или пустыми строками при фоллбэке) +
  структурными полями пациента/записи — то есть весь маппинг
  "JSON от LLM → ключи шаблона" из таблицы выше происходит **в сервисе**
  (`MedicalRecordService`), а не внутри `pydocx.py` — репозиторно-сервисный
  слой не должен знать про формат ответа конкретной LLM, `pydocx.py`
  остаётся чистой функцией рендеринга шаблона по уже нормализованным
  данным (принцип "Repository/рендерер не содержит бизнес-логики").

### 3. Новая таблица и репозиторий: `medical_records`

По аналогии с существующими репозиториями (`AppointmentRepository` —
образец для `init()` через `PRAGMA table_info`/`ALTER TABLE`, см.
`CLAUDE.md` про SQLite→PostgreSQL совместимость — избегать
SQLite-специфичного SQL):

Минимальная схема:

```
medical_records
- id INTEGER PRIMARY KEY
- appointment_id INTEGER NOT NULL (FK на appointments.id, unique — одна
  запись-медкарта на один appointment)
- status TEXT NOT NULL  -- 'pending' | 'generating' | 'ready' | 'ready_partial' | 'failed'
- file_path TEXT NULL
- created_at TIMESTAMP
- updated_at TIMESTAMP
- error_message TEXT NULL  -- для диагностики последнего сбоя, не показывается пользователю
```

Создать `bot/models/medical_record.py` (dataclass `MedicalRecord`, по
образцу `bot/models/appointment.py`) и
`bot/repositories/medical_record_repository.py` (по образцу
`appointment_repository.py`) с методами вроде
`create_pending(appointment_id)`, `get_by_appointment_id(appointment_id)`,
`mark_ready(id, file_path, partial: bool)`, `mark_failed(id, error_message)`.
Репозиторий не валидирует и не содержит бизнес-логики — это делает
сервис.

### 4. `MedicalRecordService` (`bot/services/medical_record/medical_record_management.py`
или аналогичный путь, согласовать с planner по аналогии с
`bot/services/appointment/appointment_management.py`)

Оркестрирует:

1. Проверка идемпотентности — если `medical_records` для
   `appointment_id` уже существует и `status in (ready, ready_partial,
   generating)` — не запускать повторную генерацию (защита от гонок,
   если, например, кнопка "получить" случайно триггернёт генерацию
   параллельно с уже идущей).
2. Создание записи `pending`/`generating`.
3. Сбор данных: `Appointment` (datetime, purpose/диагноз, doctor),
   `User`/клиент (full_name, gender, birth_date, phone) через уже
   существующие репозитории/сервисы — переиспользовать
   `AppointmentManagement.get_appointment_by_id`/`get_client_by_id`, не
   дублировать SQL.
4. Вызов LLM-клиента (пункт 1) с ретраями внутри клиента; на итоговый
   сбой — не бросать исключение наружу без обработки, а зафиксировать
   fallback-путь (документ без ИИ-полей).
5. Вызов `create_docx`/рендерера (пункт 2) с нормализованным dict.
6. Обновление статуса записи в `medical_records` (`ready`/`ready_partial`/
   `failed`).
7. Метод `get_or_generate(appointment_id)` — используется хендлером
   кнопки "Получить историю болезни": если готово — вернуть путь сразу;
   если `generating`/`pending` — вернуть сигнал "ещё не готово"; если
   записи нет вовсе — создать и синхронно сгенерировать (fallback-путь
   из пункта 2 общих решений) или поставить в очередь и попросить
   подождать — решает implementer, но поведение должно быть
   задокументировано в docstring метода.

Сервис не знает про Telegram-объекты (правило `CLAUDE.md`).

### 5. Новая job + интеграция в существующие точки завершения

В `bot/services/appointment/appointment_jobs.py` (или отдельном
`bot/services/appointment/medical_record_jobs.py`, если так чище —
решает planner) — функция уровня модуля (для сериализации APScheduler,
хотя эта job скорее всего будет запускаться "fire-and-forget" сразу, а
не через `scheduler.add_job` с задержкой — см. ниже, это не 100%-но job
в смысле APScheduler, а просто фоновая асинхронная задача):

```python
async def generate_medical_record_job(appointment_id: int) -> None:
    """Generate the medical history docx for a just-completed appointment.

    Fires immediately after an appointment transitions to COMPLETED,
    regardless of path (admin edit/skip at T+1h, or silent auto-complete
    at T+2h). Creates its own bot/repositories/services to remain
    independent, matching the pattern of other module-level job functions
    in this file.
    """
```

Внутри — создаёт `MedicalRecordRepository`/`MedicalRecordService`
(аналогично тому, как остальные job'ы создают свои repo/service с нуля),
вызывает генерацию, логирует успех/неудачу. Всё оборачивается в
`try/except Exception` с логом — сбой генерации документа **никогда** не
должен всплывать наружу и не должен влиять на уже свершившийся переход
статуса записи в `COMPLETED` (эта job вызывается **после** того, как
статус уже сохранён).

Точки вызова (запускать как
`asyncio.create_task(generate_medical_record_job(appointment.id))`,
не блокируя ответ пользователю/хендлеру, либо через
`scheduler.add_job(..., run_date=<сейчас>)`, если в проекте принято
всё асинхронное фоновое делать через APScheduler, а не голый
`create_task` — уточнить у researcher, как в проекте уже принято
использовать background-задачи; если нигде не используется голый
`create_task`, предпочесть `scheduler.add_job` ради единообразия и
чтобы job переживала быстрый рестарт процесса благодаря persistent
jobstore):

1. `bot/handlers/admin/appointment_management/appointment_completion.py`:
   - `open_edit` — после успешного `complete_appointment_by_admin` (после
     блока `if appointment_scheduler: await appointment_scheduler.resync_appointment_jobs(appointment)`).
   - `skip_edit` — аналогично, в том же месте по структуре.
2. `bot/services/appointment/appointment_jobs.py::auto_complete_appointment_job` —
   после успешного `complete_confirmed_appointment` (сейчас там просто
   `logger.info(...)` и всё, добавить туда же).
3. `bot/services/appointment/appointment_scheduler.py::schedule_appointment_autocomplete` —
   past-due ветка, после `completed = await self.appointment_management.complete_confirmed_appointment(appointment.id)`
   и проверки `if completed is not None:`.

Внедрение зависимости `MedicalRecordService` в эти хендлеры/джобы —
через тот же паттерн DI, что и остальные сервисы (конструктор роутера/
джобы принимает сервис или создаёт его сама, как остальные
module-level job-функции создают свои repo/service с нуля — см.
`appointment_jobs.py`, там паттерн уже установлен, повторить его).
В `bot/run.py` и `bot/services/appointment/appointment_scheduler.py`
(конструктор `AppointmentScheduler`) добавить `medical_record_service`
аналогично тому, как туда уже инжектированы `notification_service`/
`appointment_management`.

### 6. Кнопка "Получить историю болезни" — admin-сторона

- `bot/keyboards/admin/record_management_kb/appointment_browser_cb.py`:
  добавить действие в `ApptActionCB` не требуется (поле `action: str`
  уже произвольная строка) — использовать значение `action="get_medical_record"`.
- `bot/keyboards/admin/record_management_kb/appointment_browser_kb.py`:
  в `appointment_card_kb`, в ветке `if post_appt:` (карточка
  завершённой записи) — не подходит, `post_appt` это ветка "прямо
  сейчас редактируем после приёма" (T+1ч подсказка), а не "уже
  завершённая запись в списке". Кнопка нужна там, где
  `status == AppointmentStatus.COMPLETED` в обычной (не `post_appt`)
  ветке карточки — добавить рядом с блоком
  `if status in _STATUS_CHANGE_MENU_STATUSES:` новое условие
  `if status == AppointmentStatus.COMPLETED:` с кнопкой
  `"📄 Получить историю болезни"` →
  `ApptActionCB(action="get_medical_record", appointment_id=..., mode=mode, page=page)`.
- `bot/handlers/admin/appointment_management/appointment_browser.py`:
  добавить обработчик
  `@router.callback_query(ApptActionCB.filter(F.action == "get_medical_record"))`
  по образцу соседних `action`-хендлеров в этом файле. Логика:
  вызвать `medical_record_service.get_or_generate(appointment_id)`,
  если путь готов — `await callback_query.message.answer_document(FSInputFile(path))`
  (см. паттерн `FSInputFile` в `price_list.py`/`geolocation.py`), иначе —
  `await callback_query.answer("Документ ещё готовится, попробуйте через пару минут", show_alert=True)`.
- Прокинуть `medical_record_service` в
  `create_admin_appointment_browser_router(...)` и в вызов этой функции
  в `bot/run.py`.

### 7. Кнопка "Получить историю болезни" — client-сторона

Симметрично пункту 6, но в клиентских файлах:

- `bot/keyboards/client/appointment_history_cb.py` — `ClientHistoryActionCB`
  уже имеет свободное поле `action: str`, использовать
  `action="get_medical_record"`.
- `bot/keyboards/client/appointment_history_kb.py` —
  `appointment_history_card_kb` сейчас строит кнопки только через
  `_add_status_action_buttons` (cancel/reschedule) — добавить кнопку
  `"📄 Получить историю болезни"` при `appointment.status == AppointmentStatus.COMPLETED`
  (нужно прокинуть статус в эту функцию, если сейчас он туда не
  передаётся — проверить сигнатуру и вызывающий код через
  `grep -rn "appointment_history_card_kb"`).
- Найти хендлер, который строит карточку истории клиента (вероятно,
  `bot/handlers/client/appointment_response.py` или отдельный файл,
  использующий `bot/handlers/utils/client_utils/appointment_history_helpers.py`
  — researcher должен найти точный файл) и добавить обработчик действия
  `get_medical_record` по тому же принципу, что в пункте 6, но с
  `answer_document` в клиентский чат.
- Прокинуть `medical_record_service` в конструктор соответствующего
  роутера и в `bot/run.py`.

### 8. `requirements.txt`

Уже присутствуют `httpx`, `docxtpl`, `python-docx` — новых зависимостей
не требуется, если не решите использовать что-то для ретраев
(`tenacity`) — не обязательно, можно ретраить вручную циклом, чтобы не
плодить зависимости без необходимости (`CLAUDE.md`: "Do not introduce
new abstractions unless explicitly requested").

### 9. Тесты

- `tests/` (найти существующую структуру через `grep -rl "AppointmentManagement" tests/`
  для соблюдения стиля фикстур/фейков — переиспользовать `repo-test-fakes`
  skill, см. `.claude/skills/repo-test-fakes/SKILL.md`):
  - Тест `MedicalRecordRepository`: создание/чтение/обновление статуса,
    уникальность по `appointment_id`.
  - Тест `MedicalRecordService.generate(...)`: успешный путь (мок LLM
    возвращает валидный JSON) → docx создан, статус `ready`; путь с
    сбоем LLM после исчерпания ретраев → docx создан **без** ИИ-полей,
    статус `ready_partial`/`ready` (что решили в пункте 4); повторный
    вызов при уже `ready` — не перегенерирует (идемпотентность).
  - Тест на маппинг JSON-ключей LLM → плейсхолдеров шаблона (таблица
    выше) — отдельный юнит-тест, не полагаться только на
    end-to-end проверку.
  - Тест `find_tooth`/`find_marker` — теперь на корректно переданной
    строке (не списке), покрыть кейсы "кариес", "пульпит", "удаление",
    "нет совпадения".
  - Тест на все 3–4 точки вызова генерации: замокать
    `MedicalRecordService`, убедиться, что после успешного
    `complete_appointment_by_admin`/`complete_confirmed_appointment` (во
    всех точках из пункта 5) генерация действительно вызывается ровно
    один раз, и что сбой генерации не мешает основному ответу
    хендлера/джобы клиенту/админу.
  - Тест на хендлеры кнопки "Получить историю болезни" (admin и client):
    статус `ready` → `send_document` вызван с верным путём; статус
    `generating`/`pending` → `callback_query.answer` с алертом, без
    `send_document`; записи нет вовсе → триггерится
    `get_or_generate`-фоллбэк.
  - Обновить `docs/manual_qa_checklist.md`: добавить сценарий "запись
    завершена (любым из трёх путей) → через некоторое время нажать
    'Получить историю болезни' у админа и у клиента → файл приходит и
    открывается, поля соответствуют данным записи, зуб на карте отмечен
    правильно".

### Порядок выполнения (обязателен по workflow.md)

1. **planner** — фиксирует scope по разделам выше (архитектура/доставка/
   триггер/фоллбэк уже согласованы заказчиком, не пересматривать; решает
   только технические детали, явно оставленные "на усмотрение
   implementer/planner" в тексте выше — например точный путь модулей,
   `create_task` vs `scheduler.add_job`, статус `ready` vs
   `ready_partial`).
2. **researcher** — перепроверяет актуальность всех grep-находок из
   этого промпта (пути к файлам/строкам могли измениться), находит
   точный файл клиентского хендлера карточки истории (пункт 7), находит
   существующий стиль тестовых фейков в `tests/`.
3. **database-expert** — схема `medical_records`, репозиторий, миграция
   через `init()` по паттерну `PRAGMA table_info`/`ALTER TABLE`
   (см. `sqlite-to-postgres-step` skill на предмет совместимости с
   будущей PostgreSQL-миграцией — избегать SQLite-специфичных типов).
4. **implementer** — Ollama-клиент, `pydocx.py`, `MedicalRecordService`,
   job, интеграция в 3–4 точки завершения. Прочитать
   `python-backend-guidelines` SKILL.md перед началом (async I/O,
   `asyncio.to_thread` для блокирующих вызовов `python-docx`/`docxtpl`).
5. **aiogram-expert** — кнопки и хендлеры в 4 файлах (admin card kb,
   admin browser handler, client history kb, client history handler),
   `answer_document`/`FSInputFile`, алерты на "документ готовится".
6. **test-expert** — тесты по пункту 9, использовать `repo-test-fakes`
   skill.
7. **routine** — обновление `docs/manual_qa_checklist.md`, чистка
   docstring'ов, если где-то остались следы демо-данных/старых
   комментариев.
8. **reviewer** — сверка с `CLAUDE.md`: бизнес-логика только в Service/
   job-функциях (не в хендлерах, не в `pydocx.py`), никакого SQL вне
   репозитория, никаких Telegram-объектов в сервисах, генерация
   документа не блокирует и не ломает существующий flow завершения
   записи, IP/URL Ollama не захардкожены в коде.

### Definition of Done

- При завершении записи любым из трёх путей (admin "изменить"/"пропустить"
  на T+1ч подсказке, автокомплит T+2ч, past-due ветка автокомплита)
  автоматически запускается генерация медкарты в фоне, не блокируя ответ
  пользователю и не влияя на смену статуса записи.
- Готовый `.docx` сохраняется на диск с путём, привязанным к
  `appointment_id`; файл не рассылается пушем.
- И у админа/врача, и у клиента в карточке завершённой записи есть
  кнопка "📄 Получить историю болезни": отдаёт файл, если готов; вежливо
  просит подождать, если генерация ещё идёт; на edge-case (записи в
  `medical_records` нет) — запускает генерацию по требованию.
- Если Ollama недоступна/вернула мусор — после ретраев документ всё
  равно создаётся, но с пустыми ИИ-полями (ничего не падает и не
  теряется), врач дозаполняет вручную.
- Зубная карта в документе отмечается по исходному короткому диагнозу
  (`appointment.purpose`), а не по развёрнутому LLM-тексту.
- IP-адрес/модель Ollama вынесены в конфиг, не захардкожены.
- `pytest` зелёный, включая новые тесты; `docs/manual_qa_checklist.md`
  обновлён.
