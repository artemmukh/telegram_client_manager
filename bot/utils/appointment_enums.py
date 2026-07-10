from enum import Enum


class AppointmentStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"
    EXPIRED = "expired"


class CreatedBy(Enum):
    ADMIN = "admin"
    CLIENT = "client"
