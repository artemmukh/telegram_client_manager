# Medical Appointment Telegram Bot

Telegram bot for managing patients and appointments. The project is designed for small clinics and private practices where administrators need a simple way to manage patient records and appointment schedules directly from Telegram.

## Features

### Administrator

Administrators can manage the entire patient database:

* Create patient records
* View patient information
* Update patient information
* Delete patient records

The bot also provides full appointment management:

* Create appointments
* View upcoming appointments
* Update appointment details
* Cancel appointments

In other words, administrators have full CRUD functionality for both patients and appointments.

### Patient

Patients can register through the bot and link their Telegram account to an existing patient profile.

After registration, patients can:

* View their upcoming appointments
* Receive appointment reminders
* Access appointment information directly from Telegram

## Planned AI Features

Artificial Intelligence integration is planned for future releases.

Potential features include:

* Voice message processing using Whisper
* Natural language appointment creation
* AI-powered patient interaction
* Automated data extraction from messages
* Local LLM integration through Ollama

Example:

Patient sends a voice message:

> Schedule me for a consultation next Tuesday at 15:00.

The AI system automatically extracts:

* Patient name
* Appointment date
* Appointment time
* Service type

and creates the appointment without manual input.

## Technology Stack

### Current

* Python
* Aiogram
* SQLite
* Asyncio

### Future

* Whisper
* Ollama
* Local LLM Models
* PostgreSQL (if scalability becomes necessary)

## Project Structure

```text
project/
│
├── bot/
│   ├── handlers/
│   ├── keyboards/
│   ├── states/
│   └── middlewares/
│
├── database/
│   ├── models/
│   └── repositories/
│
├── services/
│
├── config/
│
└── main.py
```
