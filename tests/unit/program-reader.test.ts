import { describe, expect, it } from 'vitest';
import { getData } from '../../src/lib/data';
import { readingHtml } from '../../src/lib/program-reader';
import { searchText } from '../../src/lib/program-reader-search';
import { readingPageHref, sourcePageAnchors } from '../../src/lib/document-anchors';
import { readingEdition } from '../../src/lib/readings';
import type { Program } from '../../src/lib/types';

describe('untrusted document Markdown', () => {
  it('renders emphasis, lists and soft line wraps without exposing Markdown syntax', () => {
    const html = readingHtml('**Konkrete Zusage**\n\nEin Satz\nauf zwei PDF-Zeilen.\n\n- Punkt eins\n- Punkt zwei');
    expect(html).toContain('<strong>Konkrete Zusage</strong>');
    expect(html).toContain('<li>Punkt eins</li>');
    expect(html).not.toContain('<br');
    expect(html).not.toContain('**');
  });

  it('does not accept raw HTML, document-supplied IDs or active content', () => {
    const html = readingHtml('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n<div id="content">Text</div>');
    expect(html).not.toMatch(/<(script|img|div)\b/);
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('&lt;div id=');
  });

  it('renders image alt text without making a tracking or network request', () => {
    const html = readingHtml('![Bildbeschreibung](https://untrusted.example/track.svg)');
    expect(html).toContain('Bildbeschreibung');
    expect(html).not.toContain('<img');
    expect(html).not.toContain('track.svg');
  });

  it('only allows explicit HTTP(S) hyperlinks, not active protocols or local routes', () => {
    for (const url of ['javascript:alert%281%29', 'data:text/html,attack', 'file:///etc/passwd', '/fake-source/', '//other.example/']) {
      expect(readingHtml(`[Link](${url})`)).not.toContain('<a ');
    }
    expect(readingHtml('[Beleg](https://example.org/path?q=1&x=2)')).toContain('href="https://example.org/path?q=1&amp;x=2"');
  });

  it('does not let PDF font-size headings replace the reader document hierarchy', () => {
    const html = readingHtml('# Große Überschrift\n\n### Kleine Überschrift');
    expect(html).not.toMatch(/<h[1-5]\b/);
    expect(html).toContain('<h6>Große Überschrift</h6>');
  });

  it('removes only control glyphs from the display, not punctuation or ordinary hyphens', () => {
    expect(readingHtml('CO2-Preis\b: 50–100 Euro.\nNicht geändert.')).toContain('CO2-Preis: 50–100 Euro.\nNicht geändert.');
  });

  it('normalises search terms identically on server and browser, without treating them as HTML', () => {
    expect(searchText('Für\nStraßen und Breit\u00adband')).toBe('fur strassen und breitband');
    expect(searchText('<SCRIPT>alert(1)</SCRIPT>')).toBe('<script>alert(1)</script>');
  });
});

describe('legacy citations in the single OCR reader', () => {
  function fixture(): Program {
    const program = structuredClone(getData('demo').programs[0]);
    program.leaves = [1, 2, 3, 4].map(n => ({ id: `demo-source-${n}`, text: `Absatz ${n}`,
      reference: { page: n, line_start: n, line_end: n, quote: `Absatz ${n}` } }));
    program.tree = { id: 'demo-root', title: 'Programm', leaf_ids: [], children: [
      { id: 'demo-chapter-a', title: 'Kapitel A', leaf_ids: ['demo-source-1'], children: [
        { id: 'demo-heading-a', title: 'Ein Thema', leaf_ids: ['demo-source-2', 'demo-source-4'], children: [] },
      ] },
      { id: 'demo-chapter-b', title: 'Kapitel B', leaf_ids: ['demo-source-3'], children: [] },
    ] };
    return program;
  }

  it('preserves every published paragraph and source-disclosure bookmark on its original PDF page', () => {
    for (const program of getData('live').programs) {
      const before = JSON.stringify(program);
      const anchors = sourcePageAnchors(program.leaves, program.tree);
      for (const leaf of program.leaves) {
        expect(anchors.get(leaf.reference.page)).toContain(leaf.id);
        expect(anchors.get(leaf.reference.page)).toContain(`${leaf.id}-source`);
      }
      const ids = [...anchors.values()].flat();
      expect(new Set(ids).size).toBe(ids.length);
      const edition = readingEdition(program.id)!;
      expect([...anchors.keys()].every(number => edition.pages.some(p => p.number === number))).toBe(true);
      expect(JSON.stringify(program)).toBe(before);
    }
  });

  it('preserves law passage fragments without copying source text into a new rendering', () => {
    for (const law of getData('live').laws) {
      const before = JSON.stringify(law);
      const anchors = sourcePageAnchors(law.passages);
      expect([...anchors.values()].flat()).toHaveLength(law.passages.length);
      for (const passage of law.passages) expect(anchors.get(passage.reference.page)).toContain(passage.id);
      const edition = readingEdition(law.id)!;
      expect([...anchors.keys()].every(number => edition.pages.some(p => p.number === number))).toBe(true);
      expect(JSON.stringify(law)).toBe(before);
    }
  });

  it('preserves the old chapter, root and continuation fragment IDs', () => {
    const program = fixture();
    const anchors = sourcePageAnchors(program.leaves, program.tree);
    expect(anchors.get(1)).toEqual(['demo-source-1', 'demo-source-1-source', 'demo-root', 'demo-chapter-a']);
    expect(anchors.get(2)).toContain('demo-heading-a');
    expect(anchors.get(3)).toContain('demo-chapter-b');
    expect(anchors.get(4)).toContain('demo-chapter-a-continuation-2');
    expect(anchors.get(4)).toContain('demo-heading-a-continuation-2');
  });

  it('handles subsections interleaved with parent paragraphs without moving their anchors', () => {
    const program = fixture();
    program.tree.children[0].leaf_ids.push('demo-source-3');
    program.tree.children.pop();
    const anchors = sourcePageAnchors(program.leaves, program.tree);
    expect(anchors.get(3)).toEqual(['demo-source-3', 'demo-source-3-source']);
    expect(anchors.get(4)).toContain('demo-heading-a-continuation-2');
    expect([...anchors.values()].flat()).not.toContain('demo-chapter-a-continuation-2');
  });

  it('fails explicitly for a leaf absent from the original tree', () => {
    const program = fixture();
    program.tree.children.pop();
    expect(() => sourcePageAnchors(program.leaves, program.tree)).toThrow('demo-source-3');
  });

  it('handles root-only programmes and documents with no extracted evidence', () => {
    const program = fixture();
    program.tree.children = [];
    program.tree.leaf_ids = program.leaves.map(l => l.id);
    expect(sourcePageAnchors(program.leaves, program.tree).get(1)).toContain('demo-root');
    expect(sourcePageAnchors([]).size).toBe(0);
  });

  it('new criterion and impact links use OCR pages rather than the retired text tree', () => {
    expect(readingPageHref('programs', 'gruene-2025', 12)).toBe('/live/programme/gruene-2025/#reading-page-12');
    expect(readingPageHref('laws', 'bgbl-1-2025-173', 1)).toBe('/live/gesetze/bgbl-1-2025-173/#reading-page-1');
  });
});
