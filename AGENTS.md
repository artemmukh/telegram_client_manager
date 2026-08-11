# AGENTS.md

This file provides guidance to AI coding agents working with code in this
repository. It follows the open [AGENTS.md](https://agents.md) format — a
README for agents. Any agent that reads AGENTS.md (Claude Code, Codex, Cursor,
Aider, ...) should treat these rules as authoritative.

# Medical Appointment Telegram Bot

This document defines the development rules for AI agents working on this project.

These rules take precedence over default coding preferences.

---

# Core Principles

This project prioritizes:

1. Readability over cleverness.
2. Explicit code over abstraction.
3. Small focused modules.
4. Predictable architecture.
5. Reuse existing code before creating new code.
6. Incremental refactoring over large rewrites.
7. Maintain consistency with the existing codebase.

When unsure, prefer the simplest implementation that matches the current project style.

---

# Project Overview

Medical Appointment Telegram Bot built with:

- Python
- aiogram 3
- aiosqlite (SQLite; PostgreSQL migration planned)
- Asyncio
- APScheduler (reminders, expiry jobs)
- pytest / pytest-asyncio (extensive suite in tests/)

The project currently manages:

- Clinics (clinics table, ClinicRepository)
- Staff: doctors and clinic administrators (Staff model; visibility_scope "own" = doctor, "clinic" = admin; both have Role.ADMIN)
- Clients (User model, Role.CLIENT)
- Appointments (Appointment model, AppointmentStatus: pending/confirmed/cancelled/completed/no_show/expired)
- Client self-booking requests with confirm / reject / propose-new-time negotiation
- Reschedule negotiation (proposed_datetime / proposed_by)
- Slot blocking (BlockedSlot model, BlockedSlotRepository, SlotBlockingService) — per-doctor or clinic-wide date-time ranges with a reason; blocked slots are hidden from every booking flow. A slot conflicts with a block when `[slot, slot + SLOT_STEP_MINUTES)` overlaps `[block.start, block.end)` — appointments have a duration, so never compare the slot's start instant alone
- Telegram notifications to client and staff (AppointmentNotificationService)
- Scheduled jobs: reminders, pending expiry, auto-completion
- Medical record generation (bot/services/llm/agent.py `ChatLLM`, backed by Mistral via the `mistralai` SDK) — extracts complaints/diseases/examination/treatment/tooth_map from input and renders a docx via bot/services/document_generator/pydocx.py (docxtpl)

Future / not yet implemented (env vars `OLLAMA_BASE_URL` / `OLLAMA_MODEL` are read in bot/config/config.py but nothing in bot/ calls Ollama yet):

- Whisper voice transcription
- Local LLM via Ollama (current LLM integration is Mistral-hosted, not local)
- Subscription system

---

# Commands

Environment: Python venv at `.venv/`; dependencies pinned in `requirements.txt` (no pyproject.toml/lockfile — install with pip).

```
pip install -r requirements.txt          # setup

pytest                                   # run full test suite (72 files in tests/)
pytest tests/test_appointment_management.py            # single file
pytest tests/test_appointment_management.py::test_name -v   # single test
pytest -k "reschedule"                   # by keyword across the suite

ruff check .                             # lint (no committed ruff config -> default rules)

python -m bot.run                        # run the bot (must run as a module from repo root;
                                          # bot/run.py uses absolute `from bot...` imports)
```

Notes:
- `pytest.ini` + `conftest.py` redirect pytest's cache/tmp dirs into `.pytest_tmp/` — don't hand-edit that directory.
- Required runtime env vars (see `.env`, not committed): `BOT_TOKEN_MM`, `BOT_TOKEN_ZB` (two bot tokens — this repo runs more than one Telegram bot instance, one per clinic deployment), `DATA_BASE`, `DATA_BASE_MM` (per-instance SQLite paths), `MISTRAL_API_KEY`.
- Tests use fakes/an in-memory or temp SQLite DB rather than the real `data/` database — see the `sqlite-to-postgres-step` and `repo-test-fakes` skills in `.codex/skills/` before touching repository or migration code. Legacy Claude copies may also exist in `.claude/skills/`, but Codex should prefer `.codex/skills/`.

---

# Project Instructions

Follow the workflow described in this file and in the Codex project skill:

`.codex/skills/codex-project-workflow/SKILL.md`

Legacy Claude workflow notes may also exist in `.claude/agents/workflow.md`;
use them only when maintaining Claude compatibility.

All implementation tasks must use the defined agent responsibilities and workflow.

Codex subagents are defined in `.codex/agents/`. Legacy Claude subagents are
defined in `.claude/agents/`. For Codex work, always dispatch work to the
appropriate `.codex/agents/` subagent rather than doing it inline:

- `.codex/agents/planner.toml` — breaks down the task, defines scope
- `.codex/agents/researcher.toml` — reads existing code, finds reference implementations
- `.codex/agents/implementer.toml` — writes/edits code following the plan
- `.codex/agents/aiogram-expert.toml` — used when Telegram/aiogram logic is affected
- `.codex/agents/database-expert.toml` — used when repositories or database are affected
- `.codex/agents/test-expert.toml` — writes/fixes pytest coverage for the change
- `.codex/agents/routine.toml` — mechanical work: formatting, renames, docs
- `.codex/agents/reviewer.toml` — final check against this file's rules

Never skip researcher before implementer. The researcher subagent is
responsible for finding the closest existing reference implementation
(e.g. a sibling *_creation.py, *_requests.py file) before any code is written.

---

# Skills

Codex project skills live in `.codex/skills/`. Legacy Claude copies live in
`.claude/skills/`. Subagents may not have the Skill tool — in that case read
the matching `.codex/skills/<skill-name>/SKILL.md` directly before writing code.
Mandatory mapping (task → skill):

- New admin/client CRUD or multi-step FSM flow → crud-flow-scaffold
- New scheduled/delayed job (reminder, expiry, follow-up) → background-job-scaffold
- New or changed tests for services/repositories → repo-test-fakes
- Any PostgreSQL migration work → sqlite-to-postgres-step
- Any backend refactor or async I/O work → python-backend-guidelines
- Non-trivial feature start-to-finish → pythonproject3-superpowers (plan → spec → TDD → implement → review)
- Codex workflow/tooling setup → codex-project-workflow or codex-project-tooling

When dispatching implementer or test-expert, include the relevant SKILL.md
path in the subagent prompt.

---

# Architecture

The application follows a layered architecture.

Handler
↓

Service
↓

Repository
↓

Database

Never bypass layers.

Handlers never access repositories directly.

Repositories never call services.

Services orchestrate business logic.

---

## Default Engineering Workflow

For every non-trivial feature:

1. Use planner.
2. Use researcher.
3. Use implementer.
4. Use aiogram-expert when Telegram logic is affected.
5. Use database-expert when repositories or database are affected.
6. Use test-expert to add/adjust pytest coverage for the change.
7. Use routine for mechanical follow-ups (docs, renames, formatting).
8. Always finish with reviewer.

This workflow is mandatory unless explicitly overridden by the user.

# Layer Responsibilities

## Handler

Responsible for:

- Telegram updates
- FSM transitions
- Calling services
- Sending responses

Handlers must NOT:

- Execute SQL
- Normalize data
- Perform business validation
- Contain business rules

---

## Service

Responsible for:

- Business logic
- Validation
- Normalization
- Repository orchestration
- Domain exceptions

Services may call multiple repositories.

Services never know about Telegram objects.

---

## Repository

Responsible only for database access.

Repositories:

- execute SQL
- map rows to models

Repositories must NOT:

- validate
- normalize
- access Telegram
- contain business logic

Return domain models only.

Never return:

- sqlite rows
- tuples
- dictionaries

---

# FSM Rules

FSM helpers exist to eliminate duplicated FSM code.

Helpers may:

- validate input
- update FSM data
- change state

Helpers must NOT:

- call repositories
- contain business logic
- create database models
- build keyboards
- send success messages

Business logic belongs to Services.

---

# Validation Rules

Input validation belongs to validators.

Business validation belongs to Services.

Repositories never validate.

Avoid duplicated validation.

---

# Database Rules

Every SQL query belongs inside Repository.

Never write SQL elsewhere.

Every database entity must have:

- Model
- Repository

---

# Repository Return Types

Repositories should return:

User

Appointment

Clinic

Staff

list[User] / list[Appointment] / list[Staff]

bool

None

Never expose database-specific objects.

---

# Error Handling

Raise domain exceptions.

Never expose:

- sqlite exceptions
- implementation details

Prefer custom exceptions.

Existing examples (bot/exceptions/):

UserNotFoundError

AppointmentNotFoundError

AppointmentAlreadyFinalizedError

NegotiationInProgressError

SlotUnavailableError

ValidationError

Extend these modules; do not create parallel exception hierarchies.

---

# Dependency Injection

Repositories are injected into Services.

Services are injected into Routers.

Avoid global mutable state.

---

# Code Style

Prefer:

Early returns

Small functions

Small modules

Type hints everywhere

Descriptive variable names

Async functions

Avoid:

Deep nesting

Large functions

Premature abstractions

Dynamic magic

Reflection

Inheritance unless necessary

---

# Formatting

Keep functions focused.

Avoid more than one responsibility per function.

Separate logical blocks with a single blank line.

Avoid unnecessary comments.

Code should explain itself.

---

# Naming

Repository:

get_appointment_by_id()

create_appointment()

update_appointment_status()

delete_appointment()

Service:

create_self_booking()

confirm_pending_request()

resolve_notification_recipients()

Handler:

confirm_request()

reject_request()

process_propose_datetime()

Keyboard:

booking_request_kb()

client_creation_kb()

Callback data classes end with CB (BookingRequestActionCB, RescheduleRequestActionCB).

---

# UI Rules

Keyboards only build keyboards.

No business logic.

Confirmation builders only format messages.

No repository access.

---

# Refactoring Rules

When modifying code:

Prefer modifying existing modules.

Do NOT create:

- duplicate validators
- duplicate builders
- duplicate helpers
- duplicate repositories

Search existing implementations first.

---

# AI Workflow

Before writing code:

1. Search the project.
2. Reuse existing code.
3. Read related modules.
4. Check documentation if API usage is uncertain.
5. Write the smallest possible change.

Never duplicate functionality.

---

# Code Generation Rules

Before generating code, verify:

- similar functionality does not already exist
- naming follows project conventions
- architecture remains unchanged
- responsibility stays inside the correct layer

Do not introduce new abstractions unless explicitly requested.

---

# Future Architecture

Already implemented: Clinic, Staff (doctor/admin), Appointment.

Planned entities:

Medical Record

Subscription

AI Assistant

Voice Processing

The architecture should remain compatible with these future additions.

---

# Planned Infrastructure

Future migration targets:

SQLite → PostgreSQL (avoid SQLite-specific SQL; schema migrations live in repository init() via PRAGMA table_info + ALTER TABLE)

Local deployment → VPS

Multi-clinic: schema already supports clinics/staff; keep clinic_id scoping in every new query

Rule-based input → AI-assisted input

Keep new code compatible with future migration whenever reasonable.

---

# AI Tool Usage

When development tools are available:

- Search the project before creating new code.
- Prefer documentation lookup over memory.
- Reuse existing implementations.
- Keep edits minimal and consistent.

Do not assume APIs or project structure without verification.

---

# Review Checklist

Before finishing any task, verify:

✔ No duplicated validation

✔ No duplicated SQL

✔ No duplicated builders

✔ No duplicated helpers

✔ No business logic inside handlers

✔ No SQL outside repositories

✔ No Telegram objects inside services

✔ Architecture remains intact

✔ Existing project style is preserved

✔ Tests pass (pytest)

---

# Golden Rule

When in doubt:

Prefer consistency with the existing project over introducing a "better" architecture.

This project values maintainability, predictability and explicit code more than clever abstractions.
