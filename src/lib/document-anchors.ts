import type { Leaf, TreeNode } from './types';

/** Compatibility only: old paragraph/chapter bookmarks now locate the same PDF
 * page in the OCR reader. This is a page mapping, NOT an exact OCR text alignment.
 * Never mutate the source tree, its IDs, or its quotations to fit a new edition.
 */
export function sourcePageAnchors(leaves: Leaf[], tree?: TreeNode): Map<number, string[]> {
  const anchors = new Map<string, number>();
  for (const leaf of leaves) {
    anchors.set(leaf.id, leaf.reference.page);
    if (tree) anchors.set(`${leaf.id}-source`, leaf.reference.page);
  }
  if (tree && leaves.length) {
    anchors.set(tree.id, leaves[0].reference.page);
    const paths = new Map<string, TreeNode[]>();
    function visit(node: TreeNode, parents: TreeNode[]) {
      const path = [...parents, node];
      for (const id of node.leaf_ids) paths.set(id, path);
      for (const child of node.children) visit(child, path);
    }
    visit(tree, []);
    const occurrences = new Map<string, number>();
    let previous: TreeNode[] = [];
    for (const leaf of leaves) {
      const path = paths.get(leaf.id);
      if (!path) throw new Error(`Source anchor: leaf ${leaf.id} is absent from its tree`);
      const sections = path.length > 1 ? path.slice(1) : path;
      let shared = 0;
      while (shared < sections.length && sections[shared]?.id === previous[shared]?.id) shared++;
      for (const section of sections.slice(shared)) {
        const count = (occurrences.get(section.id) ?? 0) + 1;
        occurrences.set(section.id, count);
        anchors.set(count === 1 ? section.id : `${section.id}-continuation-${count}`, leaf.reference.page);
      }
      previous = sections;
    }
  }
  const byPage = new Map<number, string[]>();
  for (const [id, page] of anchors) {
    const ids = byPage.get(page) ?? [];
    ids.push(id);
    byPage.set(page, ids);
  }
  return byPage;
}

export function readingPageHref(collection: 'programs' | 'laws', id: string, page: number): string {
  return `/live/${collection === 'programs' ? 'programme' : 'gesetze'}/${id}/#reading-page-${page}`;
}
