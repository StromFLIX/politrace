"""Conservative interpretation of chair-announced decisions in structured transcripts."""
from __future__ import annotations

import re

from pipeline.models import GroupVote
from pipeline.parliament import document_numbers

STAGES = {'final_passage': 'Schlussabstimmung', 'second_reading': 'Zweite Beratung',
          'resolution': 'Entschließung', 'amendment': 'Änderungsantrag',
          'procedural': 'Verfahrensentscheidung', 'unknown': 'Parlamentarischer Beschluss'}


def decision_stage(position: dict, decision: dict) -> str:
    tenor = decision.get('beschlusstenor', '').lower()
    if 'entschließung' in tenor:
        return 'resolution'
    if 'änderungsantrag' in tenor or 'änderungsanträge' in tenor:
        return 'amendment'
    if not tenor.startswith(('annahme', 'ablehnung')):
        return 'procedural'
    reading = position.get('vorgangsposition', '')
    if '3.' in reading or 'Schlussabstimmung' in reading:
        return 'final_passage'
    if '2.' in reading:
        return 'second_reading'
    return 'unknown'


def decision_scope(decision: dict) -> str:
    # DIP sometimes puts the partial-law target only in the result remark.
    text = decision.get('beschlusstenor', '') + ' ' + decision.get('abstimm_ergebnis_bemerkung', '')
    return 'partial_law' if re.search(
        r'\b(?:Artikel|Art\.|Einzelpl(?:an|äne)|Buchstabe|Ziffer|Nummer|übrig\w*|Teile)\b', text, re.I
    ) else 'whole_law'


def law_decisions(positions, published):
    result = []
    for position in positions:
        if (position.get('zuordnung') != 'BT' or position.get('dokumentart') != 'Plenarprotokoll'
                or position.get('vorgangstyp') != 'Gesetzgebung' or position['datum'] > str(published)):
            continue
        for index, decision in enumerate(position.get('beschlussfassung', [])):
            stage = decision_stage(position, decision)
            if stage not in ('final_passage', 'second_reading'):
                continue  # Resolutions/amendments are not votes on this law as a whole.
            if re.search(r'\b(Artikel|Einzel|Buchstabe|Ziffer|Nummer)\b', decision.get('beschlusstenor', '')):
                continue
            result.append((position, index, decision, stage))
    return result


