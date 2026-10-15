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
const share = (count: number, total: number) => total ? count / total * 100 : null;
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
    expect(insights.timeline_basis).toBe('current_accepted_evidence_by_law_publication_date');
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
      await expect(dashboard.locator(`[data-insight-status="${status}"] > [data-status-percent]`)).toHaveText(percent(share(period.criteria[key], period.criteria.total)));
    }
    expect(Object.values(statuses).reduce((sum, key) => sum + period.criteria[key], 0)).toBe(period.criteria.total);
    expect(period.implementation_percent).toBe(share(period.criteria.fulfilled + period.criteria.partial, period.criteria.total));
    await expect(dashboard.locator('[data-implementation]')).toHaveText(percent(period.implementation_percent));
    await expect(dashboard.locator('.implementation-headline .insight-caption')).toHaveText('Ganz oder teilweise umgesetzt');
    await expect(dashboard.locator('.implementation-headline > small')).toHaveText(`${number(period.criteria.fulfilled)} ganz · ${number(period.criteria.partial)} teilweise`);
    await expect(dashboard.locator('[data-coverage]')).toHaveText(percent(period.coverage_percent));
    for (const [key, value] of Object.entries({ all: period.laws.total, supporting: period.laws.supporting, opposing: period.laws.opposing, mixed: period.laws.mixed })) {
      await expect(dashboard.locator(`[data-law-total="${key}"]`)).toHaveText(number(value));
      if (key !== 'all') {
        await expect(dashboard.locator(`[data-law-percent="${key}"]`)).toHaveText(percent(share(value, period.laws.total)));
        await expect(dashboard.locator(`.law-kpi.${key} > small`)).toHaveText(`${number(value)} von ${number(period.laws.total)} belegten Gesetzen`);
      }
    }
    await fitsViewport(page);
    for (const anchor of ['bilanz', 'zeitverlauf', 'gesetzeswirkung', 'kriterien']) {
      await expect(page.locator(`[id="${anchor}"]`)).toHaveCount(1);
      await expect(page.locator(`[id="${anchor}"]`)).toBeVisible();
    }
  }
  expect(errors).toEqual([]);
});

