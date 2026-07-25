import asyncio
import io
import logging
import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.shared import Pt
from docxtpl import DocxTemplate

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "data" / "history_of_illness" / "medical_card_wisdom_tooth.docx"
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "history_of_illness" / "generated"

TEETH_TABLE_INDEX = 1

TOOTH_MARKERS = {
    "кариес": "C",
    "пульпит": "P",
    "периодонтит": "Pt",
    "ретинирован": "X",
    "дистопирован": "X",
    "удаление": "X",
}

TOOTH_MAP = {
    18: (2, 0), 17: (2, 1), 16: (2, 2), 15: (2, 3),
    14: (2, 4), 13: (2, 5), 12: (2, 6), 11: (2, 7),
    21: (2, 8), 22: (2, 9), 23: (2, 10), 24: (2, 11),
    25: (2, 12), 26: (2, 13), 27: (2, 14), 28: (2, 15),

    48: (3, 0), 47: (3, 1), 46: (3, 2), 45: (3, 3),
    44: (3, 4), 43: (3, 5), 42: (3, 6), 41: (3, 7),
    31: (3, 8), 32: (3, 9), 33: (3, 10), 34: (3, 11),
    35: (3, 12), 36: (3, 13), 37: (3, 14), 38: (3, 15),
}


def find_tooth(text: str) -> int | None:
    match = re.search(r"\b([1-4][1-8])\b", text)
    if match:
        return int(match.group(1))
    return None


def find_marker(text: str) -> str:
    text = text.lower()

    for key, value in TOOTH_MARKERS.items():
        if key in text:
            return value

    return ""


def mark_tooth(table, tooth: int, marker: str) -> None:
    if tooth not in TOOTH_MAP:
        return

    row, col = TOOTH_MAP[tooth]

    cell = table.cell(row, col)
    cell.text = ""
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    paragraph = cell.paragraphs[0]
    paragraph.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

    run = paragraph.add_run(marker)
    run.bold = True
    run.font.size = Pt(12)


def _render_docx_sync(data: dict, raw_diagnosis: str, output_path: Path) -> None:
    template = DocxTemplate(str(TEMPLATE_PATH))
    template.render(data)

    buffer = io.BytesIO()
    template.save(buffer)
    buffer.seek(0)

    doc = Document(buffer)

    tooth = find_tooth(raw_diagnosis)
    marker = find_marker(raw_diagnosis)

    try:
        teeth_table = doc.tables[TEETH_TABLE_INDEX]
    except IndexError:
        logger.warning("Шаблон не содержит таблицу зубной карты (индекс %s), пропускаю отметку зуба.", TEETH_TABLE_INDEX)
    else:
        if tooth and marker:
            mark_tooth(teeth_table, tooth, marker)

    logger.info("Причинный зуб: %s", tooth)
    logger.info("Маркер: %s", marker)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))

    logger.info("Документ сохранён: %s", output_path)


async def create_docx(data: dict, raw_diagnosis: str, appointment_id: int) -> str:
    """Render the medical record template and mark the affected tooth.

    `data` must already contain every template placeholder (appointment_date,
    full_name, gender, birth_date, phone, diagnosis, complaints, diseases,
    examination, treatment) with LLM-key-to-template-key mapping already
    applied by the caller. `raw_diagnosis` is the original short
    appointment.purpose string (not the LLM-generated diagnosis text), used
    only for the tooth-map regex/keyword search. Returns the path to the
    generated .docx file.
    """
    output_path = OUTPUT_DIR / f"medical_card_{appointment_id}.docx"

    await asyncio.to_thread(_render_docx_sync, data, raw_diagnosis, output_path)

    return str(output_path)
