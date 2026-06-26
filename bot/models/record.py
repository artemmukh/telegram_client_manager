
class Record:
    def __init__(self, ID: int, user_telegram_id: int, date: str, status: str, description: str):
        self.ID = ID
        self.user_telegram_id = user_telegram_id
        self.date = date
        self.status = status
        self.description = description