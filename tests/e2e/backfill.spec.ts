import { test, expect } from '@playwright/test';

for (const id of ['afd-2025', 'cdu-csu-2025', 'gruene-2025', 'linke-2025', 'spd-2025', 'ssw-2025']) {
  test(`${id}: complete leaf audit and working programme/criterion/source links`, async ({ page, request }) => {
    const response = await request.get(`/api/v1/live/programs/${id}.json`);
    test.skip(response.status() === 404, 'This programme checkpoint has not been published yet');
    const program = await response.json();
    await response.dispose();
    expect(program.criteria_extraction).toHaveLength(program.leaves.length);
    expect(new Set(program.criteria_extraction.map((leaf: { leaf_id: string }) => leaf.leaf_id)).size).toBe(program.leaves.length);
    const source = program.criteria_extraction.find((leaf: { criterion_ids: string[] }) => leaf.criterion_ids.length);
    const criterion = await (await request.get(`/api/v1/live/criteria/${source.criterion_ids[0]}.json`)).json();
    await page.goto(`/live/parteien/${program.party_id}/`);
    await expect(page.getByRole('link', { name: /Programm.*lesen/ }).first()).toHaveAttribute('href', `/live/programme/${id}/`);
    await page.goto(`/live/kriterien/${criterion.id}/`);
    await expect(page.getByRole('heading', { name: criterion.title, exact: true })).toBeVisible();
    expect(await page.locator('.evidence-box blockquote').first().textContent()).toBe(criterion.reference.quote);
    await page.getByRole('link', { name: 'Im Programm lesen' }).click();
    const readingPage = page.locator(`#reading-page-${criterion.reference.page}`);
    await expect(readingPage).toHaveAttribute('open');
    await expect(readingPage.locator('.document-prose')).toBeVisible();
    await expect(page.locator('[data-program-reader], [data-evidence-edition], [data-exact-source]')).toHaveCount(0);
    // Every old citation still locates the same PDF page, even though its old view is gone.
    const aliases = await page.locator('[data-source-anchor]').evaluateAll(nodes => Object.fromEntries(nodes.map(n => [n.id, n.closest<HTMLElement>('[data-reading-page]')?.dataset.page])));
    for (const leaf of program.leaves) {
      expect(aliases[leaf.id]).toBe(String(leaf.reference.page));
      expect(aliases[`${leaf.id}-source`]).toBe(String(leaf.reference.page));
    }
    const edition = await (await request.get(`/api/v1/live/readings/${id}.json`)).json();
    await expect(page.locator('[data-reading-page]')).toHaveCount(edition.page_count);
    await expect(page.locator('[data-reading-criterion]')).toHaveCount(program.criteria_extraction.reduce((sum: number, leaf: { criterion_ids: string[] }) => sum + leaf.criterion_ids.length, 0));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
}

test('long law pages stay within the mobile viewport and source fragments open their PDF page', async ({ page, request }) => {
  const response = await request.get('/api/v1/live/laws/bgbl-1-2025-343.json');
  test.skip(response.status() === 404, 'Historical inventory not published yet');
  const law = await response.json();
  await response.dispose();
  const passage = law.passages.at(-1);
  await page.goto(`/live/gesetze/${law.id}/#${passage.id}`);
  const readingPage = page.locator(`#reading-page-${passage.reference.page}`);
  await expect(readingPage).toHaveAttribute('open');
  await expect(readingPage.locator('.document-prose')).toBeVisible();
  await expect(readingPage.locator('[data-reading-citation]')).toBeVisible();
  await expect(page.locator('[data-law-text], .law-evidence')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  const aliases = await page.locator('[data-source-anchor]').evaluateAll(nodes => Object.fromEntries(nodes.map(n => [n.id, n.closest<HTMLElement>('[data-reading-page]')?.dataset.page])));
  for (const source of law.passages) expect(aliases[source.id]).toBe(String(source.reference.page));
  const before = await page.locator('[data-reading-page][open]').count();
  await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
  await expect(page.locator('[data-reading-page]:not([open])')).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
  await expect(page.locator('[data-reading-page][open]')).toHaveCount(before);
});
