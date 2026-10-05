import { test, expect } from '@playwright/test';

const programme = '/live/programme/gruene-2025/';
const retiredViews = '[data-program-reader], [data-evidence-edition], [data-exact-source], [data-law-text], .law-evidence';

async function openNavigation(page: import('@playwright/test').Page) {
  const nav = page.locator('.document-navigation');
  if (!(await nav.evaluate((element: HTMLDetailsElement) => element.open))) await nav.locator(':scope > summary').click();
}

test('programme has only the OCR reader, in PDF page order, on both screen sizes', async ({ page, request }, testInfo) => {
  const edition = await (await request.get('/api/v1/live/readings/gruene-2025.json')).json();
  await page.goto(programme);
  await expect(page.locator('[data-document-reader]')).toHaveCount(1);
  await expect(page.locator(retiredViews)).toHaveCount(0); // Removed, not merely hidden.
  expect(await page.locator('[data-reading-page]').evaluateAll(nodes => nodes.map(n => n.id)))
    .toEqual(edition.pages.map((p: { number: number }) => `reading-page-${p.number}`));
  expect(await page.locator('.document-prose strong').count()).toBeGreaterThan(0);
  expect(await page.locator('.document-prose h1, .document-prose h2, .document-prose img, .document-prose script').count()).toBe(0);
  expect(await page.locator('.document-prose').first().evaluate(node => getComputedStyle(node).fontSize)).toMatch(/1[8-9]px/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/programme-reader-${testInfo.project.name}.png` });
  await openNavigation(page);
  const link = page.getByRole('navigation', { name: 'Inhalt der Lesefassung' }).locator('a').nth(5);
  const href = await link.getAttribute('href');
  await link.click();
  await expect(page.locator(href!)).toHaveAttribute('open');
  await page.evaluate(() => document.fonts.ready);
  const headerHeight = (await page.locator('.site-header').boundingBox())!.height;
  await expect.poll(async () => (await page.locator(`${href} > summary`).boundingBox())?.y ?? -1).toBeGreaterThanOrEqual(headerHeight);
  if (testInfo.project.name === 'mobile') await expect(page.locator('.document-navigation')).not.toHaveAttribute('open');
  await page.screenshot({ path: `test-results/programme-page-${testInfo.project.name}.png` });
});

test('OCR search, criterion filter, URL restoration and no-result reset work', async ({ page, request }) => {
  const { items: criteria } = await (await request.get('/api/v1/live/criteria.json')).json();
  const count = new Set(criteria.filter((c: { program_id: string }) => c.program_id === 'gruene-2025').map((c: { reference: { page: number } }) => c.reference.page)).size;
  await page.goto(programme);
  await openNavigation(page);
  await page.getByRole('checkbox', { name: 'Nur Seiten mit Kriterien' }).check();
  await expect(page.locator('[data-reading-page]:visible')).toHaveCount(count);
  expect(page.url()).toContain('criteria=1');
  await page.getByRole('searchbox', { name: 'In der Lesefassung suchen' }).fill('Glasfaser');
  const matches = await page.locator('[data-reading-page]:visible').count();
  expect(matches).toBeGreaterThan(0);
  expect(matches).toBeLessThanOrEqual(count);
  await page.reload();
  await openNavigation(page);
  await expect(page.getByRole('searchbox', { name: 'In der Lesefassung suchen' })).toHaveValue('Glasfaser');
  await expect(page.locator('[data-reading-page]:visible')).toHaveCount(matches);
  await page.getByRole('searchbox', { name: 'In der Lesefassung suchen' }).fill('<script>alert(1)</script>');
  await expect(page.getByRole('heading', { name: 'Keine passende Textstelle gefunden.' })).toBeVisible();
  await expect(page.locator('[data-reading-count]')).toContainText('0 von');
  await page.getByRole('button', { name: 'Alle Seiten anzeigen' }).click();
  await expect(page.getByRole('searchbox', { name: 'In der Lesefassung suchen' })).toHaveValue('');
  expect(new URL(page.url()).search).toBe('');
  await expect(page.locator('[data-reading-page][hidden]')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('old paragraph and source-disclosure fragments reveal the OCR page without rewriting evidence', async ({ page, request }) => {
  const source = await (await request.get('/api/v1/live/programs/gruene-2025/tree.json')).json();
  const leaf = source.leaves[1];
  const markdown = await (await request.get(source.markdown)).text();
  expect(markdown).toContain(leaf.reference.quote);
  for (const fragment of [leaf.id, `${leaf.id}-source`]) {
    await page.goto(`${programme}?q=unfindbarerbegriff&criteria=1#${fragment}`);
    const readingPage = page.locator(`#reading-page-${leaf.reference.page}`);
    await expect(readingPage).toHaveAttribute('open');
    await expect(readingPage.locator('[data-reading-citation]')).toBeVisible();
    expect(new URL(page.url()).search).toBe('');
    await expect(page.locator(retiredViews)).toHaveCount(0);
    await expect(readingPage.locator('.document-source-links a').first()).toHaveAttribute('href', new RegExp(`#page=${leaf.reference.page}$`));
    await page.evaluate(() => document.fonts.ready);
    const headerHeight = (await page.locator('.site-header').boundingBox())!.height;
    await expect.poll(async () => (await readingPage.locator(':scope > summary').boundingBox())?.y ?? -1).toBeGreaterThanOrEqual(headerHeight);
  }
});

