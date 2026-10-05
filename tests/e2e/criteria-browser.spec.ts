import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

const partyRoute = '/live/parteien/linke/';
const visibleRows = (page: Page) => page.locator('.criterion-row:visible');
const topPages = (page: Page) => page.getByRole('navigation', { name: 'Kriterienseiten oben' });
const bottomPages = (page: Page) => page.getByRole('navigation', { name: 'Kriterienseiten unten' });
const hrefs = (page: Page) => visibleRows(page).evaluateAll(rows => rows.map(row => row.getAttribute('href')));

async function waitForBrowser(page: Page) {
  await expect(page.getByRole('combobox', { name: 'Kriterien pro Seite' })).toBeVisible();
}

test('numbered pages replace rows, reach the final result, and survive refresh and history', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${partyRoute}?jahr=2025&source=bookmark`);
  await waitForBrowser(page);
  const total = await page.locator('.criterion-row').count();
  const pages = Math.ceil(total / 20);
  const first = await hrefs(page);
  expect(first).toHaveLength(20);
  await expect(topPages(page).getByRole('button', { name: 'Vorherige Seite' })).toBeDisabled();
  await expect(topPages(page).locator('[aria-current="page"]')).toHaveText('1');
  await topPages(page).getByRole('button', { name: 'Nächste Seite' }).click();
  const second = await hrefs(page);
  expect(second).toHaveLength(20);
  expect(second.every(href => !first.includes(href))).toBe(true);
  expect(new URL(page.url()).searchParams.get('source')).toBe('bookmark');
  expect(new URL(page.url()).searchParams.get('jahr')).toBe('2025');
  expect(new URL(page.url()).searchParams.get('seite')).toBe('2');
  await expect(page.locator('[data-results-start]')).toBeFocused();
  await page.reload();
  await waitForBrowser(page);
  expect(await hrefs(page)).toEqual(second);
  await topPages(page).getByRole('button', { name: `Seite ${pages}`, exact: true }).click();
  await expect(visibleRows(page)).toHaveCount(total % 20 || 20);
  await expect(topPages(page).getByRole('button', { name: 'Nächste Seite' })).toBeDisabled();
  await expect(bottomPages(page).getByRole('button', { name: 'Nächste Seite' })).toBeDisabled();
  await expect(page.locator('[data-result-count]')).toContainText(`${(total - (total % 20 || 20) + 1).toLocaleString('de-DE')}–${total.toLocaleString('de-DE')} von ${total.toLocaleString('de-DE')}`);
  await page.goBack();
  await expect(topPages(page).locator('[aria-current="page"]')).toHaveText('2');
  expect(await hrefs(page)).toEqual(second);
  await page.goForward();
  await expect(topPages(page).locator('[aria-current="page"]')).toHaveText(String(pages));
  await bottomPages(page).getByRole('button', { name: 'Vorherige Seite' }).click();
  await expect(topPages(page).locator('[aria-current="page"]')).toHaveText(String(pages - 1));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/criteria-pagination-${testInfo.project.name}.png` });
  expect(errors).toEqual([]);
});

