"""Per-instance clinic identity, shared by ClinicRepository and StaffRepository.

Each bot instance ("zb" / "mm") now runs against its own dedicated database
(one clinic per DB) instead of one shared multi-clinic database. This module
is the single place that maps an instance name to its clinic's name/token and
its initial staff telegram ids, so the two repositories don't each hardcode
their own copy of the same business data.
"""

from typing import TypedDict


class ClinicSeed(TypedDict):
    name: str
    token: str


CLINIC_SEED_BY_INSTANCE: dict[str, ClinicSeed] = {
    "zb": {"name": "Зуб Мудрости", "token": "x7A92JdPkLmQe81"},
    "mm": {"name": "Мануал Мед", "token": "q5N28JdTkLmXe73"},
}

STAFF_SEED_BY_INSTANCE: dict[str, list[int]] = {
    "zb": [685889801, 226655040, 37470594],
    # 685889801 is also an admin here: now that zb/mm are separate databases
    # (not one shared DB), the same telegram id can be staff in both without
    # the staff.telegram_user_id PK conflict that blocked this before.
    "mm": [1093653116, 685889801],
}


class PriceListContent(TypedDict):
    image_paths: dict[str, list[str]]
    caption: dict[str, str]


class LocationContent(TypedDict):
    image_path: str
    caption: dict[str, str]

class DateParserContent(TypedDict):
    clinic_mode: str

# None means "not set up yet" -- the handler sends a placeholder text message
# instead of trying to load images that don't exist for that clinic.
# image_paths is per-language; clinics without a dedicated Uzbek scan (mm)
# just point "uz" at the same files as "ru".
PRICE_LIST_BY_INSTANCE: dict[str, PriceListContent] = {
    "zb": {
        "image_paths": {
            "ru": ["data/price_list/rus_1pg.png", "data/price_list/rus_2pg.png"],
            "uz": ["data/price_list/uzb_1pg.png", "data/price_list/uzb_2pg.png"],
        },
        "caption": {
            "ru": "Прайс-лист оказываемых услуг.",
            "uz": "Ko'rsatiladigan xizmatlar narxlar ro'yxati.",
        },
    },
    "mm": {
        "image_paths": {
            "ru": ["data/price_list/price_mm.jpg", "data/price_list/schedule_mm.jpg"],
            "uz": ["data/price_list/price_mm.jpg", "data/price_list/schedule_mm.jpg"],
        },
        "caption": {
            "ru": "График и Прайс-лист оказываемых услуг.",
            "uz": "Ko'rsatiladigan xizmatlar jadvali va narxlar ro'yxati.",
        },
    },
}

LOCATION_BY_INSTANCE: dict[str, LocationContent] = {
    "zb": {
        "image_path": "data/location/location.png",
        "caption": {
            "ru": (
                "https://yandex.uz/maps/-/CTBl4J6V\n"
                "ул. Мирзо Улугбека 105/3 (вход со стороны дороги).\n"
                'Ориентир: магазин "Чимган".'
            ),
            "uz": (
                "https://yandex.uz/maps/-/CTBl4J6V\n"
                "Mirzo Ulug'bek ko'chasi 105/3 (yo'l tomonidan kirish).\n"
                "Mo'ljal: \"Chimgan\" do'koni."
            ),
        },
    },
    "mm": {"image_path": "data/location/location_mm.png",
        "caption": {
            "ru": (
                "https://yandex.uz/maps/-/CTfUePor\n"
                "Мануал мед, ул. Шота Руставели, 91"
            ),
            "uz": (
                "https://yandex.uz/maps/-/CTfUePor\n"
                "Manual Med, Shota Rustaveli ko'chasi, 91"
            ),
        },
    }
}

PRICE_LIST_STUB_MESSAGE = {
    "ru": "Прайс-лист скоро появится здесь. Уточняйте у администратора клиники.",
    "uz": "Narxlar ro'yxati tez orada bu yerda paydo bo'ladi. Klinika administratoridan so'rang.",
}
LOCATION_STUB_MESSAGE = {
    "ru": "Адрес клиники скоро появится здесь. Уточняйте у администратора клиники.",
    "uz": "Klinika manzili tez orada bu yerda paydo bo'ladi. Klinika administratoridan so'rang.",
}

DATEPARSER_BY_INSTANCE: dict[str, str] = {
    "zb": "slots",
    "mm": "slots",
}

# None means "not set up yet" -- MedicalRecordService marks the record failed
# with a clear message instead of trying to render a template that doesn't
# exist for that clinic.
MEDICAL_RECORD_TEMPLATE_BY_INSTANCE: dict[str, str | None] = {
    "zb": "data/history_of_illness/medical_card_wisdom_tooth.docx",
    "mm": None,  # ещё не настроено
}

# Seeded staff keep their notification visibility explicit. Existing rows are
# left untouched by StaffRepository so manual per-user configuration survives.
STAFF_VISIBILITY_SCOPE_BY_INSTANCE: dict[str, dict[int, str]] = {
    "zb": {
        685889801: "clinic",
        226655040: "own",
        37470594: "own",
    },
    "mm": {
        1093653116: "own",
        685889801: "clinic",
    },
}
