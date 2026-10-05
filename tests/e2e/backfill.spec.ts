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
    await page.getByRole('link', { name: 'Absatz im Textbaum' }).click();
    await expect(page.locator(':target')).toContainText(criterion.reference.quote);
    await expect(page.locator(':target')).toBeVisible();
    expect(await page.locator('[data-reader-passage]').count()).toBe(program.leaves.length);
    await page.locator(':target .passage-source > summary').click();
    await expect(page.locator(':target [data-exact-source]')).toContainText(criterion.reference.quote);
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
  await expect(page.locator(':target')).toContainText(passage.text);
  await expect(page.locator(':target')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  const before = await page.locator('.law-page[open]').count();
  await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
  await expect(page.locator('.law-page:not([open])')).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
  await expect(page.locator('.law-page[open]')).toHaveCount(before);
});
