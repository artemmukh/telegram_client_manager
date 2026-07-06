from enum import Enum


class AppointmentStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class CreatedBy(Enum):
    ADMIN = "admin"
    CLIENT = "client"
