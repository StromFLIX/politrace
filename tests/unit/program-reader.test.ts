import { describe, expect, it } from 'vitest';
import { getData } from '../../src/lib/data';
import { isLayoutLeaf, readingChapters, readingHtml, searchText } from '../../src/lib/program-reader';
import type { Program } from '../../src/lib/types';

describe('untrusted programme Markdown', () => {
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

describe('source-order programme reader', () => {
  it('preserves all existing leaves and their order without changing canonical data', () => {
    for (const dataset of ['demo', 'live'] as const) {
      for (const program of getData(dataset).programs) {
        const before = JSON.stringify(program);
        const chapters = readingChapters(program);
        const ids = chapters.flatMap(c => c.blocks.filter(b => b.kind === 'passage').map(b => b.leaf.id));
        expect(ids).toEqual(program.leaves.map(l => l.id));
        expect(new Set(ids).size).toBe(program.leaves.length);
        expect(chapters.flatMap(c => c.leafIds)).toEqual(ids);
        const anchors = chapters.flatMap(c => [c.id, ...c.blocks.filter(b => b.kind === 'heading').map(b => b.id)]);
        expect(new Set(anchors).size).toBe(anchors.length);
        expect(JSON.stringify(program)).toBe(before);
      }
    }
  });

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

  it('keeps a recurring thematic branch in source order with stable first anchors', () => {
    const chapters = readingChapters(fixture());
    expect(chapters.map(c => c.id)).toEqual(['demo-chapter-a', 'demo-chapter-b', 'demo-chapter-a-continuation-2']);
    expect(chapters[2].continued).toBe(true);
    expect(chapters[2].blocks[0]).toMatchObject({ id: 'demo-heading-a-continuation-2', continued: true, leafIds: ['demo-source-4'] });
    expect(chapters[0].blocks[1]).toMatchObject({ id: 'demo-heading-a', leafIds: ['demo-source-2'] });
  });

  it('never moves all parent paragraphs ahead of their interleaved subsections', () => {
    const program = fixture();
    program.tree.children[0].leaf_ids.push('demo-source-3');
    program.tree.children.pop();
    const chapters = readingChapters(program);
    expect(chapters).toHaveLength(1);
    expect(chapters[0].blocks.filter(b => b.kind === 'passage').map(b => b.number)).toEqual([1, 2, 3, 4]);
    expect(chapters[0].blocks.filter(b => b.kind === 'heading').map(b => b.leafIds)).toEqual([['demo-source-2'], ['demo-source-4']]);
  });

  it('fails explicitly rather than dropping a leaf missing from the tree', () => {
    const program = fixture();
    program.tree.children.pop();
    expect(() => readingChapters(program)).toThrow('demo-source-3');
  });

  it('compacts known heading furniture only, never text with additional policy words or amounts', () => {
    const program = fixture();
    const leaf = program.leaves[0];
    const sections = ['Kapitel 1: Eine gute Zukunft'];
    leaf.text = '1\nK A P I T E L\n# 1\n\nEINE GUTE ZUKUNFT';
    expect(isLayoutLeaf(leaf, program, sections)).toBe(true);
    leaf.text += '\n\n15 Euro Mindestlohn';
    expect(isLayoutLeaf(leaf, program, sections)).toBe(false);
    leaf.text = 'Eine gute Zukunft.';
    expect(isLayoutLeaf(leaf, program, sections)).toBe(false);
  });

  it('keeps root-only programmes readable', () => {
    const program = fixture();
    program.tree.children = [];
    program.tree.leaf_ids = program.leaves.map(l => l.id);
    expect(readingChapters(program)[0]).toMatchObject({ id: 'demo-root', leafIds: program.tree.leaf_ids });
  });
});
