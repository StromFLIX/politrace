// Shared by the build and the tiny browser controller. Keep the Markdown parser
// server-only; searching a programme must not download a renderer or contact an API.
export function searchText(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').replace(/\u00ad/g, '')
    .toLocaleLowerCase('de').replace(/ß/g, 'ss').replace(/\s+/g, ' ').trim();
}
