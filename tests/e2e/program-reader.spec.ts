import { test, expect } from '@playwright/test';

const programme = '/live/programme/gruene-2025/';

async function readerSource(request: import('@playwright/test').APIRequestContext) {
  return (await request.get('/api/v1/live/programs/gruene-2025/tree.json')).json();
}

async function openNavigation(page: import('@playwright/test').Page) {
  const nav = page.locator('[data-reader-navigation]');
  if (!(await nav.evaluate((element: HTMLDetailsElement) => element.open))) await nav.locator(':scope > summary').click();
}

test('programme reader renders Markdown, retains source order and is usable on both screen sizes', async ({ page, request }, testInfo) => {
  const source = await readerSource(request);
  await page.goto(programme);
  await expect(page.getByRole('heading', { name: source.tree.title, exact: true })).toBeVisible();
  await expect(page.locator('[data-reader-passage]')).toHaveCount(source.leaves.length);
  expect(await page.locator('[data-reader-passage]').evaluateAll(nodes => nodes.map(n => n.id)))
    .toEqual(source.leaves.map((leaf: { id: string }) => leaf.id));
  expect(await page.locator('.reader-prose strong').count()).toBeGreaterThan(0);
  expect(await page.locator('.reader-prose h1, .reader-prose h2, .reader-prose img, .reader-prose script').count()).toBe(0);
  expect(await page.locator('.reader-prose').first().evaluate(node => getComputedStyle(node).fontSize)).toMatch(/1[7-8]px/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/programme-reader-${testInfo.project.name}.png` });
  await openNavigation(page);
  await page.getByRole('navigation', { name: 'Kapitel im Wahlprogramm' }).getByRole('link', { name: /Kapitel 2:/ }).click();
  await expect(page.locator(':target > summary h2')).toContainText('Einfach dabei sein');
  await expect(page.locator(':target .program-passage').first().locator('[data-reader-layout]')).not.toHaveAttribute('open');
  await page.evaluate(() => document.fonts.ready);
  const headerHeight = (await page.locator('.site-header').boundingBox())!.height;
  await expect.poll(async () => (await page.locator(':target > summary h2').boundingBox())?.y ?? -1).toBeGreaterThanOrEqual(headerHeight);
  if (testInfo.project.name === 'mobile') await expect(page.locator('[data-reader-navigation]')).not.toHaveAttribute('open');
  await page.screenshot({ path: `test-results/programme-chapter-${testInfo.project.name}.png` });
});

test('programme search, criterion filter, URL restoration and no-result state work', async ({ page, request }) => {
  const { items: criteria } = await (await request.get('/api/v1/live/criteria.json')).json();
  const count = new Set(criteria.filter((c: { program_id: string }) => c.program_id === 'gruene-2025').map((c: { leaf_id: string }) => c.leaf_id)).size;
  await page.goto(programme);
  await openNavigation(page);
  await page.getByRole('checkbox', { name: 'Nur Absätze mit Kriterien' }).check();
  await expect(page.locator('[data-reader-passage]:visible')).toHaveCount(count);
  expect(page.url()).toContain('criteria=1');
  await page.getByRole('searchbox', { name: 'Im Programm suchen' }).fill('Glasfaser');
  const matches = await page.locator('[data-reader-passage]:visible').count();
  expect(matches).toBeGreaterThan(0);
  expect(matches).toBeLessThanOrEqual(count);
  await page.reload();
  await openNavigation(page);
  await expect(page.getByRole('searchbox', { name: 'Im Programm suchen' })).toHaveValue('Glasfaser');
  await expect(page.locator('[data-reader-passage]:visible')).toHaveCount(matches);
  await page.getByRole('searchbox', { name: 'Im Programm suchen' }).fill('<script>alert(1)</script>');
  await expect(page.getByRole('heading', { name: 'Keine passenden Absätze' })).toBeVisible();
  await expect(page.locator('[data-reader-count]')).toContainText('0 von');
  await page.getByRole('button', { name: 'Alle Absätze anzeigen' }).click();
  await expect(page.getByRole('searchbox', { name: 'Im Programm suchen' })).toHaveValue('');
  expect(new URL(page.url()).search).toBe('');
  await expect(page.locator('[data-reader-passage][hidden]')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('source fragments override conflicting filters and preserve exact Markdown citations', async ({ page, request }) => {
  const source = await readerSource(request);
  const first = source.leaves[1]; // A closed front-matter chapter with Markdown headings.
  await page.goto(`${programme}?q=unfindbarerbegriff#${first.id}`);
  await expect(page.locator(':target')).toBeVisible();
  expect(new URL(page.url()).search).toBe('');
  await page.locator(':target > .passage-source > summary').click();
  const raw = page.locator(':target [data-exact-source]');
  await expect(raw).toBeVisible();
  expect(await raw.textContent()).toBe(first.text);
  const pdfLink = page.locator(':target .passage-source-links a').first();
  await expect(pdfLink).toHaveAttribute('href', new RegExp(`#page=${first.reference.page}$`));
  await expect(page.locator(':target .passage-source-links a').nth(1)).toHaveAttribute('href', new RegExp(`#L${first.reference.line_start}$`));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('criterion disclosures link to the same source-backed criteria, not generated replacement IDs', async ({ page, request }) => {
  const { items } = await (await request.get('/api/v1/live/criteria.json')).json();
  const criterion = items.find((c: { program_id: string }) => c.program_id === 'gruene-2025');
  await page.goto(`${programme}#${criterion.leaf_id}`);
  await page.locator(':target [data-reader-criteria] > summary').click();
  const link = page.locator(':target .passage-criteria-list a').filter({ hasText: criterion.title });
  await expect(link).toHaveAttribute('href', `/live/kriterien/${criterion.id}/`);
  await link.click();
  await expect(page.getByRole('heading', { name: criterion.title, exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Absatz im Textbaum' }).click();
  await expect(page.locator(':target')).toContainText(criterion.reference.quote);
});

test('printing includes filtered and collapsed passages, then restores the reader', async ({ page, request }) => {
  const source = await readerSource(request);
  await page.goto(`${programme}?q=Glasfaser&criteria=1`);
  const displayedBefore = await page.locator('[data-reader-passage]:visible').count();
  expect(displayedBefore).toBeGreaterThan(0);
  expect(displayedBefore).toBeLessThan(source.leaves.length);
  const urlBefore = page.url();
  const disclosureStates = () => page.locator('[data-reader-chapter], [data-reader-layout]')
    .evaluateAll(nodes => nodes.map(n => (n as HTMLDetailsElement).open));
  const statesBefore = await disclosureStates();
  await page.evaluate(() => {
    // Repeated beforeprint events must not overwrite the original state.
    window.dispatchEvent(new Event('beforeprint'));
    window.dispatchEvent(new Event('beforeprint'));
  });
  await expect(page.locator('[data-reader-passage]:visible')).toHaveCount(source.leaves.length);
  expect((await disclosureStates()).every(Boolean)).toBe(true);
  await expect(page.locator('[data-reader-empty]')).toBeHidden();
  await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
  await expect(page.locator('[data-reader-passage]:visible')).toHaveCount(displayedBefore);
  expect(await disclosureStates()).toEqual(statesBefore);
  expect(page.url()).toBe(urlBefore);
});

test.describe('progressive enhancement', () => {
  test.use({ javaScriptEnabled: false });
  test('programme and exact sources remain readable without JavaScript', async ({ page }) => {
    await page.goto('/demo/programme/demo-spd-2025/');
    await expect(page.getByRole('navigation', { name: 'Kapitel im Wahlprogramm' })).toBeVisible();
    await expect(page.locator('[data-reader-controls]')).toBeHidden();
    const first = page.locator('[data-reader-passage]').first();
    await expect(first.locator('.reader-prose')).toBeVisible();
    await first.locator('.passage-source > summary').click();
    await expect(first.locator('[data-exact-source]')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
});
