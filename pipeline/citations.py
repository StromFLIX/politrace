"""Lossless source anchoring: restore whitespace only, never words, punctuation or conditions."""
import re


def source_quote(quote: str | None, source: str) -> str:
    """Return the exact source span, or fail. No fuzzy matching or model-based repair.

    A model may turn a PDF line break into a space. Collapse whitespace runs in both strings,
    retaining character offsets into the source. Accept only one unambiguous match, then return
    the original source substring. Word boundaries, spelling, numbers, punctuation and Markdown
    must remain identical. Every stored quote is still a literal substring of its cited source.
    """
    normalized = re.sub(r'\s+', ' ', quote or '').strip()
    if len(normalized) < 10:
        raise ValueError('A source quotation needs at least ten meaningful characters')
    if quote in source:
        return quote
    characters, starts, ends = [], [], []
    for match in re.finditer(r'\s+|\S', source):
        characters.append(' ' if match.group().isspace() else match.group())
        starts.append(match.start())
        ends.append(match.end())
    text = ''.join(characters)
    start = text.find(normalized)
    if start < 0 or text.find(normalized, start + 1) >= 0:
        raise ValueError('Quotation is absent or ambiguous after whitespace-only source anchoring')
    exact = source[starts[start]:ends[start + len(normalized) - 1]]
    if len(exact) < 10:
        raise ValueError('Restored source quotation is too short')
    return exact
