"""Tests for bot.services.document_generator.pydocx's tooth-map marking.

mark_teeth must degrade gracefully on malformed entries (missing keys, wrong
types, non-dict entries) instead of raising, so a bad LLM response never
crashes document generation.
"""

from bot.services.document_generator.pydocx import TOOTH_MAP, mark_teeth


class FakeCell:
    def __init__(self):
        self.text = ""
        self.vertical_alignment = None
        self.paragraphs = [FakeParagraph()]


class FakeParagraph:
    def __init__(self):
        self.alignment = None
        self.runs = []

    def add_run(self, text):
        run = FakeRun(text)
        self.runs.append(run)
        return run


class FakeRun:
    def __init__(self, text):
        self.text = text
        self.bold = False
        self.font = FakeFont()


class FakeFont:
    def __init__(self):
        self.size = None


class FakeTable:
    def __init__(self):
        self.cells: dict[tuple[int, int], FakeCell] = {}

    def cell(self, row, col):
        key = (row, col)
        if key not in self.cells:
            self.cells[key] = FakeCell()
        return self.cells[key]


def test_mark_teeth_marks_multiple_cells_correctly():
    table = FakeTable()

    mark_teeth(table, [{"tooth": 37, "marker": "C"}, {"tooth": 21, "marker": "P"}])

    row_37, col_37 = TOOTH_MAP[37]
    row_21, col_21 = TOOTH_MAP[21]
    assert table.cells[(row_37, col_37)].paragraphs[0].runs[0].text == "C"
    assert table.cells[(row_21, col_21)].paragraphs[0].runs[0].text == "P"


def test_mark_teeth_skips_unknown_tooth_number():
    table = FakeTable()

    mark_teeth(table, [{"tooth": 99, "marker": "C"}])

    assert table.cells == {}


def test_mark_teeth_with_empty_list_marks_nothing():
    table = FakeTable()

    mark_teeth(table, [])

    assert table.cells == {}


def test_mark_teeth_skips_malformed_entry_missing_tooth_key(caplog):
    table = FakeTable()

    with caplog.at_level("WARNING"):
        mark_teeth(table, [{"marker": "C"}])

    assert table.cells == {}
    assert "tooth_map" in caplog.text


def test_mark_teeth_skips_malformed_entry_missing_marker_key(caplog):
    table = FakeTable()

    with caplog.at_level("WARNING"):
        mark_teeth(table, [{"tooth": 37}])

    assert table.cells == {}
    assert "tooth_map" in caplog.text


def test_mark_teeth_skips_malformed_entry_wrong_type(caplog):
    table = FakeTable()

    with caplog.at_level("WARNING"):
        mark_teeth(table, [{"tooth": "37", "marker": "C"}])

    assert table.cells == {}
    assert "tooth_map" in caplog.text


def test_mark_teeth_skips_non_dict_entry(caplog):
    table = FakeTable()

    with caplog.at_level("WARNING"):
        mark_teeth(table, ["not a dict"])

    assert table.cells == {}
    assert "tooth_map" in caplog.text


def test_mark_teeth_with_none_marks_nothing(caplog):
    table = FakeTable()

    with caplog.at_level("WARNING"):
        mark_teeth(table, None)

    assert table.cells == {}
    assert "tooth_map" in caplog.text


def test_mark_teeth_with_dict_instead_of_list_marks_nothing(caplog):
    table = FakeTable()

    with caplog.at_level("WARNING"):
        mark_teeth(table, {"tooth": 37, "marker": "C"})

    assert table.cells == {}
    assert "tooth_map" in caplog.text


def test_mark_teeth_continues_after_a_malformed_entry():
    table = FakeTable()

    mark_teeth(table, [{"tooth": "bad"}, {"tooth": 37, "marker": "C"}])

    row, col = TOOTH_MAP[37]
    assert table.cells[(row, col)].paragraphs[0].runs[0].text == "C"
