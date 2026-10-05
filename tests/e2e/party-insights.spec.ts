import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import type { PartyInsights } from '../../src/lib/party-insights';
import { defaultPageSize } from '../../src/lib/criteria-browser';

type Period = PartyInsights & { election_year: number };
type PartyExport = { insights: {
  timeline_basis: string; fulfilment_history_available: boolean; law_groups_overlap: boolean; periods: Period[];
} };
const number = (value: number) => value.toLocaleString('de-DE');
const resultCount = (matched: number, total: number) => matched
  ? `1–${number(Math.min(defaultPageSize, matched))} von ${number(matched)} Kriterien${matched !== total ? ` (${number(total)} insgesamt)` : ''}`
  : `0 von ${number(total)} Kriterien`;
const percent = (value: number | null) => value === null ? '—' : value > 0 && value < 0.1 ? '<0,1 %' :
  `${new Intl.NumberFormat('de-DE', { maximumFractionDigits: 1 }).format(value)} %`;
const statuses = { fulfilled: 'fulfilled', partial: 'partial', contradicted: 'contradicted', mixed: 'mixed', unassessed: 'unknown' } as const;

async function partyExport(request: APIRequestContext, id: string) {
  const response = await request.get(`/api/v1/live/parties/${id}.json`);
  expect(response.ok()).toBe(true);
  return await response.json() as PartyExport;
}

async function openParty(page: Page, request: APIRequestContext, id = 'gruene') {
  const { insights } = await partyExport(request, id);
  const period = insights.periods[0];
  await page.goto(`/live/parteien/${id}/?jahr=${period.election_year}`);
  return { period, panel: page.locator(`[data-period-panel="${period.election_year}"]`) };
}

async function fitsViewport(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test('party balances match their exported programme counts, including empty parties', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const { items: parties } = await (await request.get('/api/v1/live/parties.json')).json();
  for (const { id } of parties) {
    const { insights } = await partyExport(request, id);
    expect(insights.timeline_basis).toBe('current_accepted_evidence_by_law_publication_month');
    expect(insights.fulfilment_history_available).toBe(false);
    expect(insights.law_groups_overlap).toBe(true);
    await page.goto(`/live/parteien/${id}/`);
    if (!insights.periods.length) {
      await expect(page.getByRole('heading', { name: 'Noch kein Wahlprogramm importiert' })).toBeVisible();
      await expect(page.locator('[data-party-insights]')).toHaveCount(0);
      continue;
    }
    const period = insights.periods[0];
    const dashboard = page.locator(`[data-period-panel="${period.election_year}"] [data-party-insights]`);
    await expect(dashboard).toBeVisible();
    for (const [status, key] of Object.entries(statuses)) {
      await expect(dashboard.locator(`[data-insight-status="${status}"] [data-status-count]`)).toHaveText(number(period.criteria[key]));
    }
    expect(Object.values(statuses).reduce((sum, key) => sum + period.criteria[key], 0)).toBe(period.criteria.total);
    await expect(dashboard.locator('[data-fulfilment]')).toHaveText(percent(period.fulfilment_percent));
    await expect(dashboard.locator('[data-coverage]')).toHaveText(percent(period.coverage_percent));
    for (const [key, value] of Object.entries({ all: period.laws.total, supporting: period.laws.supporting, opposing: period.laws.opposing, mixed: period.laws.mixed })) {
      await expect(dashboard.locator(`[data-law-total="${key}"]`)).toHaveText(number(value));
    }
    await fitsViewport(page);
    for (const anchor of ['bilanz', 'zeitverlauf', 'gesetzeswirkung', 'kriterien']) {
      await expect(page.locator(`[id="${anchor}"]`)).toHaveCount(1);
      await expect(page.locator(`[id="${anchor}"]`)).toBeVisible();
    }
  }
  expect(errors).toEqual([]);
});

test('status cards clear unrelated filters and open shareable criterion results', async ({ page, request }) => {
  const { period, panel } = await openParty(page, request, 'linke');
  for (const [status, key] of Object.entries(statuses)) {
    await panel.getByRole('searchbox').fill('nichtvorhandenerbegriffxyz');
    await panel.locator(`[data-insight-status="${status}"]`).click();
    await expect(panel.getByRole('combobox', { name: 'Status', exact: true })).toHaveValue(status);
    await expect(panel.getByRole('searchbox')).toHaveValue('');
    await expect(panel.locator('[data-result-count]')).toHaveText(resultCount(period.criteria[key], period.criteria.total));
    await expect(panel.locator('.criterion-row:visible')).toHaveCount(Math.min(defaultPageSize, period.criteria[key]));
    expect(new URL(page.url()).searchParams.get('status')).toBe(status);
    expect(new URL(page.url()).searchParams.get('jahr')).toBe(String(period.election_year));
    expect(new URL(page.url()).hash).toBe('#kriterien');
    await expect(panel.locator('[data-results-start]')).toBeFocused();
  }
  await page.reload();
  await expect(panel.getByRole('combobox', { name: 'Status', exact: true })).toHaveValue('unassessed');
  await expect(panel.locator('.criterion-row:visible')).toHaveCount(Math.min(defaultPageSize, period.criteria.unknown));
  await panel.locator('.fulfilment-headline [data-criteria-filter]').click();
  await expect(panel.getByRole('combobox', { name: 'Status', exact: true })).toHaveValue('');
  await expect(panel.locator('[data-result-count]')).toHaveText(resultCount(period.criteria.total, period.criteria.total));
});

