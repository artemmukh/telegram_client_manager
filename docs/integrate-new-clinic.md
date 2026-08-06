# Гайд: интеграция новой клиники в Medical Appointment Telegram Bot

Модель мультиклиничности в проекте простая: **1 клиника = 1 инстанс = отдельный процесс бота + отдельная SQLite-БД**.
Всё специфичное для клиники завязано на строковый код инстанса (`BOT_INSTANCE`), который сейчас принимает значения `zb` и `mm`.

Ниже — шаги для добавления новой клиники с условным кодом **`nc`** (замените на свой).

---

## 1. `bot/config/clinic_instances.py`

Центральный файл со всеми данными клиники. Добавить туда:

- **`CLINIC_SEED_BY_INSTANCE["nc"]`** — `name` и `token` клиники.
- **`STAFF_SEED_BY_INSTANCE["nc"]`** — telegram_id админов/врачей, которых нужно засеять при первом запуске.
  Добавление новых сотрудников позже делается так же — через этот список + рестарт процесса (отдельного admin-UI для этого нет).
- **`PRICE_LIST_BY_INSTANCE["nc"]`** — пути к картинкам прайса по языкам (`ru`/`uz`). Если не добавить запись — сработает `PRICE_LIST_STUB_MESSAGE` ("прайс скоро появится").
- **`LOCATION_BY_INSTANCE["nc"]`** — путь к картинке и подпись с адресом. Аналогично, без записи — стаб `LOCATION_STUB_MESSAGE`.
- **`DATEPARSER_BY_INSTANCE["nc"] = "slots"`** (у обеих текущих клиник так).
- **`MEDICAL_RECORD_TEMPLATE_BY_INSTANCE["nc"]`** — путь к `.docx`-шаблону медкарты, либо `None`, если шаблон ещё не готов.

## 2. Новый конфиг рабочих часов

Создать `bot/config/nc_data_parser_cfg.py` по образцу `mm_data_parser_cfg.py` / `zb_data_parser_cfg.py`:

```python
nc_cfg = {
    "WORKING_HOURS_START": "9:00",
    "WORKING_HOURS_END": "18:00",
    # "BREAK_START": "13:00",   # опционально
    # "BREAK_END": "14:00",
    "SLOT_STEP_MINUTES": 30,
    "WORKING_WEEKDAYS": (0, 1, 2, 3, 4, 5),  # Mon=0 ... Sat=5, Sunday=6 — выходной
    "BOOKING_HORIZON_DAYS": 14,
    "MAX_PENDING_REQUESTS_PER_CLIENT": 1,
    "CANCELLATION_COOLDOWN_WINDOW_MINUTES": 5,
    "MAX_CANCELLATIONS_PER_COOLDOWN_WINDOW": 3,
    # "MAX_BOOKINGS_PER_SLOT": 1,  # опционально
}
```

## 3. `bot/config/booking_config.py`

Импортировать новый cfg и дописать его в словарь инстансов:

```python
from bot.config.nc_data_parser_cfg import nc_cfg
...
_cfg = {"zb": zb_cfg, "mm": mm_cfg, "nc": nc_cfg}.get(_instance, zb_cfg)
```

## 4. `bot/config/config.py`

Единственное по-настоящему обязательное изменение кода вне двух файлов выше. В `token_by_instance` (около строки 27) добавить:

```python
token_by_instance = {
    "zb": os.getenv("BOT_TOKEN_ZB"),
    "mm": os.getenv("BOT_TOKEN_MM"),
    "nc": os.getenv("BOT_TOKEN_NC"),
}
```

Без этого `load_config()` не узнает про новый инстанс и упадёт с `RuntimeError`.

## 5. Материалы клиники в `data/`

Положить файлы, на которые ссылаются пути из шага 1:

- `data/price_list/...` — картинки прайса.
- `data/location/...` — фото/скрин локации.
- `data/history_of_illness/...` — docx-шаблон медкарты (если есть).

