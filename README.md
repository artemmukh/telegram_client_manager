# 🏥 Medical Appointment Telegram Bot

A Telegram bot for managing patients and appointments in a private clinic — built with **aiogram 3**, **SQLite**, and a strict layered architecture.

Two roles share one bot: **administrators** (doctors and clinic admins), who run the clinic's day-to-day schedule, and **clients**, who register, book, and manage their own appointments straight from Telegram.

---

## ✨ Features

### 👤 Client

- **Registration** — clients register via Telegram and get linked to an existing patient profile by phone number.
- **Self-booking wizard** — choose a doctor → pick a day (with weekly pagination) → pick a free time slot → describe the reason for the visit → confirm. The request goes to the clinic as a booking request.
- **Booking negotiation** — the clinic can confirm, reject, or propose a different time for a pending request; the client accepts or declines the proposed time.
- **Manage own appointments** — view upcoming/past appointments by status (confirmed, pending, cancelled, no-show, completed, expired), cancel, or request a reschedule on a confirmed appointment (subject to a minimum-notice cutoff enforced by the service layer).
- **Reminders** — configurable 24h and 2h reminders before an appointment; the 2h reminder includes "I'll come" / "I won't come" buttons.
- **Profile** — view personal info, request a name change (requires admin approval), and adjust reminder preferences.
- **Price list & clinic location** — sent as photos on request.

### 👨‍⚕️ Administrator

- **Full client CRUD** — create, search (by name or phone), edit, and delete patient records.
- **Full appointment CRUD** — create appointments directly, browse/search all appointments with pagination, filter by status tab, edit date/time/purpose/price, change status, or delete.
- **Booking & reschedule request review** — confirm/reject/counter-propose a client's booking request; accept/reject a client's reschedule request.
- **Post-appointment workflow** — mark a finished appointment as completed or no-show; appointments auto-transition on a schedule if left untouched.
- **Reminders mirrored to admin** — the staff member who created the appointment gets the same 24h/2h reminders as the client.
- **Name-change approval** — approve or reject a client's self-service name change request.

### 🩺 Medical Records

- **Record generation** — after an appointment, clinic staff can request automatic generation of a filled medical record (medical card, history of illness, treatment plan). AI-powered extraction of complaints, diseases, examination findings, treatment plan, and tooth map from free-text input.
- **Per-clinic configuration** — each clinic instance has an optional Word template (`.docx`); templates are loaded from `data/` and rendering includes tooth-map tables keyed by FDI numbers.
- **Integrated workflow** — accessible from appointment browser (admin) and appointment-details view (client).

### ⚙️ Behind the scenes

- **Multi-clinic deployment** — the same codebase runs as a separate OS process per clinic (`BOT_INSTANCE=zb` / `mm`), each with its own bot token, SQLite database, seed staff, price list, and medical-record template — see `bot/config/clinic_instances.py`.
- Background jobs (via **APScheduler**) handle reminders, auto-completion, and the expiry of unanswered booking/reschedule requests — all cancelled and rescheduled automatically as appointment state changes.
- Natural-language Russian date/time parsing (`dateparser`) for both admin and client input ("завтра в 15:00", "в пятницу утром", etc.).
- Two-way Telegram notifications between client and clinic on every state change, with graceful failure handling so a failed notification never breaks the underlying action.

---

## 🤖 AI Roadmap

The project is designed to grow into an AI-assisted assistant:

- 🎙️ Voice message recognition (Whisper)
- 💬 Natural language appointment creation from free text
- 🧠 Automatic extraction of patient / date / time / service from a single message
- 🖥️ Local LLM support via Ollama, so appointments can be created without manual admin input at all
- 📋 Subscription system and automated recurring appointments

---

## 🛠️ Technology Stack

| | |
|---|---|
| Language | Python 3 |
| Bot framework | aiogram 3.29 |
| Database | SQLite via `aiosqlite` 0.22 |
| Scheduling | APScheduler 3.11 |
| Date parsing | `dateparser` ≥1.1 |
| AI / LLM | Mistral AI (via `mistralai` SDK, hosted API) |
| Document generation | `docxtpl` + `python-docx` |
| Testing | pytest 9 + pytest-asyncio 1.2 |

**Planned:** PostgreSQL (multi-clinic scale), Whisper, local LLMs (Ollama).

---

## 🏗️ Architecture

Strict layered architecture — each layer only talks to the one directly below it:

```
Handler  (Telegram updates, FSM transitions, calling services)
   ↓
Service  (business logic, validation, orchestration)
   ↓
Repository  (SQL, row → domain model mapping)
   ↓
SQLite
```

Supporting layers sit alongside: **Validators**, **FSM States**, **Keyboards**, **Middlewares** (logging, error handling, current-user resolution), and **Filters** (role-based access). Domain exceptions (e.g. `AppointmentNotFoundError`, `CancellationWindowExpiredError`) replace raw database/Telegram errors at the boundary.

---

## 📂 Project Structure

```text
bot/
├── config/            # env-driven config, clinic instances, booking constants
├── create_bot.py      # bot factory
├── loader.py          # dependency injection setup
├── run.py             # entry point
├── exceptions/        # domain exceptions (appointment, user, medical_record)
├── handlers/          # Telegram routers (admin/, client/, common/)
├── keyboards/         # inline/reply keyboards, callback factories
├── middlewares/       # logging, error handling, user resolution
├── models/            # domain models (User, Appointment, Clinic, Staff)
├── repositories/      # SQL access (clinic, staff, user, appointment, client_clinic, user_settings, medical_record)
├── services/          # business logic
│   ├── appointment/   # appointment workflows
│   ├── client/        # client-facing flows
│   ├── llm/           # Mistral AI integration (ChatLLM agent)
│   ├── document_generator/  # Word document rendering (pydocx)
│   ├── medical_record/      # medical record orchestration service
│   └── utils/         # shared utilities
├── states/            # aiogram FSM state groups
├── validators/        # input validation
└── utils/             # enums, role filters, helpers

tests/                 # unit + real-SQLite integration + E2E test suite (83 test files)
docs/                  # design notes, QA checklists
```

---

## 📌 Project Status

🚧 **Active development.**

Core flows are implemented and covered by an extensive automated test suite: patient CRUD, self-booking, booking/reschedule negotiation, reminders, auto-completion, name-change approval, and medical record generation. Additional AI-assisted features (voice, NLP appointment creation, local LLM, subscriptions) are on the roadmap but not started.

---

## 📄 License

Licensed under the [MIT License](LICENSE).
