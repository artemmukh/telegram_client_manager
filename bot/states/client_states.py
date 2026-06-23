from aiogram.fsm.state import StatesGroup, State

class ClientStates(StatesGroup):
    client_name = State()
    client_phone = State()