test('dashboard drill-down resets pagination and preserves browser history', async ({ page, request }) => {
  const { period, panel } = await openParty(page, request, 'linke');
  const pages = panel.getByRole('navigation', { name: 'Kriterienseiten oben' });
  const rows = panel.locator('.criterion-row:visible');
  const hrefs = () => rows.evaluateAll(items => items.map(item => item.getAttribute('href')));
  await panel.getByRole('combobox', { name: 'Kriterien pro Seite' }).selectOption('50');
  await pages.getByRole('button', { name: 'Nächste Seite' }).click();
  await expect(pages.locator('[aria-current="page"]')).toHaveText('2');
  const previousUrl = page.url();
  const previousRows = await hrefs();
  await panel.locator('[data-insight-status="unassessed"]').click();
  await expect(rows).toHaveCount(Math.min(defaultPageSize, period.criteria.unknown));
  expect(new URL(page.url()).searchParams.has('seite')).toBe(false);
  expect(new URL(page.url()).searchParams.has('pro_seite')).toBe(false);
  const dashboardUrl = page.url();
  await page.goBack();
  await expect(page).toHaveURL(previousUrl);
  await expect(pages.locator('[aria-current="page"]')).toHaveText('2');
  await expect(panel.getByRole('combobox', { name: 'Kriterien pro Seite' })).toHaveValue('50');
  expect(await hrefs()).toEqual(previousRows);
  await page.goForward();
  await expect(page).toHaveURL(dashboardUrl);
  await expect(panel.getByRole('combobox', { name: 'Status', exact: true })).toHaveValue('unassessed');
  await expect(panel.locator('[data-result-count]')).toHaveText(resultCount(period.criteria.unknown, period.criteria.total));
});

test('topic breakdown expands and links to the selected programme topic', async ({ page, request }) => {
  const { period, panel } = await openParty(page, request);
  await expect(panel.locator('[data-topic-insight]:visible')).toHaveCount(Math.min(5, period.topics.length));
  const more = panel.locator('[data-topic-more]');
  if (period.topics.length > 5) {
    await more.click();
    await expect(more).toHaveAttribute('aria-expanded', 'true');
    await expect(panel.locator('[data-topic-insight]:visible')).toHaveCount(period.topics.length);
    await more.click();
    await expect(more).toHaveAttribute('aria-expanded', 'false');
    await expect(panel.locator('[data-topic-insight]:visible')).toHaveCount(5);
  }
  const topic = period.topics[0];
  await panel.locator(`[data-topic-insight="${topic.topic}"]`).click();
  await expect(panel.getByRole('combobox', { name: 'Thema', exact: true })).toHaveValue(topic.topic);
  await expect(panel.locator('[data-result-count]')).toHaveText(resultCount(topic.total, period.criteria.total));
  await expect(panel.locator('.criterion-row:visible')).toHaveCount(Math.min(defaultPageSize, topic.total));
  await page.reload();
  await expect(panel.getByRole('combobox', { name: 'Thema', exact: true })).toHaveValue(topic.topic);
  expect(new URL(page.url()).hash).toBe('#kriterien');
});

test('law highlights sort, paginate and filter overlapping directions', async ({ page, request }) => {
  const { period, panel } = await openParty(page, request);
  const highlights = panel.locator('[data-law-highlights]');
  const visible = highlights.locator('[data-law-item]:visible');
  const ids = () => visible.evaluateAll(items => items.map(item => (item as HTMLElement).dataset.id));
  await expect(visible).toHaveCount(Math.min(3, period.laws.total));
  expect(await ids()).toEqual(period.law_effects.slice(0, 3).map(law => law.id));
  if (period.laws.total > 3) {
    await highlights.locator('[data-law-more]').click();
    await expect(visible).toHaveCount(Math.min(8, period.laws.total));
  }
  for (const order of ['coverage', 'recent'] as const) {
    await highlights.locator('[data-law-order]').selectOption(order);
    const expected = [...period.law_effects].sort((a, b) =>
      (order === 'coverage' ? b.newly_covered - a.newly_covered : b.published_at.localeCompare(a.published_at)) ||
      b.affected - a.affected || b.newly_covered - a.newly_covered || b.published_at.localeCompare(a.published_at) || a.id.localeCompare(b.id));
    expect(await ids()).toEqual(expected.slice(0, 3).map(law => law.id));
  }
  for (const direction of ['supporting', 'opposing', 'mixed', ''] as const) {
    await panel.locator(`[data-law-shortcut="${direction}"]`).click();
    await expect(highlights.locator('[data-law-direction]')).toHaveValue(direction);
    await expect(highlights.locator('[data-law-direction]')).toBeFocused();
    const count = direction ? period.laws[direction] : period.laws.total;
    await expect(highlights.locator('[data-law-count]')).toContainText(`${count} von ${period.laws.total} Gesetzen`);
    await expect(visible).toHaveCount(Math.min(3, count));
    if (!count) await expect(highlights.locator('[data-law-empty]')).toBeVisible();
    else await expect(highlights.locator('[data-law-empty]')).toBeHidden();
  }
  await fitsViewport(page);
});

