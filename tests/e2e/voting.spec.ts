import { test, expect } from '@playwright/test';
import type { Vote } from '../../src/lib/types';

const published = (v: Vote) => v.review.status !== 'rejected' && (v.review.status === 'reviewed' || ['bundestag-dip-v1', 'bundestag-structured-v2'].includes(v.evidence?.method ?? ''));

test('voting overview exposes denominators, every law and the source-linked API', async ({ page, request }) => {
  const { items: votes }: { items: Vote[] } = await (await request.get('/api/v1/live/votes.json')).json();
  const summary = await (await request.get('/api/v1/live/voting-summary.json')).json();
  const index = await (await request.get('/api/v1/live/index.json')).json();
  const coverage = await (await request.get(index.voting_coverage)).json();
  const laws = new Set(votes.filter(published).filter(v => v.groups.length).map(v => v.law_id));
  expect(summary.coverage.laws).toBe(index.counts.laws);
  expect(summary.coverage.with_positions).toBe(laws.size);
  expect(summary.coverage.with_positions + summary.coverage.decision_only + summary.coverage.without_decisions).toBe(index.counts.laws);
  expect(new Set(coverage.items.map((row: { law_id: string }) => row.law_id)).size).toBe(coverage.items.length);
  await page.goto('/live/abstimmungen/');
  await expect(page.getByRole('heading', { name: 'Abstimmungen & Wahlversprechen', exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Hauptnavigation' }).getByRole('link', { name: 'Abstimmungen' })).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('main')).toContainText('kein bewiesener Wortbruch');
  await page.locator('#abdeckung summary').click();
  await expect(page.locator('#abdeckung tbody tr')).toHaveCount(index.counts.laws);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('named ballots reconcile, filter by member/group/choice and retain correction links', async ({ page, request }) => {
  const { items }: { items: Vote[] } = await (await request.get('/api/v1/live/votes.json')).json();
  const vote = items.find(v => published(v) && v.type === 'roll_call' && v.members?.length)!;
  expect(vote).toBeDefined();
  const members = vote.members!;
  for (const group of vote.groups) for (const category of ['yes', 'no', 'abstain', 'absent', 'invalid'] as const) {
    expect(members.filter(m => m.group === group.group && m.vote === category).length).toBe(group[category] ?? 0);
  }
  await page.goto(`/live/gesetze/${vote.law_id}/#${vote.id}`);
  const card = page.locator(`[id="${vote.id}"]`);
  await expect(card.getByRole('img')).toHaveAttribute('aria-label', /nicht abgegeben.*ungültig/);
  await card.locator('[data-member-votes] summary').click();
  await expect(card.locator('[data-member-name]:visible')).toHaveCount(members.length);
  const member = members[0];
  await card.getByLabel('Name suchen').fill(member.name);
  await expect(card.locator('[data-member-name]:visible')).toHaveCount(members.filter(m => m.name.toLocaleLowerCase('de-DE').includes(member.name.toLocaleLowerCase('de-DE'))).length);
  await card.getByLabel('Name suchen').fill('');
  await card.getByLabel('Fraktion / Gruppe', { exact: true }).selectOption(member.group);
  await card.getByLabel('Stimme', { exact: true }).selectOption('no');
  await expect(card.locator('[data-member-name]:visible')).toHaveCount(members.filter(m => m.group === member.group && m.vote === 'no').length);
  await card.getByLabel('Name suchen').fill('kein-ergebnis-xyz');
  await expect(card.locator('[data-member-empty]')).toBeVisible();
  await expect(card.getByRole('link', { name: 'Beleg korrigieren' })).toHaveAttribute('href', /github.com\/StromFLIX\/politrace\/edit\/main\/data\/live\/votes\//);
  await expect(card.getByRole('link', { name: 'Amtliche Einzelstimmen (XLSX)' })).toHaveAttribute('href', /^https:\/\/www.bundestag.de\/resource\/blob\/.+\.xlsx$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('non-named decisions expose protocol positions without inventing counts or individual ballots', async ({ page, request }) => {
  const { items }: { items: Vote[] } = await (await request.get('/api/v1/live/votes.json')).json();
  const vote = items.find(v => published(v) && v.type === 'group_record' && v.stage === 'final_passage')!;
  expect(vote).toBeDefined();
  expect(vote.groups.every(g => g.yes === null && g.no === null && g.absent === null)).toBe(true);
  await page.goto(`/live/gesetze/${vote.law_id}/#${vote.id}`);
  const card = page.locator(`[id="${vote.id}"]`);
  await expect(card.locator('.votes-bar, [data-member-votes]')).toHaveCount(0);
  await expect(card).toContainText('keine Einzelstimmenzählung');
  await card.getByText('Belegkette und genaue Zuordnung', { exact: true }).click();
  expect(await card.locator('blockquote').textContent()).toBe(vote.evidence!.quote);
  await expect(card.getByRole('link', { name: /Original-Plenarprotokoll/ })).toHaveAttribute('href', vote.evidence!.protocol_source!.url);
  if (vote.evidence!.method === 'bundestag-structured-v2') {
    expect(vote.evidence!.protocol_format).toBe('xml');
    expect(vote.evidence!.protocol_source!.url).toMatch(/\.xml$/);
    await expect(card.getByRole('link', { name: 'Original-Plenarprotokoll (XML)' })).toBeVisible();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('programme comparisons remain filterable, traceable and non-accusatory', async ({ page, request }) => {
  const { items } = await (await request.get('/api/v1/live/voting-comparisons.json')).json();
  expect(items.length).toBeGreaterThan(0);
  const first = items[0];
  const vote = await (await request.get(first.vote_url)).json();
  const impact = await (await request.get(first.impact_url)).json();
  expect(vote.compares_to_law).toBe(true);
  expect(vote.stage).toBe('final_passage');
  expect(vote.scope).not.toBe('partial_law');
  expect(vote.evidence?.cross_check?.status).not.toBe('mismatch');
  expect(impact.criterion_id).toBe(first.criterion_id);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`/live/abstimmungen/?party=${first.party_id}#vergleiche`);
  await expect(page.getByLabel('Partei', { exact: true })).toHaveValue(first.party_id);
  await expect(page.locator('[data-comparison-row]:visible')).toHaveCount(items.filter((c: { party_id: string }) => c.party_id === first.party_id).length);
  await page.getByLabel('Einordnung', { exact: true }).selectOption('tension');
  await expect(page.locator('[data-comparison-row]:visible')).toHaveCount(items.filter((c: { party_id: string; outcome: string }) => c.party_id === first.party_id && c.outcome === 'tension').length);
  await page.getByLabel('Gesetz oder Zusage suchen').fill('<script>throw Error("unsafe")</script>');
  await expect(page.locator('[data-comparison-empty]')).toBeVisible();
  await page.getByRole('button', { name: 'Zurücksetzen', exact: true }).click();
  await expect(page.locator('[data-comparison-row]:visible')).toHaveCount(items.length);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
