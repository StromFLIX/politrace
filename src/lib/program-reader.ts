import MarkdownIt from 'markdown-it';
import type { Leaf, Program, TreeNode } from './types';

// Programme text is untrusted. This renderer runs at build time, has no plugins,
// escapes raw HTML and never emits images, embedded media or document-supplied IDs.
const markdown = new MarkdownIt({ html: false, linkify: false, typographer: false, breaks: false });
const validLink = markdown.validateLink.bind(markdown);
markdown.validateLink = url => /^https?:\/\//i.test(url) && validLink(url);
markdown.renderer.rules.image = (tokens, index) => markdown.utils.escapeHtml(tokens[index].content);
for (const rule of ['heading_open', 'heading_close'] as const) {
  markdown.renderer.rules[rule] = (tokens, index, options, _env, renderer) => {
    // The programme and chapter headings belong to the reader, not the PDF's font sizes.
    tokens[index].tag = 'h6';
    return renderer.renderToken(tokens, index, options);
  };
}

export function readingHtml(source: string): string {
  // Display-only: remove PDF control glyphs, not words, punctuation or regular hyphens.
  // Canonical Markdown and the exact-source disclosure are never changed.
  return markdown.render(source.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, ''));
}

export { searchText } from './program-reader-search';

export function isLayoutLeaf(leaf: Leaf, program: Program, sections: string[]): boolean {
  // Compact display only, never an extraction/abstention decision. Fold a short
  // heading/footer only if EVERY token already appears in its source titles,
  // publisher, or physical page number. The complete text remains one click away.
  if (leaf.text.length > 600 || (!/^\s*#{1,6}\s/m.test(leaf.text) && leaf.text !== leaf.text.toLocaleUpperCase('de'))) return false;
  const words = (text: string) => text.replace(/K A P I T E L/g, 'Kapitel').normalize('NFKC')
    .toLocaleLowerCase('de').match(/[\p{L}\p{N}]+/gu) ?? [];
  const allowed = new Set(words([program.title, program.source.publisher, ...sections, String(leaf.reference.page)].join(' ')));
  const source = words(leaf.text);
  return source.length > 0 && source.every(word => allowed.has(word));
}

export type ReaderHeading = {
  kind: 'heading'; id: string; title: string; level: number; continued: boolean; leafIds: string[];
};
export type ReaderPassage = { kind: 'passage'; leaf: Leaf; number: number; sections: string[] };
export type ReaderChapter = {
  id: string; title: string; continued: boolean; ancillary: boolean;
  firstPage: number; lastPage: number; leafIds: string[]; blocks: (ReaderHeading | ReaderPassage)[];
};

/** Render the canonical source order, not parent leaves first and children afterwards.
 * A thematic branch can recur later in a PDF. Keep its original anchor on the first
 * occurrence, add a labelled continuation, and never repeat or omit a source leaf.
 */
export function readingChapters(program: Program): ReaderChapter[] {
  const paths = new Map<string, TreeNode[]>();
  function visit(node: TreeNode, parents: TreeNode[]) {
    const path = [...parents, node];
    for (const id of node.leaf_ids) paths.set(id, path);
    for (const child of node.children) visit(child, path);
  }
  visit(program.tree, []);
  const occurrences = new Map<string, number>();
  function anchor(node: TreeNode) {
    const occurrence = (occurrences.get(node.id) ?? 0) + 1;
    occurrences.set(node.id, occurrence);
    return { id: occurrence === 1 ? node.id : `${node.id}-continuation-${occurrence}`, continued: occurrence > 1 };
  }
  const chapters: ReaderChapter[] = [];
  let previous: TreeNode[] = [];
  let activeHeadings: ReaderHeading[] = [];
  program.leaves.forEach((leaf, index) => {
    const path = paths.get(leaf.id);
    if (!path) throw new Error(`Programme reader: leaf ${leaf.id} is absent from its tree`);
    const sections = path.length > 1 ? path.slice(1) : path;
    const top = sections[0];
    if (top.id !== previous[0]?.id) {
      chapters.push({ ...anchor(top), title: top.title,
        ancillary: /^(titelseite|deckblatt|inhaltsverzeichnis|front matter|impressum)$/i.test(top.title.trim()),
        firstPage: leaf.reference.page, lastPage: leaf.reference.page, leafIds: [], blocks: [] });
      previous = [];
      activeHeadings = [];
    }
    const chapter = chapters[chapters.length - 1];
    let shared = 0;
    while (shared < sections.length && sections[shared]?.id === previous[shared]?.id) shared++;
    activeHeadings = activeHeadings.slice(0, Math.max(0, shared - 1));
    for (let depth = Math.max(1, shared); depth < sections.length; depth++) {
      const heading: ReaderHeading = { kind: 'heading', ...anchor(sections[depth]),
        title: sections[depth].title, level: Math.min(6, depth + 2), leafIds: [] };
      chapter.blocks.push(heading);
      activeHeadings.push(heading);
    }
    for (const heading of activeHeadings) heading.leafIds.push(leaf.id);
    chapter.blocks.push({ kind: 'passage', leaf, number: index + 1, sections: sections.map(s => s.title) });
    chapter.leafIds.push(leaf.id);
    chapter.lastPage = leaf.reference.page;
    previous = sections;
  });
  return chapters;
}