test('law evidence opens the exact criterion and original-law evidence', async ({ page, request }) => {
  const { period, panel } = await openParty(page, request);
  const law = period.law_effects[0];
  const evidence = law.evidence[0];
  const card = panel.locator(`[data-law-item][data-id="${law.id}"]`);
  await card.locator('summary').click();
  const evidenceRow = card.locator('.law-criterion-evidence > li').first();
  const lawLink = await evidenceRow.getByRole('link', { name: 'Gesetz & Originalbeleg' }).getAttribute('href');
  await evidenceRow.getByRole('link', { name: evidence.criterion_title, exact: true }).click();
  await expect(page.getByRole('heading', { name: evidence.criterion_title, exact: true })).toBeVisible();
  await expect(page.locator(`[id="${evidence.impact_id}"]`)).toBeVisible();
  await page.goto(lawLink!);
  await expect(page.getByRole('heading', { level: 1, name: law.title, exact: true })).toBeVisible();
  const sourceCard = page.locator(`[id="${evidence.impact_id}"]`);
  await expect(sourceCard).toBeVisible();
  await expect(sourceCard.locator('blockquote')).not.toBeEmpty();
});

test('timeline exposes monthly values without inventing historical fulfilment', async ({ page, request }) => {
  const { period, panel } = await openParty(page, request, 'linke');
  const timeline = panel.locator('.timeline-card');
  await expect(timeline.getByRole('img')).toHaveAccessibleName(`Entwicklung der Belegabdeckung für Programm ${period.election_year}`);
  await expect(timeline.getByRole('img')).toHaveAccessibleDescription(/Keine historische Umsetzungsquote/);
  await expect(timeline.locator('figcaption')).toContainText('keine historische Umsetzungsquote');
  const last = period.timeline.at(-1)!;
  expect(last.covered).toBe(period.criteria.covered);
  expect(last.opposing).toBeLessThanOrEqual(last.covered);
  await timeline.locator('summary').click();
  await expect(timeline.locator('tbody tr')).toHaveCount(period.timeline.length);
  const cells = timeline.locator('tbody tr').last().locator('td');
  await expect(cells.nth(1)).toHaveText(number(last.covered));
  await expect(cells.nth(2)).toHaveText(percent(period.coverage_percent));
  await expect(cells.nth(3)).toHaveText(number(last.opposing));
  for (const law of period.law_effects) {
    await expect(timeline.locator(`tbody a[href="/live/gesetze/${law.id}/"]`)).toHaveCount(1);
  }
  await fitsViewport(page);
});

test('dashboard fits narrow and wide viewports', async ({ page, request }, testInfo) => {
  const { panel } = await openParty(page, request, 'linke');
  await page.screenshot({ path: testInfo.outputPath('party-viewport.png') });
  await panel.locator('[data-party-insights]').screenshot({ path: testInfo.outputPath('party-dashboard.png') });
  for (const width of [320, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await fitsViewport(page);
    await expect(panel.locator('[data-insight-status="unassessed"]')).toBeVisible();
  }
});

test.describe('without JavaScript', () => {
  test.use({ javaScriptEnabled: false });
  test('all evidence and topics remain readable without interactive controls', async ({ page, request }) => {
    const { period, panel } = await openParty(page, request);
    await expect(panel.locator('[data-law-item]:visible')).toHaveCount(period.laws.total);
    await expect(panel.locator('[data-topic-insight]:visible')).toHaveCount(period.topics.length);
    await expect(panel.locator('.criterion-row:visible')).toHaveCount(period.criteria.total);
    await expect(panel.locator('[data-law-controls]')).toBeHidden();
    await expect(panel.locator('[data-law-more]')).toBeHidden();
    await expect(panel.locator('[data-topic-more]')).toBeHidden();
    await expect(panel.locator('noscript .notice')).toBeVisible();
    await expect(panel.locator('noscript .notice')).toContainText('Alle Kriterien sind darunter vollständig lesbar');
    await fitsViewport(page);
  });
});
