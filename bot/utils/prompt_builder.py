from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SYSTEM_PROMPT_PATH = PROJECT_ROOT / "data" / "history_of_illness" / "templates" / "docx_gen_prompt.txt"
UNFILLED_TEMPLATE_PATH = PROJECT_ROOT / "data" / "history_of_illness" / "templates" / "zub_mudsrosti_med_card_unfilled.md"
FILLED_EXAMPLE_PATH = PROJECT_ROOT / "data" / "history_of_illness" / "templates" / "zub_mudsrosti_med_card_filled.md"
REFERENCE_PDF_PATH = PROJECT_ROOT / "data" / "history_of_illness" / "medical_card_filled.pdf"


@lru_cache(maxsize=1)
def get_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf8")


@lru_cache(maxsize=1)
def get_unfilled_template() -> str:
    return UNFILLED_TEMPLATE_PATH.read_text(encoding="utf8")


@lru_cache(maxsize=1)
def get_filled_example() -> str:
    return FILLED_EXAMPLE_PATH.read_text(encoding="utf8")


def get_reference_pdf_path() -> Path:
    return REFERENCE_PDF_PATH


def build_user_prompt(patient_summary: str, diagnosis: str) -> str:
    return (
        "Пациент:\n"
        + patient_summary
        + "\n\nДиагноз:\n"
        + diagnosis
        + "\n\nШаблон (незаполненный):\n"
        + get_unfilled_template()
        + "\n\nПример заполненного шаблона:\n"
        + get_filled_example()
    )