test('topic drill-down uses the full topic and preserves honest progress through list filters', async ({ page }, testInfo) => {
  await page.goto(`${partyRoute}?seite=3`);
  await waitForBrowser(page);
  const card = page.locator('[data-topic-link="gesundheit"]');
  const statsBefore = await card.locator('[data-topic-status], [data-topic-total], [data-topic-covered]').allTextContents();
  const expected = await page.locator('.criterion-row[data-topic~="gesundheit"]').count();
  await expect(card.locator('[data-topic-total]')).toHaveText(expected.toLocaleString('de-DE'));
  await card.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('combobox', { name: 'Thema', exact: true })).toHaveValue('gesundheit');
  await expect(page.locator('[data-results-start]')).toBeFocused();
  await expect(visibleRows(page)).toHaveCount(Math.min(20, expected));
  expect(new URL(page.url()).searchParams.has('seite')).toBe(false);
  expect(new URL(page.url()).searchParams.get('thema')).toBe('gesundheit');
  expect(await visibleRows(page).evaluateAll(rows => rows.every(row => row.getAttribute('data-topic')?.split(' ').includes('gesundheit')))).toBe(true);
  await page.getByRole('combobox', { name: 'Status', exact: true }).selectOption('fulfilled');
  expect(await card.locator('[data-topic-status], [data-topic-total], [data-topic-covered]').allTextContents()).toEqual(statsBefore);
  await page.getByRole('searchbox').fill('unfindbarerbegriffxyz');
  await expect(page.getByRole('heading', { name: 'Keine passenden Kriterien' })).toBeVisible();
  await expect(topPages(page)).toBeHidden();
  await expect(page.locator('[data-filter-list]')).toBeHidden();
  expect(await card.locator('[data-topic-status], [data-topic-total], [data-topic-covered]').allTextContents()).toEqual(statsBefore);
  await page.getByRole('button', { name: 'Filter zurücksetzen' }).click();
  await expect(visibleRows(page)).toHaveCount(20);
  await expect(page.getByRole('searchbox')).toHaveValue('');
  await expect(page.getByRole('combobox', { name: 'Thema', exact: true })).toHaveValue('');
  await page.locator('[data-show-topics]').click();
  await expect(page.locator('[data-topic-overview]')).toHaveAttribute('open');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/criteria-topics-${testInfo.project.name}.png` });
});

test('page size, search and topic/status changes reset the page, not other filters', async ({ page }) => {
  await page.goto(`${partyRoute}?thema=gesundheit&status=unassessed&seite=2&jahr=2025`);
  await waitForBrowser(page);
  await expect(topPages(page).locator('[aria-current="page"]')).toHaveText('2');
  await page.getByRole('combobox', { name: 'Kriterien pro Seite' }).selectOption('50');
  await expect(visibleRows(page)).toHaveCount(50);
  expect(new URL(page.url()).searchParams.get('pro_seite')).toBe('50');
  expect(new URL(page.url()).searchParams.has('seite')).toBe(false);
  await expect(page.getByRole('combobox', { name: 'Thema', exact: true })).toHaveValue('gesundheit');
  await expect(page.getByRole('combobox', { name: 'Status', exact: true })).toHaveValue('unassessed');
  await topPages(page).getByRole('button', { name: 'Nächste Seite' }).click();
  await page.getByRole('searchbox').fill('Pflege');
  expect(new URL(page.url()).searchParams.has('seite')).toBe(false);
  expect(await visibleRows(page).count()).toBeGreaterThan(0);
  expect(await visibleRows(page).count()).toBeLessThanOrEqual(50);
  await page.reload();
  await waitForBrowser(page);
  await expect(page.getByRole('searchbox')).toHaveValue('Pflege');
  await expect(page.getByRole('combobox', { name: 'Kriterien pro Seite' })).toHaveValue('50');
  await page.getByRole('combobox', { name: 'Thema', exact: true }).selectOption('arbeit');
  expect(new URL(page.url()).searchParams.has('seite')).toBe(false);
  await expect(page.getByRole('searchbox')).toHaveValue('Pflege');
});

test('cross-party topic counts follow party selection, not the current page or search', async ({ page }) => {
  await page.goto('/live/kriterien/?partei=spd&pro_seite=50&seite=2');
  await waitForBrowser(page);
  await expect(page.locator('[data-topic-scope]')).toHaveText('SPD');
  const card = page.locator('[data-topic-link="arbeit"]');
  const expected = await page.locator('.criterion-row[data-party="spd"][data-topic~="arbeit"]').count();
  await expect(card.locator('[data-topic-total]')).toHaveText(expected.toLocaleString('de-DE'));
  await expect(visibleRows(page)).toHaveCount(50);
  expect(await visibleRows(page).evaluateAll(rows => rows.every(row => row.getAttribute('data-party') === 'spd'))).toBe(true);
  await page.getByRole('combobox', { name: 'Partei', exact: true }).selectOption('linke');
  await expect(page.locator('[data-topic-scope]')).toHaveText('Die Linke');
  expect(new URL(page.url()).searchParams.has('seite')).toBe(false);
  const linkeCount = await page.locator('.criterion-row[data-party="linke"][data-topic~="arbeit"]').count();
  await expect(card.locator('[data-topic-total]')).toHaveText(linkeCount.toLocaleString('de-DE'));
  const before = await card.textContent();
  await page.getByRole('searchbox').fill('Pflege');
  await page.getByRole('combobox', { name: 'Status', exact: true }).selectOption('partial');
  expect(await card.textContent()).toBe(before);
  const href = new URL((await card.getAttribute('href'))!, page.url());
  expect(href.searchParams.get('partei')).toBe('linke');
  expect(href.searchParams.get('q')).toBe('Pflege');
  expect(href.searchParams.get('status')).toBe('partial');
  expect(href.searchParams.get('pro_seite')).toBe('50');
  expect(href.searchParams.has('seite')).toBe(false);
  await page.getByRole('combobox', { name: 'Partei', exact: true }).selectOption('fdp');
  await expect(page.locator('[data-topic-link]:visible')).toHaveCount(0);
  await expect(page.locator('[data-no-topics]')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Keine passenden Kriterien' })).toBeVisible();
  await expect(page.locator('main')).not.toContainText('NaN');
});

test('bad URL values are sanitized and oversized page numbers clamp to the last page', async ({ page }) => {
  await page.goto(`${partyRoute}?seite=999999&pro_seite=500&thema=unknown&status=invalid&jahr=2025`);
  await waitForBrowser(page);
  const total = await page.locator('.criterion-row').count();
  expect(new URL(page.url()).searchParams.get('seite')).toBe(String(Math.ceil(total / 20)));
  expect(new URL(page.url()).searchParams.get('jahr')).toBe('2025');
  expect(new URL(page.url()).searchParams.has('thema')).toBe(false);
  expect(new URL(page.url()).searchParams.has('status')).toBe(false);
  expect(new URL(page.url()).searchParams.has('pro_seite')).toBe(false);
  await expect(topPages(page).getByRole('button', { name: 'Nächste Seite' })).toBeDisabled();
  await page.goto(`${partyRoute}?seite=-3&pro_seite=not-a-number`);
  await waitForBrowser(page);
  await expect(topPages(page).locator('[aria-current="page"]')).toHaveText('1');
  await expect(visibleRows(page)).toHaveCount(20);
  expect(new URL(page.url()).searchParams.has('seite')).toBe(false);
});

test('hidden programme years do not change the active page; year switches and history restore correctly', async ({ page, request }) => {
  // Browser-only fixture: exercise a second period without publishing fictional data.
  const html = await (await request.get(partyRoute)).text();
  const fixture = await page.evaluate(source => {
    const doc = new DOMParser().parseFromString(source, 'text/html');
    const panel = doc.querySelector('[data-period-panel="2025"]')!;
    const previous = panel.cloneNode(true) as HTMLElement;
    previous.dataset.periodPanel = '2021'; previous.hidden = true;
    previous.querySelectorAll('.criterion-row').forEach((row, i) => { if (i >= 5) row.remove(); });
    panel.insertAdjacentHTML('afterend', previous.outerHTML.replaceAll('kriterien-2025', 'kriterien-2021'));
    const option = doc.createElement('option'); option.value = '2021'; option.textContent = 'Bundestagswahl 2021';
    doc.querySelector('[data-period-select]')!.append(option);
    return `<!doctype html>${doc.documentElement.outerHTML}`;
  }, html);
  await page.route(`**${partyRoute}*`, route => route.fulfill({ contentType: 'text/html', body: fixture }));
  await page.goto(`${partyRoute}?jahr=2025&seite=3`);
  const current = page.locator('[data-period-panel="2025"]');
  const previous = page.locator('[data-period-panel="2021"]');
  await expect(current.locator('.criterion-row:visible')).toHaveCount(20);
  await expect(current.locator('[data-pagination]').first().locator('[aria-current="page"]')).toHaveText('3');
  expect(new URL(page.url()).searchParams.get('seite')).toBe('3');
  await page.getByRole('combobox', { name: 'Programmjahr' }).selectOption('2021');
  await expect(previous.locator('.criterion-row:visible')).toHaveCount(5);
  await expect(current).toBeHidden();
  expect(new URL(page.url()).searchParams.has('seite')).toBe(false);
  await page.goBack();
  await expect(current).toBeVisible();
  await expect(current.locator('[data-pagination]').first().locator('[aria-current="page"]')).toHaveText('3');
  expect(new URL(page.url()).searchParams.get('seite')).toBe('3');
});

test.describe('without JavaScript', () => {
  test.use({ javaScriptEnabled: false });
  test('all eligible criteria and full topic counts remain readable', async ({ page, request }) => {
    const party = await (await request.get('/api/v1/live/parties/linke.json')).json();
    const total = party.statistics.find((stats: { election_year: number }) => stats.election_year === 2025).total;
    await page.goto(partyRoute);
    await expect(visibleRows(page)).toHaveCount(total);
    // SSR avoids a full-list layout flash; the no-JS stylesheet reveals those rows.
    await expect(page.locator('.criterion-row[hidden]')).toHaveCount(Math.max(0, total - 20));
    await expect(page.locator('[data-pagination]:visible')).toHaveCount(0);
    await expect(page.locator('noscript .notice')).toContainText('vollständig lesbar');
    const card = page.locator('[data-topic-link="gesundheit"]');
    const expected = await page.locator('.criterion-row[data-topic~="gesundheit"]').count();
    await expect(card.locator('[data-topic-total]')).toHaveText(expected.toLocaleString('de-DE'));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
});
