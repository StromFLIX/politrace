import fs from 'node:fs';
import path from 'node:path';
import bundestag21 from '../../data/sources/bundestag-21.json';
import type { Data, Dataset, Party, Program, Criterion, Law, Impact, Vote } from './types';
export { metrics } from './metrics';

export const dataRoot = path.resolve('data');
export const repoUrl = 'https://github.com/StromFLIX/politrace';
// Only real records are published. Fictional fixtures live under tests, not the site/API.
export const datasets: Dataset[] = ['live'];

function records<T>(dataset: Dataset, collection: string): T[] {
  const root = dataset === 'demo' && process.env.NODE_ENV === 'test' ? path.resolve('tests/fixtures') : dataRoot;
  const dir = path.join(root, dataset, collection);
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter(f => f.endsWith('.json')).sort().map(f => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')));
}
// Astro renders thousands of static record pages. Parse each immutable build snapshot once,
// not once per route/module (which multiplies memory and I/O for historical law corpora).
const snapshots = new Map<Dataset, Data>();
export function getData(dataset: Dataset): Data {
  const cached = snapshots.get(dataset);
  if (cached) return cached;
  const data: Data = {
    dataset, parties: JSON.parse(fs.readFileSync(path.join(dataRoot, 'parties.json'), 'utf8')) as Party[],
    programs: records<Program>(dataset, 'programs'), criteria: records<Criterion>(dataset, 'criteria'),
    laws: records<Law>(dataset, 'laws').sort((a, b) => b.published_at.localeCompare(a.published_at)),
    impacts: records<Impact>(dataset, 'impacts'), votes: records<Vote>(dataset, 'votes'),
  };
  snapshots.set(dataset, data);
  return data;
}
export function defaultDataset(): Dataset {
  return 'live';
}
export function overviewParties(data: Pick<Data, 'dataset' | 'parties'>, year: number): Party[] {
  // Parliamentary representation, not coalition membership or import progress, defines the current scope.
  // Keep the registry and other election years intact for historical records and API references.
  if (data.dataset !== 'live' || year !== bundestag21.election_year) return data.parties;
  const represented = new Set(bundestag21.programs.map(program => program.party_id));
  return data.parties.filter(party => represented.has(party.id));
}
export const topics: Record<string, string> = {
  arbeit: 'Arbeit & Löhne', wirtschaft: 'Wirtschaft', steuern: 'Steuern', soziales: 'Soziales & Rente',
  klima: 'Klimaschutz', energie: 'Energie', mobilitaet: 'Mobilität', wohnen: 'Wohnen', bildung: 'Bildung',
  gesundheit: 'Gesundheit', migration: 'Migration', digitales: 'Digitalisierung', demokratie: 'Demokratie',
  sicherheit: 'Sicherheit', europa: 'Europa',
};
export const statusLabels = { unassessed: 'Offen', fulfilled: 'Gesetzlich umgesetzt', partial: 'Teilweise umgesetzt', contradicted: 'Widersprochen', mixed: 'Gemischte Wirkung' };
export const impactLabels: Record<number, string> = { '-2': 'Widerspricht direkt', '-1': 'Erschwert', 0: 'Gemischte Wirkung', 1: 'Unterstützt teilweise', 2: 'Setzt direkt um' };
export const reviewLabels = { proposed: 'Prüfung offen', reviewed: 'Redaktionell geprüft', rejected: 'Verworfen' };
export function formatDate(value: string) { return new Intl.DateTimeFormat('de-DE', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(value + 'T12:00:00Z')); }
export function editUrl(dataset: Dataset, collection: string, id: string) { return `${repoUrl}/edit/main/data/${dataset}/${collection}/${id}.json`; }
export function mdUrl(markdownPath: string, line?: number) { return `${repoUrl}/blob/main/data/${markdownPath}${line ? `#L${line}` : ''}`; }
export function sectionPath(tree: Program['tree'], leafId: string, parents: string[] = []): string[] {
  const current = [...parents, tree.title];
  if (tree.leaf_ids.includes(leafId)) return current;
  for (const child of tree.children) {
    const found = sectionPath(child, leafId, current);
    if (found.length) return found;
  }
  return [];
}
