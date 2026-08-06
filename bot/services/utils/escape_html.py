import html


def escape_html(value: str) -> str:
    """Escape a value for interpolation into an HTML-parse-mode Telegram message.

    Telegram HTML only requires escaping <, >, &. quote=False is deliberate:
    quote=True would also escape apostrophes into &#x27;, and the uz locale
    uses apostrophes heavily (Ta'mirlash, yo'q).

    Deduplicates what used to be several inline `html.escape(value, quote=False)`
    call sites; this is consolidation of existing logic, not a new abstraction.
    """
    return html.escape(value, quote=False)
