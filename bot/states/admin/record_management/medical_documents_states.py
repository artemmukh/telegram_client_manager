from aiogram.fsm.state import State, StatesGroup


class MedicalDocumentStates(StatesGroup):
    """Transient input state for a new document's temporary diagnosis."""

    diagnosis = State()
