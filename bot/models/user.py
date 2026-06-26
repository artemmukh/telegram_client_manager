

class User:
    def __init__(self, ID: int, telegram_user_id: int, full_name: str, phone: int, role: str, is_registered: bool, records: list):
        self.ID = ID
        self.telegram_user_id = telegram_user_id
        self.full_name = full_name
        self.phone = phone
        self.role = role
        self.is_registered = is_registered
        self.records = []
