"""Unit coverage for bot/services/utils/escape_html.py.

escape_html wraps html.escape(value, quote=False) -- quote=False is the
load-bearing choice this batch introduces: Telegram HTML parse_mode only
requires escaping <, >, & (quote=True would also turn apostrophes into
&#x27;, which would visibly mangle the uz locale's apostrophe-heavy text,
e.g. "Ta'mirlash", "yo'q"). These tests pin that specific behaviour so a
future "helpful" switch to html.escape's default quote=True is caught.
"""
from bot.services.utils.escape_html import escape_html


def test_escape_html_escapes_less_than():
    assert escape_html("a < b") == "a &lt; b"


def test_escape_html_escapes_greater_than():
    assert escape_html("a > b") == "a &gt; b"


def test_escape_html_escapes_ampersand():
    assert escape_html("Tom & Jerry") == "Tom &amp; Jerry"


def test_escape_html_escapes_all_three_special_characters_together():
    assert escape_html('<кабинет> & "покраска"') == '&lt;кабинет&gt; &amp; "покраска"'


def test_escape_html_leaves_apostrophe_unchanged():
    """Pins quote=False: html.escape's default (quote=True) would turn this
    into "Ta&#x27;mirlash", which is wrong for the uz locale."""
    assert escape_html("Ta'mirlash") == "Ta'mirlash"


def test_escape_html_leaves_double_quote_unchanged():
    """Pins quote=False: the default quote=True would turn this into
    "&quot;покраска&quot;"."""
    assert escape_html('"покраска"') == '"покраска"'


def test_escape_html_leaves_plain_text_unchanged():
    assert escape_html("Отпуск врача") == "Отпуск врача"


def test_escape_html_would_differ_under_quote_true_for_apostrophe():
    """Empirical guard, not a tautology: proves the apostrophe assertion above
    is actually meaningful by showing html.escape's default quote=True DOES
    mangle it -- if escape_html ever regresses to quote=True, the two values
    below would become equal and this test documents why that matters."""
    import html

    assert html.escape("Ta'mirlash", quote=True) != "Ta'mirlash"
    assert escape_html("Ta'mirlash") == "Ta'mirlash"