## 6. Переменные окружения для нового процесса

Клиники — это отдельные ОС-процессы, каждому нужен свой набор env-переменных (отдельный `.env` / systemd unit / screen-сессия):

```
BOT_TOKEN_NC=<токен от BotFather>
BOT_INSTANCE=nc
DATA_BASE=<путь к отдельному .sqlite файлу этой клиники>
MISTRAL_API_KEY=<общий ключ, тот же что у остальных>
```

Общая БД между клиниками не используется — у каждой своя.

## 7. Захардкоженная развилка, на которую стоит обратить внимание

`bot/handlers/admin/appointment_management/appointment_creation.py:464`:

```python
if instance == "zb":
    # текст "цель визита"
else:
    # текст "жалоба/проблема"
```

Новая клиника по умолчанию попадёт в ветку `else` (текст как у `mm`). Если нужен другой текст — добавить туда явное условие для `nc`.

## 8. Что трогать не нужно

`bot/create_bot.py` (job store APScheduler) и `bot/loader.py` (Bot/notifier) уже полностью работают через `config.instance` / `config.bot_token` — для нового инстанса они сами создадут `data/reminders_nc.db` и т.д.

## 9. Первый запуск

```
BOT_INSTANCE=nc python -m bot.run
```

Все `*Repository.init()` (clinic, staff, appointment, user...) сами создадут таблицы и засеют клинику/стафф в новой БД при старте.

## 10. Проверка

- `pytest`
- `ruff check .`
- Вручную в Telegram: `/start`, прайс-лист, геолокация, само-запись клиента, создание записи админом, генерация медкарты (если задан шаблон).

## 11. Не забыть про билингвальность (ru/uz)

В проекте весь пользовательский текст хранится как словарь `{"ru": ..., "uz": ...}` и достаётся через `.get(lang, ...["ru"])`, где `lang` — это `current_user.language` (поле `User.language`, по умолчанию `"ru"`). Это касается всего, что видит клиент/админ, и добавление новой клиники не должно ломать этот паттерн:

- **Все новые константы для `nc` в `clinic_instances.py` — на двух языках.** `PRICE_LIST_BY_INSTANCE["nc"]["caption"]`, `LOCATION_BY_INSTANCE["nc"]["caption"]` — обязательно оба ключа `ru` и `uz` (даже если картинка одна на оба языка, как сделано для `mm`, где `uz`-прайс совпадает с `ru`-прайсом за неимением отдельного скана).
- **Если для клиники добавляется новый текст в хендлерах/клавиатурах** (например под условие `instance == "nc"` по аналогии с п.7) — он тоже оформляется как `{"ru": "...", "uz": "..."}` и достаётся через `.get(lang, ...)`, а не как голая строка. Смотреть образец в `bot/messages/common.py` / `bot/messages/booking.py`.
- **docx-шаблон медкарты** (`MEDICAL_RECORD_TEMPLATE_BY_INSTANCE["nc"]`) сейчas не локализуется — язык шаблона не выбирается по `User.language`; если для новой клиники это важно, потребуется отдельная доработка (сейчас есть только один путь на инстанс, без разбивки по языку).
- **Стабы** (`PRICE_LIST_STUB_MESSAGE`, `LOCATION_STUB_MESSAGE`) уже двуязычные и переиспользуются для любой клиники без прайса/локации — их трогать не нужно.
- При ревью/тестировании — пройти флоу `/start` → прайс → локация → бронирование дважды: один раз с `ru`, один раз с `uz` (переключается через `language_settings_kb`), чтобы убедиться, что для `nc` нигде не всплывает "сырой" английский/русский текст без узбекского варианта.

---

**Итог:** архитектура уже рассчитана на N клиник — почти всё сводится к данным в `clinic_instances.py` / `booking_config.py` / `config.py`, а не к новому коду.