def flattened(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Normalize XML whitespace for matching, retaining exact source offsets for quotes."""
    chars, spans = [], []
    tokens = r'(?P<soft>\xad)|(?P<space>\s+)|(?P<char>.)'
    for match in re.finditer(tokens, text, re.S):
        if match.lastgroup == 'soft':
            continue
        chars.append(' ' if match.lastgroup == 'space' else match[0])
        spans.append(match.span())
    return ''.join(chars), spans


LAW_WORD = r'(?:Gesetz(?:es)?entwurf(?:es|s)?|Gesetz|Vorlage)'
FINAL = r'\b(?:(?:[Dd]ritte[nr]?|[Zz]weite[nr]?) Beratung und )?Schlussabstimmung\b'
END = re.compile(LAW_WORD + r'\b[^.?!]{0,650}?\b(?:angenommen|abgelehnt)\b[^.?!]{0,650}\.'
                 + r'|Annahme des ' + LAW_WORD + r'\b[^.?!]{0,350}\.')
QUESTIONS = re.compile(
    r'(?:Ich bitte(?: jetzt| nun)?[,]? diejenigen|Jetzt bitte ich diejenigen|'
    r'Nun mögen sich diejenigen|Und diejenigen sollen sich)[^.?!]{0,350}?(?:Handzeichen|erheben)[.;]'
    r'|(?:Ich darf fragen: )?Wer (?:stimmt|ist|möchte) [^?!]{1,200}\?'
    r'|Wer (?:dagegenstimmen|zustimmen) (?:möchte|will), möge sich (?:bitte )?erheben[.;]'
    r'|(?:Und )?(?:nun|jetzt) erheben sich bitte die, die (?:dagegenstimmen|zustimmen) wollen[.;]'
    r'|(?:Nun|Jetzt) diejenigen, die sich enthalten[.;]'
    r'|(?:Gibt es )?(?:Gegenstimmen|Neinstimmen|Stimmenthaltungen|Enthaltung(?:en)?)\?'
    r'|Gegenprobe[!.?]'
    r'|(?:Ich darf fragen: )?(?:Wer|Möchte)\b[^.?!]{0,110}(?:enthalten|enthält sich)\?', re.I)


def prompt_position(prompt: str) -> str | None:
    if re.search(r'enthalt|enthält', prompt, re.I):
        return 'abstain'
    if re.search(r'dagegen|gegen\b|Gegenstimmen|Neinstimmen|Gegenprobe', prompt, re.I):
        return 'no'
    if re.search(r'zustimmen|dafür|für\b|\bzu\?', prompt, re.I):
        return 'yes'
    return None


def motion_references(context: str) -> set[str]:
    # A shared agenda/report may list several different bills. Use the last actual
    # recommendation, not every Drucksache in the agenda headings above it.
    recommendations = list(re.finditer(r'\bempfiehlt\b', context))
    if recommendations:
        boundary = context.rfind('. ', 0, recommendations[-1].start())
        context = context[boundary + 2:] if boundary >= 0 else context
    return document_numbers(context)


def without_comments(text: str, spans) -> str:
    chars = list(text)
    for start, end in spans:
        if not 0 <= start <= end <= len(text):
            raise ValueError('Invalid XML commentary range')
        chars[start:end] = ' ' * (end - start)
    return ''.join(chars)


def decision_passage(text: str, numbers: set[str], stage: str, comment_spans=()):
    """Separate readings at their result, require every reference, fail closed on ambiguity.

    Final votes can reuse the *identity* of the immediately preceding second reading,
    never its positions. Quotes start at the actual voting invitation, after amendments.
    """
    if not numbers:
        return None
    flat, spans = flattened(without_comments(text, comment_spans))
    candidates = []
    previous_end, previous_stage, previous_refs = 0, None, set()
    previous_partial = False
    for result in END.finditer(flat):
        start = max(previous_end, result.start() - 40000)
        block = flat[start:result.end()]
        prompts = [q for q in QUESTIONS.finditer(block[:result.start() - start])
                   if prompt_position(q[0]) == 'yes' and not re.search(
                       r'Änderungsantrag|Entschließungsantrag|Artikel\s+\w|übrigen|Teile', q[0], re.I)]
        finals = [m for m in re.finditer(FINAL, block)
                  if prompts and m.end() <= prompts[-1].start()
                  and not re.match(r'\s+des\b', block[m.end():])]
        # A pending named final vote on another bill can precede this reading in
        # the same chair block. The explicit result stage takes precedence over
        # that earlier marker; it must not swallow the following final decision.
        explicit_second = re.search(r'zweite[nr]? (?:Beratung|Lesung)', result[0])
        if explicit_second:
            finals = []
        current_stage = ('second_reading' if explicit_second else 'final_passage' if finals else
                         'second_reading' if prompts and 'Handzeichen' in prompts[-1][0] and (
                             re.search(r'Zweite und dritte Beratung', block) or re.match(
                                 r'\s*(?:Wir kommen(?: nun)? zur\s+)?' + FINAL, flat[result.end():])) else None)
        vote_start = finals[-1].start() if finals else (prompts[-1].start() if prompts else None)
        # A counted division can announce its result without repeating the invitation.
        refs = motion_references(block[:prompts[-1].end() if prompts else result.start() - start])
        if (not refs and previous_partial and re.fullmatch(
                r'\s*Alle Teile des Gesetzentwurfs sind(?: damit)? in zweiter Beratung angenommen\.', block)):
            # This intervening summary carries only the bill identity from the
            # immediately preceding partial decision, never its voting positions.
            refs = previous_refs
        # No reference inheritance past another motion/agenda item or an unknown result.
        if (finals and not refs and previous_stage == 'second_reading'
                and not re.search(r'Tagesordnungspunkt|Zusatzpunkt|Antrag|Gesetzentwurf', block[:vote_start])):
            refs = previous_refs
        if current_stage == stage and vote_start is not None and numbers <= refs:
            quote = block[vote_start:]
            if not re.search(r'Änderungsantrag|Entschließungsantrag|namentliche Abstimmung', quote, re.I):
                a, b = spans[start + vote_start][0], spans[result.end() - 1][1]
                candidates.append((text[a:b], a, b))
        previous_partial = bool(re.search(r'\bübrigen Teile des\s+$', block[:result.start() - start]))
        previous_end, previous_stage, previous_refs = result.end(), current_stage, refs
    return candidates[0] if len(candidates) == 1 else None


def decision_quote(text: str, numbers: set[str], stage: str) -> str | None:
    passage = decision_passage(text, numbers, stage)
    return passage[0] if passage else None


GROUP_PATTERNS = {
    # These are explicit parliamentary names, not an inferred government coalition.
    'CDU/CSU': ('cdu-csu', r'CDU\s*/\s*CSU|\bUnionsfraktion\b|\bUnion\b'),
    'SPD': ('spd', r'\bSPD(?=\b|Fraktion)|\bSozialdemokratie\b'),
    'AfD': ('afd', r'\bAfD(?=\b|Fraktion)'), 'FDP': ('fdp', r'\bFDP(?=\b|Fraktion)'),
    'BÜNDNIS 90/DIE GRÜNEN': ('gruene', r'Bündnis\s*90\s*/\s*(?:Die\s*)?Grünen|\bGrünen?(?:fraktion)?\b'),
    'Die Linke': ('linke', r'\b(?:Die\s+)?Linke[n]?\b|\b(?:Links|Linken)fraktion\b'),
    'BSW': ('bsw', r'\bBSW\b'), 'SSW': ('ssw', r'\bSSW\b'),
}
QUALIFIED = re.compile(r'einzel|einige|teil|mehrheit|Abgeordnet|Ausnahme|bis auf|Stimme[n]? aus|\d+ Gegen', re.I)


def explicit_groups(fragment: str, position: str | None = None) -> list[tuple[str, str]]:
    flat, _ = flattened(fragment)
    for prefix, direction in [(r'^Es stimmen dafür ', 'yes'), (r'^Es enthält sich ', 'abstain'),
                              (r'^Dagegen stimmen ', 'no')]:
        if re.search(prefix, flat, re.I):
            if position and position != direction:
                return []
            flat = re.sub(prefix, '', flat, flags=re.I)
    if QUALIFIED.search(flat):
        return []
    result = []
    for group, (party, pattern) in GROUP_PATTERNS.items():
        if re.search(pattern, flat, re.I):
            result.append((group, party))
            flat = re.sub(pattern, '', flat, flags=re.I)
    flat = re.sub(r'\b(?:Das|sind|ist|die|der|den|des|dem|Fraktionen|Fraktion|Gruppe|Gruppen|'
                  r'und|sowie|auch|mit|von|durch|Stimmen|Ich|sehe|stehend|Ebenfalls|wieder|Zustimmung|bei|Dagegen|stimmen)\b',
                  '', flat, flags=re.I)
    if re.search(r'\w', flat):
        return []  # Unknown qualifications, "all others", applause and coalitions stay unknown.
    return result


def group_positions(quote: str, comment_spans=()) -> list[GroupVote]:
    flat, _ = flattened(without_comments(quote, comment_spans))
    if len(list(END.finditer(flat))) != 1:
        return []  # Never combine the positions of successive decisions.
    parts = []
    questions = list(QUESTIONS.finditer(flat))
    for i, question in enumerate(questions):
        position = prompt_position(question[0])
        if position is None:
            continue
        end = questions[i + 1].start() if i + 1 < len(questions) else len(flat)
        answer = flat[question.end():end].strip(' \n\r\t–—-')
        answer = re.split(r'\b(?:(?:Der|Das|Dieser) ' + LAW_WORD + r'|Damit|Somit|Dann)\b', answer)[0].strip()
        parts.append((position, answer))
    # Presidents often ask all three questions, THEN state the named result in one sentence.
    result = END.search(flat)[0]
    # Stage directions are not positions. Keep all substantive qualifiers intact.
    result = re.sub(r'\((?:Beifall|Heiterkeit)[^()]*\)', '', result)
    outcome = re.search(r'\b(angenommen|abgelehnt)\b', result)
    affirmative = outcome is None or outcome[1] == 'angenommen'
    clauses = list(re.finditer(
        r'\bmit (?:den )?Stimmen|\bgegen (?:die )?(?:Stimmen|die)'
        r'|\b(?:bei|und(?: bei)?) (?:der )?(?:Zustimmung|Ablehnung|Gegenstimmen|Enthaltung(?:en)?)', result))
    for i, clause in enumerate(clauses):
        label = clause[0]
        end = clauses[i + 1].start() if i + 1 < len(clauses) else len(result)
        fragment = result[clause.end():end]
        fragment = re.split(r'\b(?:angenommen|abgelehnt)\b', fragment)[0].strip()
        if 'Enthaltung' in label:
            direction = 'abstain'
        elif 'Zustimmung' in label:
            direction = 'yes'
        elif 'Ablehnung' in label or 'Gegenstimmen' in label:
            direction = 'no'
        elif label.startswith('gegen'):
            direction = 'no' if affirmative else 'yes'
        else:
            direction = 'yes' if affirmative else 'no'
        parts.append((direction, fragment))
    positions, qualified = {}, set()
    for position, fragment in parts:
        # Unambiguous chair instructions do not qualify the named faction answer.
        # Do not remove political commentary, unnamed coalitions or dissenters.
        fragment = re.sub(r'(?:Auch )?Sie dürfen sich (?:wieder )?setzen\.|'
                          r'(?:Ich sage )?[Hh]erzlichen Dank\.|[Vv]ielen Dank\.', '', fragment)
        if QUALIFIED.search(fragment):
            qualified.update(g for g, (_, pattern) in GROUP_PATTERNS.items() if re.search(pattern, fragment, re.I))
        for group, party in explicit_groups(fragment, position):
            if group in positions and positions[group].position != position:
                return []
            positions[group] = GroupVote(group=group, party_id=party, position=position, evidence_quote=quote)
    # A named dissenter in another answer prevents a whole-faction assertion for that party.
    return [value for group, value in positions.items() if group not in qualified]