test('page criteria round-trip through unchanged exact quotes to the OCR reader', async ({ page, request }) => {
  const { items } = await (await request.get('/api/v1/live/criteria.json')).json();
  const criterion = items.find((c: { program_id: string }) => c.program_id === 'gruene-2025');
  const href = `${programme}#reading-page-${criterion.reference.page}`;
  await page.goto(href);
  await page.locator(':target [data-reading-criteria] > summary').click();
  const link = page.locator(`:target [data-criterion-id="${criterion.id}"]`);
  await expect(link).toHaveAttribute('href', `/live/kriterien/${criterion.id}/`);
  await link.click();
  await expect(page.getByRole('heading', { name: criterion.title, exact: true })).toBeVisible();
  expect(await page.locator('.evidence-box blockquote').first().textContent()).toBe(criterion.reference.quote);
  await expect(page.getByRole('link', { name: 'Im Programm lesen' })).toHaveAttribute('href', href);
  await page.getByRole('link', { name: 'Im Programm lesen' }).click();
  await expect(page.locator(':target')).toHaveAttribute('data-reading-page');
  await expect(page.locator(':target .document-prose')).toBeVisible();
});

test('printing includes every OCR page once and restores filtered/collapsed states', async ({ page, request }) => {
  const edition = await (await request.get('/api/v1/live/readings/gruene-2025.json')).json();
  await page.goto(`${programme}?q=Glasfaser&criteria=1`);
  const displayedBefore = await page.locator('[data-reading-page]:visible').count();
  expect(displayedBefore).toBeGreaterThan(0);
  expect(displayedBefore).toBeLessThan(edition.page_count);
  const urlBefore = page.url();
  const disclosureStates = () => page.locator('[data-reading-page]')
    .evaluateAll(nodes => nodes.map(n => (n as HTMLDetailsElement).open));
  const statesBefore = await disclosureStates();
  await page.evaluate(() => {
    window.dispatchEvent(new Event('beforeprint'));
    window.dispatchEvent(new Event('beforeprint'));
  });
  await expect(page.locator('[data-reading-page]:visible')).toHaveCount(edition.page_count);
  expect((await disclosureStates()).every(Boolean)).toBe(true);
  await expect(page.locator('[data-reading-empty]')).toBeHidden();
  await expect(page.locator(retiredViews)).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
  await expect(page.locator('[data-reading-page]:visible')).toHaveCount(displayedBefore);
  expect(await disclosureStates()).toEqual(statesBefore);
  expect(page.url()).toBe(urlBefore);
});

test.describe('progressive enhancement', () => {
  test.use({ javaScriptEnabled: false });
  test('OCR pages, criteria and old bookmarks remain accessible without JavaScript', async ({ page, request }) => {
    const program = await (await request.get('/api/v1/live/programs/gruene-2025.json')).json();
    const leaf = program.leaves.at(-2);
    await page.goto(`${programme}#${leaf.id}`);
    const readingPage = page.locator(`#reading-page-${leaf.reference.page}`);
    await expect(readingPage.locator(':scope > summary')).toBeVisible();
    if (!(await readingPage.evaluate((p: HTMLDetailsElement) => p.open))) await readingPage.locator(':scope > summary').click();
    await expect(readingPage.locator('.document-prose')).toBeVisible();
    await expect(page.locator('[data-reading-controls]')).toBeHidden();
    await expect(page.locator(retiredViews)).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
});
