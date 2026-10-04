import { test, expect } from '@playwright/test';

test('landing page follows the configured dataset', async ({ page }) => {
  const { default_dataset: dataset } = await (await page.request.get('/api/v1/index.json')).json();
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /Vom Versprechen/ })).toBeVisible();
  await expect(page.locator('.dataset-banner')).toContainText(dataset === 'demo' ? 'DEMO' : 'LIVE-DATEN');
  await expect(page.getByRole('navigation', { name: 'Hauptnavigation' }).getByRole('link', { name: 'Parteien' }))
    .toHaveAttribute('href', `/${dataset}/parteien/`);
});

test('demo overview labels fictional data and switches periods', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  // This stays a demo test even after the first live manifesto changes the default homepage.
  await page.goto('/demo/parteien/');
  await expect(page.getByRole('heading', { name: /Vom Versprechen/ })).toBeVisible();
  await expect(page.locator('.dataset-banner')).toContainText('Fiktive Programme');
  await expect(page.locator('[data-period-panel="2025"] .party-card')).toHaveCount(7);
  await page.screenshot({ path: `test-results/home-${testInfo.project.name}.png`, fullPage: true });
  await page.locator('[data-period-panel="2025"] [data-period-select]').selectOption('2021');
  await expect(page.locator('[data-period-panel="2021"]')).toBeVisible();
  await expect(page.locator('[data-period-panel="2025"]')).toBeHidden();
  expect(page.url()).toContain('jahr=2021');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('party criteria search, no-results state and deep links work', async ({ page }) => {
  await page.goto('/demo/parteien/spd/');
  const section = page.locator('[data-period-panel="2025"]');
  await section.getByRole('searchbox').fill('Mindestlohn');
  await expect(section.locator('.criterion-row:visible')).toHaveCount(1);
  await section.getByRole('searchbox').fill('nichtvorhandenerbegriff');
  await expect(section.getByRole('heading', { name: 'Keine passenden Kriterien' })).toBeVisible();
  await section.getByRole('searchbox').fill('');
  await section.getByRole('combobox', { name: 'Thema' }).selectOption('wohnen');
  await expect(section.locator('.criterion-row:visible')).toHaveCount(1);
  await section.locator('.criterion-row:visible').click();
  await expect(page.getByRole('heading', { name: 'Mietpreisbremse verlängern', exact: true })).toBeVisible();
  await expect(page.getByText('Der Akzeptanztest', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Kriterium auf GitHub bearbeiten' })).toHaveAttribute('href', /\/edit\/main\/data\/demo\/criteria\//);
  await page.getByRole('link', { name: 'Absatz im Textbaum' }).click();
  await expect(page.locator(':target')).toContainText('Die Mietpreisbremse');
});

test('activity filters and separate vote sources', async ({ page }, testInfo) => {
  await page.goto('/demo/aktivitaet/');
  await page.screenshot({ path: `test-results/activity-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole('combobox', { name: 'Partei', exact: true }).selectOption('spd');
  await expect(page.locator('.activity-card:visible')).toHaveCount(3);
  await page.getByRole('combobox', { name: 'Thema', exact: true }).selectOption('arbeit');
  await expect(page.locator('.activity-card:visible')).toHaveCount(1);
  await page.getByRole('link', { name: 'Gesetz & Belege' }).filter({ visible: true }).click();
  await expect(page.getByRole('heading', { name: 'Wer hat wie abgestimmt?' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'CDU/CSU', exact: true })).toBeVisible();
  await expect(page.getByText('Fiktive Beispielstimmen', { exact: false })).toBeVisible();
});

test('live activity is sourced and does not fabricate vote data', async ({ page }) => {
  await page.goto('/live/aktivitaet/');
  await expect(page.locator('.dataset-banner')).toContainText('LIVE-DATEN');
  const laws = await (await page.request.get('/api/v1/live/laws.json')).json();
  const votes = await (await page.request.get('/api/v1/live/votes.json')).json();
  await expect(page.locator('.activity-card')).toHaveCount(laws.total);
  test.skip(!laws.total, 'No live publications yet');
  const firstId = await page.locator('.activity-card').first().getByRole('link', { name: 'Gesetz & Belege' }).getAttribute('href');
  await page.goto(firstId!);
  const lawId = firstId!.split('/').filter(Boolean).at(-1);
  if (!votes.items.some((v: { law_id: string; review: { status: string } }) => v.law_id === lawId && v.review.status === 'reviewed')) {
    await expect(page.getByText('Keine belegten Abstimmungsdaten hinterlegt.')).toBeVisible();
  }
  await expect(page.getByRole('link', { name: 'Amtliche Veröffentlichung' })).toHaveAttribute('href', /^https:\/\/www.recht.bund.de\//);
  await expect(page.getByRole('heading', { name: 'Verbindungen zu Wahlversprechen' })).toBeVisible();
});

test('API exposes separate datasets, exact text, schemas and real 404s', async ({ request }) => {
  const response = await request.get('/api/v1/demo/criteria.json');
  expect(response.status()).toBe(200);
  const list = await response.json();
  expect(list.dataset).toBe('demo');
  expect(list.items).toHaveLength(32);
  const criterion = list.items[0];
  const programme = await (await request.get(`/api/v1/demo/programs/${criterion.program_id}/tree.json`)).json();
  expect(programme.leaves.some((leaf: { id: string }) => leaf.id === criterion.leaf_id)).toBeTruthy();
  const markdown = await (await request.get(programme.markdown)).text();
  expect(markdown).toContain(criterion.reference.quote);
  const live = await (await request.get('/api/v1/live/criteria.json')).json();
  expect(live.items.every((c: { dataset: string; id: string }) => c.dataset === 'live' && !c.id.startsWith('demo-'))).toBe(true);
  const contract = await (await request.get('/api/v1/schemas/criteria.schema.json')).json();
  expect(contract.additionalProperties).toBe(false);
  expect((await request.get('/api/v1/live/does-not-exist.json')).status()).toBe(404);
});

test('search index UI handles shared URL filters without HTML injection', async ({ page }) => {
  await page.goto('/demo/kriterien/?q=%3Cscript%3Ealert(1)%3C/script%3E');
  await expect(page.getByRole('searchbox')).toHaveValue('<script>alert(1)</script>');
  await expect(page.getByRole('heading', { name: 'Keine passenden Kriterien' })).toBeVisible();
  await page.getByRole('searchbox').fill('');
  await page.getByRole('combobox', { name: 'Partei', exact: true }).selectOption('gruene');
  await expect(page.locator('.criterion-row:visible')).toHaveCount(4);
});
