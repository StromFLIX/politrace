"""Explicit, reversible reading corrections; no edits to original evidence or source text."""
from collections import Counter

from pipeline.reading import ReadingCorrection, ReadingEdition, validate_reading
from pipeline.store import ROOT, digest, load_records, write_json


def main():
    root = ROOT / 'data'
    records = {r.id: r for kind in ('programs', 'laws') for r in load_records(root, 'live', kind)}
    corrected = warned = 0
    for path in sorted((root / 'live/readings').glob('*.json')):
        edition = ReadingEdition.model_validate_json(path.read_text())
        before = edition.model_dump_json()
        for page in edition.pages:
            furniture = [line.strip() for line in (page.header + '\n' + page.footer).splitlines() if len(line.strip()) > 12]
            if furniture and Counter(furniture).most_common(1)[0][1] >= 4:
                warning = 'Repeated OCR header/footer pattern may be invented decoration; compare the original PDF.'
                if warning not in page.warnings:
                    page.warnings.append(warning)
                    warned += 1
            if (edition.document_id == 'gruene-2025' and page.number == 12
                    and edition.source_pdf_sha256 == 'bf8d15021d8cc2695cb97d0d4a4bc9b7b93de54b86d491d8536b1325354dc213'
                    and page.markdown.count('Russ-\n\nRusslands') == 1):
                # Visually checked against the original PDF in the local OCR acceptance test.
                # Exact change and original OCR digest retained; NOT marked human-reviewed.
                page.ocr_markdown_sha256 = digest(page.markdown)
                page.corrections.append(ReadingCorrection(before='Russ-\n\nRusslands', after='Russlands',
                    source_evidence='Original PDF page 12, column boundary: Russ- + lands. '
                                    'Agent visual source inspection; human review remains pending.'))
                page.markdown = page.markdown.replace('Russ-\n\nRusslands', 'Russlands')
                corrected += 1
        if before == edition.model_dump_json():
            continue
        markdown = '\n\n'.join(f'<!-- page:{p.number} -->\n\n{p.markdown}' for p in edition.pages).rstrip() + '\n'
        edition.markdown_sha256 = digest(markdown)
        (root / edition.markdown_path).write_text(markdown)
        validate_reading(edition, root, records[edition.document_id])
        write_json(path, edition)
    print(f'{corrected} reversible PDF-checked correction; {warned} additional header/footer warnings')


if __name__ == '__main__':
    main()
