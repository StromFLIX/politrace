import MarkdownIt from 'markdown-it';

// OCR text is untrusted. This renderer runs at build time, has no plugins,
// escapes raw HTML and never emits images, embedded media or document-supplied IDs.
const markdown = new MarkdownIt({ html: false, linkify: false, typographer: false, breaks: false });
const validLink = markdown.validateLink.bind(markdown);
markdown.validateLink = url => /^https?:\/\//i.test(url) && validLink(url);
markdown.renderer.rules.image = (tokens, index) => markdown.utils.escapeHtml(tokens[index].content);
for (const rule of ['heading_open', 'heading_close'] as const) {
  markdown.renderer.rules[rule] = (tokens, index, options, _env, renderer) => {
    // Document/page headings belong to the reader, not the PDF's font sizes.
    tokens[index].tag = 'h6';
    return renderer.renderToken(tokens, index, options);
  };
}

export function readingHtml(source: string): string {
  // Display-only: remove control glyphs, not words, punctuation or regular hyphens.
  // The stored OCR edition and the separate canonical evidence stay unchanged.
  return markdown.render(source.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, ''));
}
