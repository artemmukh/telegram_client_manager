from datetime import datetime
import re

from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docxtpl import DocxTemplate
from docx import Document
from docx.shared import Pt
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT


INPUT_FILE = "docs/medical_card_wisdom_tooth.docx"
TEMP_FILE = "docs/_temp.docx"
OUTPUT_FILE = "docs/medical_card_filled.docx"


# ==========================================================
# ДАННЫЕ
# ==========================================================

fio = "Иванов Иван Иванович"
gender = "М"
birth_date = "14.02.2005"
phone = "+998901234567"

visit_date = datetime.now().strftime("%d.%m.%Y")

diagnosis = """
Средний кариес 37 зуба.
""".strip()

complaints = """
Жалобы на кратковременную боль при приёме сладкой и холодной пищи, застревание пищи в области 37 зуба.
""".strip()

diseases = """
Со слов пациента хронические заболевания и аллергические реакции отрицает.
""".strip()

examination = """
На жевательной поверхности 37 зуба определяется кариозная полость средней глубины с размягчённым пигментированным дентином. Зондирование дна и стенок умеренно болезненно. Перкуссия безболезненна. Слизистая оболочка без патологических изменений.
""".strip()

treatment = """
Под инфильтрационной анестезией проведена механическая и медикаментозная обработка кариозной полости 37 зуба. Выполнено восстановление композитным пломбировочным материалом, проведена финишная обработка и полировка реставрации. Даны рекомендации по гигиене полости рта.
""".strip()


# ==========================================================
# ПОИСК ЗУБА
# ==========================================================

def find_tooth(text: str):
    m = re.search(r"\b([1-4][1-8])\b", text)
    if m:
        return int(m.group(1))
    return None


# ==========================================================
# ОБОЗНАЧЕНИЕ
# ==========================================================

MARKERS = {
    "кариес": "C",
    "пульпит": "P",
    "периодонтит": "Pt",
    "ретинирован": "X",
    "дистопирован": "X",
    "удаление": "X",
}


def find_marker(text):
    text = text.lower()

    for key, value in MARKERS.items():
        if key in text:
            return value

    return ""


# ==========================================================
# КАРТА ЗУБОВ
# ==========================================================

TOOTH_MAP = {
    18:(2,0),17:(2,1),16:(2,2),15:(2,3),
    14:(2,4),13:(2,5),12:(2,6),11:(2,7),
    21:(2,8),22:(2,9),23:(2,10),24:(2,11),
    25:(2,12),26:(2,13),27:(2,14),28:(2,15),

    48:(3,0),47:(3,1),46:(3,2),45:(3,3),
    44:(3,4),43:(3,5),42:(3,6),41:(3,7),
    31:(3,8),32:(3,9),33:(3,10),34:(3,11),
    35:(3,12),36:(3,13),37:(3,14),38:(3,15),
}


def mark_tooth(table, tooth, marker):

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

# ==========================================================
# DOCXTPL
# ==========================================================

doc = DocxTemplate(INPUT_FILE)

context = {
    "appointment_date": visit_date,
    "full_name": fio,
    "gender": gender,
    "birth_date": birth_date,
    "phone": phone,
    "diagnosis": diagnosis,
    "complaints": complaints,
    "diseases": diseases,
    "examination": examination,
    "treatment": treatment,
}

doc.render(context)
doc.save(TEMP_FILE)


# ==========================================================
# ОТМЕТКА ЗУБА
# ==========================================================

doc = Document(TEMP_FILE)

teeth_table = doc.tables[1]

tooth = find_tooth(diagnosis)
marker = find_marker(diagnosis)

if tooth and marker:
    mark_tooth(teeth_table, tooth, marker)

doc.save(OUTPUT_FILE)

print("Причинный зуб:", tooth)
print("Маркер:", marker)
print("Документ сохранён:", OUTPUT_FILE)