import { expect, test } from '@playwright/test';

test('OCR reading pages retain pagination, correction logs and evidence links', async ({ page, request }, info) => {
  const edition = await (await request.get('/api/v1/live/readings/gruene-2025.json')).json();
  expect(edition.evidence_unchanged).toBe(true);
  expect(edition.review_status).toBe('proposed');
  expect(edition.pages).toHaveLength(edition.page_count);
  const corrected = edition.pages.find((p: { number: number }) => p.number === 12);
  expect(corrected.corrections[0].after).toBe('Russlands');
  await page.goto('/live/programme/gruene-2025/#reading-page-12');
  await expect(page.locator('#reading-page-12')).toHaveAttribute('open');
  await expect(page.locator('#reading-page-12 .document-prose')).toContainText('Angriffskrieg Russlands gegen die Ukraine');
  await expect(page.locator('#reading-page-12 .document-prose')).not.toContainText('Russ- Russlands');
  expect(await page.locator('.document-prose script, .document-prose img').count()).toBe(0);
  await page.screenshot({ path: `test-results/ocr-programme-${info.project.name}.png` });
  await page.locator('#reading-page-12 .document-source-links a').nth(1).click();
  await expect(page.locator(':target')).toBeVisible();
  await expect(page.locator('[data-evidence-edition]')).toHaveAttribute('open');
});

test('OCR search and printing do not lose hidden pages', async ({ page }) => {
  await page.goto('/live/programme/gruene-2025/');
  const nav = page.locator('.document-navigation');
  if (!(await nav.evaluate((el: HTMLDetailsElement) => el.open))) await nav.locator('summary').first().click();
  const search = page.getByRole('searchbox', { name: 'In der Lesefassung suchen' });
  await search.fill('nichtvorhandenertextxyz');
  await expect(page.locator('[data-reading-empty]')).toBeVisible();
  const hidden = await page.locator('[data-reading-page][hidden]').count();
  expect(hidden).toBeGreaterThan(100);
  await page.evaluate(() => { window.dispatchEvent(new Event('beforeprint')); window.dispatchEvent(new Event('beforeprint')); });
  await expect(page.locator('[data-reading-page][hidden]')).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
  await expect(page.locator('[data-reading-page][hidden]')).toHaveCount(hidden);
  await search.fill('Glasfaser');
  expect(await page.locator('[data-reading-page]:visible').count()).toBeGreaterThan(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('AfD archive copy renders the complete contents table without sidecar links', async ({ page, request }, info) => {
  const edition = await (await request.get('/api/v1/live/readings/afd-2025.json')).json();
  expect(edition.page_count).toBe(177);
  expect(edition.retrieved_from).toContain('web.archive.org');
  expect(edition.source_url).toContain('www.afd.de');
  expect(edition.pages.some((p: { markdown: string }) => /\]\(tbl-\d+\./.test(p.markdown))).toBe(false);
  await page.goto('/live/programme/afd-2025/#reading-page-3');
  await expect(page.locator('#reading-page-3 .document-prose table')).toBeVisible();
  await expect(page.locator('#reading-page-3 .document-prose')).toContainText('Soziale Marktwirtschaft');
  expect(await page.locator('.document-prose a[href*="tbl-"]').count()).toBe(0);
  await expect(page.locator('#reading-page-3 .document-source-links a').first()).toHaveAttribute('href', /web\.archive\.org.*#page=3$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/ocr-afd-${info.project.name}.png` });
});

test('real law OCR uses readable headings and fits narrow screens', async ({ page }, info) => {
  await page.goto('/live/gesetze/bgbl-1-2025-173/#reading-page-1');
  await expect(page.locator('.document-reader')).toBeVisible();
  await expect(page.locator('#reading-page-1 .document-prose')).toContainText('Gesetz');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/ocr-law-${info.project.name}.png` });
});