test('overview cards lead with fully or partially implemented percentages on both overviews', async ({ page, request }) => {
  const { programs } = await (await request.get('/api/v1/sources/bundestag-21.json')).json();
  const exports = await Promise.all(programs.map(async ({ party_id: id }: { party_id: string }) => ({ id, ...await partyExport(request, id) })));
  for (const route of ['/', '/live/parteien/']) {
    await page.goto(route);
    for (const { id, insights } of exports) {
      for (const period of insights.periods) {
        const card = page.locator(`[data-period-panel="${period.election_year}"] .party-card[href="/live/parteien/${id}/?jahr=${period.election_year}"]`);
        const { fulfilled, partial, total, covered } = period.criteria;
        await expect(card.locator('[data-card-implementation]')).toHaveText(percent(share(fulfilled + partial, total)));
        await expect(card.locator('.metric-caption')).toHaveText(total ? 'Ganz oder teilweise umgesetzt' : 'Noch kein Programm importiert');
        await expect(card.locator('.card-implementation-counts')).toHaveText(`${number(fulfilled + partial)} von ${number(total)} Kriterien · ${number(fulfilled)} ganz · ${number(partial)} teilweise`);
        await expect(card.locator('.card-coverage')).toHaveText(`${percent(share(covered, total))} mit Gesetzesbelegen · ${number(covered)} von ${number(total)}`);
      }
    }
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await fitsViewport(page);
    }
  }
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
  await panel.locator('.implementation-headline [data-criteria-filter]').click();
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
  for (const topic of period.topics) {
    expect(topic.implementation_percent).toBe(share(topic.fulfilled + topic.partial, topic.total));
    await expect(panel.locator(`[data-topic-insight="${topic.topic}"] .topic-insight-percent > strong`)).toHaveText(percent(topic.implementation_percent));
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

test('chart replaces the separate law ranking and markers open the biggest jumps', async ({ page, request }) => {
  const { period, panel } = await openParty(page, request);
  await expect(panel.locator('[data-law-highlights]')).toHaveCount(0);
  await expect(panel.getByRole('heading', { name: 'Welche Gesetze bewegen am meisten?' })).toHaveCount(0);
  const timeline = panel.locator('.timeline-card');
  await expect(timeline.getByRole('heading', { name: 'Belege über Zeit' })).toBeVisible();
  await expect(timeline.locator('path[data-score]')).toHaveCount(4);
  const expectedJumps = [...period.law_effects]
    .sort((a, b) => b.evidence.length - a.evidence.length || a.published_at.localeCompare(b.published_at) || a.id.localeCompare(b.id))
    .slice(0, 3).map(law => ({ date: law.published_at, new_evidence: law.evidence.length,
      newly_covered: law.newly_covered, law_ids: [law.id] }));
  expect(period.timeline_jumps).toEqual(expectedJumps);
  await expect(timeline.locator('[data-jump-marker]')).toHaveCount(expectedJumps.length);
  const markers = await timeline.locator('[data-jump-marker]').evaluateAll(items => items.map(item => {
    const { left, right, top, bottom } = item.getBoundingClientRect();
    return { left, right, top, bottom };
  }));
  for (let i = 0; i < markers.length; i++) for (let j = i + 1; j < markers.length; j++) {
    const a = markers[i], b = markers[j];
    expect(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top).toBe(true);
  }
  for (const [index, point] of expectedJumps.entries()) {
    const marker = timeline.locator('[data-jump-marker]').nth(index);
    const detail = timeline.locator('[data-timeline-jump]').nth(index);
    await marker.focus();
    await page.keyboard.press('Enter');
    await expect(detail).toHaveAttribute('open', '');
    await expect(detail.locator(':scope > summary')).toBeFocused();
    await expect(detail.locator(':scope > summary')).toContainText(`+${number(point.new_evidence)}`);
    expect(await detail.locator('[data-jump-law]').evaluateAll(items => items.map(item => item.getAttribute('data-jump-law')))).toEqual(point.law_ids);
  }
  await panel.locator('.law-kpi.opposing').click();
  expect(new URL(page.url()).hash).toBe('#gesetzeswirkung');
  await expect(timeline.locator('#gesetzeswirkung')).toBeVisible();
  await fitsViewport(page);
});

test('law evidence opens the exact criterion and original-law evidence', async ({ page, request }) => {
  const { period, panel } = await openParty(page, request);
  const point = period.timeline_jumps[0];
  const law = period.law_effects.find(law => law.id === point.law_ids[0])!;
  const evidence = law.evidence[0];
  await panel.locator('[data-jump-marker]').first().click();
  const card = panel.locator(`[data-jump-law="${law.id}"]`);
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

test('timeline exposes exact publication events and a single zero baseline without inventing historical fulfilment', async ({ page, request }) => {
  const { period, panel } = await openParty(page, request, 'linke');
  const timeline = panel.locator('.timeline-card');
  await expect(timeline.getByRole('img')).toHaveAccessibleName(`Gestapelte Gesetzesbelege nach Wirkung für Programm ${period.election_year}`);
  await expect(timeline.getByRole('img')).toHaveAccessibleDescription(/Keine historische Umsetzungsquote/);
  await expect(timeline.getByRole('img')).toHaveAccessibleDescription(/Gemischte Belege \(0\) zählen zur Gesamtzahl/);
  await expect(timeline.locator('figcaption')).toContainText('keine historische Umsetzungsquote');
  await expect(timeline.locator('figcaption')).toContainText('Gemischte Belege (0) zählen zur Gesamtzahl, werden aber nicht als Unterstützung oder Gegenwirkung dargestellt.');
  await expect(timeline.locator('path[data-score="0"], .chart-mixed-label')).toHaveCount(0);
  await expect(timeline.locator('.chart-baseline')).toHaveCount(1);
  await expect(timeline.locator('[data-zero-label]')).toHaveCount(1);
  await expect(timeline.locator('[data-zero-label]')).toHaveText('0');
  await expect(timeline.locator('.chart-zero-baseline')).toHaveCount(1);
  const zero = Number(await timeline.locator('.chart-zero-baseline').getAttribute('y1'));
  expect(zero).toBe(213);
  for (const score of [2, 1, -2, -1]) {
    const path = (await timeline.locator(`path[data-score="${score}"]`).getAttribute('d'))!;
    const ys = [...path.matchAll(/(?:M|L)\d+\.\d+ (\d+\.\d+)|V(\d+\.\d+)/g)].map(match => Number(match[1] ?? match[2]));
    expect(ys.length).toBeGreaterThan(0);
    expect(ys.every(y => score > 0 ? y <= zero : y >= zero)).toBe(true);
  }
  for (const point of period.timeline.filter(point => point.new_evidence)) {
    expect(point.law_ids.every(id => period.law_effects.find(law => law.id === id)?.published_at === point.date)).toBe(true);
  }
  const last = period.timeline.at(-1)!;
  expect(last.covered).toBe(period.criteria.covered);
  expect(last.opposing).toBeLessThanOrEqual(last.covered);
  expect(Object.values(last.evidence_by_score).reduce((sum, count) => sum + count, 0)).toBe(period.laws.evidence);
  await expect(timeline.locator('.timeline-headline > strong')).toHaveText(`${number(period.laws.evidence)} Belege`);
  await timeline.locator('.timeline-values > summary').click();
  await expect(timeline.locator('tbody tr')).toHaveCount(period.timeline.length);
  const cells = timeline.locator('tbody tr').last().locator('td');
  await expect(cells.nth(0)).toHaveText(number(last.new_evidence));
  for (const [index, score] of ([2, 1, -2, -1, 0] as const).entries()) {
    await expect(cells.nth(index + 1)).toHaveText(number(last.evidence_by_score[score]));
    await expect(timeline.locator('.chart-legend > span').nth(index)).toContainText(number(last.evidence_by_score[score]));
  }
  await expect(cells.nth(6)).toHaveText(number(last.covered));
  await expect(cells.nth(7)).toHaveText(percent(period.coverage_percent));
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
    await expect(panel.locator('[data-law-highlights]')).toHaveCount(0);
    await expect(panel.locator('[data-timeline-jump]:visible')).toHaveCount(period.timeline_jumps.length);
    await panel.locator('.timeline-values > summary').click();
    await expect(panel.locator('.timeline-table tbody a')).toHaveCount(period.laws.total);
    const jump = panel.locator('[data-timeline-jump]').first();
    await jump.locator(':scope > summary').click();
    await expect(jump.locator('[data-jump-law]:visible')).toHaveCount(1);
    await expect(panel.locator('[data-topic-insight]:visible')).toHaveCount(period.topics.length);
    await expect(panel.locator('.criterion-row:visible')).toHaveCount(period.criteria.total);
    await expect(panel.locator('[data-topic-more]')).toBeHidden();
    await expect(panel.locator('noscript .notice')).toBeVisible();
    await expect(panel.locator('noscript .notice')).toContainText('Alle Kriterien sind darunter vollständig lesbar');
    await fitsViewport(page);
  });
});
