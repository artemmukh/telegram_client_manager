# 🏥 Medical Appointment Telegram Bot

A modern Telegram bot for managing **patients** and **medical appointments**.

Designed for **private clinics**, **medical offices**, and **small healthcare businesses**, allowing administrators to manage patients and schedules directly from Telegram while giving patients convenient access to their appointments.

---

# ✨ Features

## 👨‍⚕️ Administrator

Complete patient management:

- ➕ Create patients
- 🔍 Search patients
- ✏️ Edit patient information
- 🗑️ Delete patients

Appointment management:

- 📅 Create appointments
- 👀 View appointments
- ✏️ Edit appointments
- ❌ Cancel appointments

The administrator has full **CRUD** functionality for both patients and appointments.

---

## 👤 Patient

Patients can register through Telegram and link their account to an existing patient profile.

Available features:

- 📅 View upcoming appointments
- 🔔 Receive appointment reminders
- 📖 Access appointment information anytime

---

# 🤖 AI Roadmap

The project is being built with future AI integration in mind.

Planned features include:

- 🎙️ Voice message recognition (Whisper)
- 💬 Natural language appointment creation
- 🤖 AI-powered assistant
- 🧠 Automatic information extraction
- 🖥️ Local LLM support via Ollama

### Example

Patient sends:

> *"Schedule me for a consultation next Tuesday at 15:00."*

The AI automatically extracts:

- 👤 Patient
- 📅 Date
- ⏰ Time
- 🩺 Service

and creates the appointment without manual administrator input.

---

# 🛠️ Technology Stack

## Current

- 🐍 Python 3.13+
- ⚡ Aiogram 3
- 🗄️ SQLite
- 🔄 Asyncio

## Planned

- 🎙️ Whisper
- 🧠 Ollama
- 🤖 Local LLMs
- 🐘 PostgreSQL (for larger deployments)

---

# 🏗️ Architecture

The project follows a layered architecture:

```
Router
    ↓
Service
    ↓
Repository
    ↓
SQLite
```

Additional layers:

- ✅ Validators
- 📦 FSM States
- ⌨️ Keyboards
- 🧩 Helpers
- 🔐 Filters
- ⚙️ Middlewares

This separation keeps business logic independent from Telegram-specific code.

---

# 📂 Project Structure

```text
bot/
│
├── config/
├── handlers/
├── keyboards/
├── middlewares/
├── repositories/
├── services/
├── states/
├── validators/
├── utils/
└── run.py
```

---

# 🚀 Getting Started

Clone the repository:

```bash
git clone https://github.com/your_username/your_repository.git
cd your_repository
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it:

**Windows**

```bash
.venv\Scripts\activate
```

**Linux / macOS**

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```env
BOT_TOKEN=your_bot_token
DATA_BASE=data/data_base.db
```

Run the bot:

```bash
python -m bot.run
```

---

# 📌 Project Status

🚧 **Active development**

Current focus:

- ✅ Patient CRUD
- 🚧 Appointment management
- 🚧 Registration flow
- ⏳ Reminder system
- ⏳ AI integration

---

# 📄 License

This project is intended for educational purposes and portfolio demonstration.