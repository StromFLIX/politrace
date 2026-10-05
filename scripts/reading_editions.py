"""Create/reuse OCR reading editions without changing existing political evidence."""
import argparse
import logging
from pathlib import Path

from pipeline.reading import run_readings
from pipeline.store import ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=ROOT / 'data')
    parser.add_argument('--cache', type=Path, default=ROOT / '.cache/ocr')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-pages', type=int, default=10000)
    parser.add_argument('--ids', nargs='+')
    parser.add_argument('--collections', nargs='+', choices=['programs', 'laws'], default=['programs', 'laws'])
    args = parser.parse_args()
    result = run_readings(args.data, args.cache, workers=args.workers, ids=args.ids,
                          collections=args.collections, max_pages=args.max_pages)
    if result['failed'] or len(result['completed']) != result['total_documents']:
        raise SystemExit('Some documents remain pending/failed; see the persisted per-document progress report')


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s')
    logging.getLogger('pipeline').setLevel(logging.INFO)
    main()
