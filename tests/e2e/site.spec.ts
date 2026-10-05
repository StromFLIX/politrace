import { test, expect } from '@playwright/test';

test('production home has no demo switch or POC branding', async ({ page, request }) => {
  const index = await (await request.get('/api/v1/index.json')).json();
  expect(index.default_dataset).toBe('live');
  expect(index.datasets).toEqual(['/api/v1/live/index.json']);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /Vom Versprechen/ })).toBeVisible();
  await expect(page.locator('.brand').first()).not.toContainText('POC');
  await expect(page.locator('.dataset-banner')).toContainText('QUELLENBASIERTE DATEN');
  await expect(page.locator('.dataset-banner a')).toHaveAttribute('href', '/fortschritt/');
  expect((await request.get('/demo/parteien/')).status()).toBe(404);
  expect((await request.get('/api/v1/demo/index.json')).status()).toBe(404);
});

test('party overview matches live inventory and fits the viewport', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/live/parteien/');
  const parties = await (await page.request.get('/api/v1/live/parties.json')).json();
  await expect(page.locator('[data-period-panel="2025"] .party-card')).toHaveCount(parties.total);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('real party criteria have searchable evidence and Git correction links', async ({ page }) => {
  await page.goto('/live/parteien/spd/');
  const section = page.locator('[data-period-panel="2025"]');
  await section.getByRole('searchbox').fill('nichtvorhandenerbegriffxyz');
  await expect(section.getByRole('heading', { name: 'Keine passenden Kriterien' })).toBeVisible();
  await section.getByRole('searchbox').fill('');
  await section.locator('.criterion-row').first().click();
  await expect(page.getByText('Der Akzeptanztest', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Kriterium auf GitHub bearbeiten' })).toHaveAttribute('href', /\/edit\/main\/data\/live\/criteria\//);
  await page.getByRole('link', { name: 'Im Programm lesen' }).click();
  await expect(page.locator(':target')).toHaveAttribute('data-reading-page');
  await expect(page.locator(':target .document-prose')).toBeVisible();
});

test('live activity does not fabricate voting records', async ({ page }) => {
  await page.goto('/live/aktivitaet/');
  const { counts } = await (await page.request.get('/api/v1/live/index.json')).json();
  const votes = await (await page.request.get('/api/v1/live/votes.json')).json();
  await expect(page.locator('.activity-card')).toHaveCount(counts.laws);
  const href = await page.locator('.activity-card').first().getByRole('link', { name: 'Gesetz & Belege' }).getAttribute('href');
  await page.goto(href!);
  const lawId = href!.split('/').filter(Boolean).at(-1);
  if (!votes.items.some((v: { law_id: string; review: { status: string } }) => v.law_id === lawId && v.review.status === 'reviewed')) {
    await expect(page.getByText('Keine belegten Abstimmungsdaten hinterlegt.')).toBeVisible();
  }
  await expect(page.getByRole('link', { name: 'Amtliche Veröffentlichung' })).toHaveAttribute('href', /^https:\/\/www.recht.bund.de\//);
  await expect(page.getByRole('heading', { name: 'Verbindungen zu Wahlversprechen' })).toBeVisible();
});

test('API exposes source contracts and actual 404s', async ({ request }) => {
  const programs = await (await request.get('/api/v1/live/programs.json')).json();
  expect(programs.total).toBe(6);
  expect(programs.items.every((p: { dataset: string; id: string }) => p.dataset === 'live' && !p.id.startsWith('demo-'))).toBe(true);
  const contract = await (await request.get('/api/v1/schemas/criteria.schema.json')).json();
  expect(contract.additionalProperties).toBe(false);
  expect((await request.get('/api/v1/live/does-not-exist.json')).status()).toBe(404);
  expect((await request.get('/api/v1/live/analyses.json')).status()).toBe(200);
  expect((await request.get('/api/v1/live/analysis.json')).status()).toBe(200);
});

test('source inventory discloses the dated archive coverage', async ({ page, request }) => {
  const catalog = await (await request.get('/api/v1/sources/bundestag-21.json')).json();
  expect(catalog.programs).toHaveLength(6);
  expect(catalog.programs.flatMap((p: { members: string[] }) => p.members)).toHaveLength(7);
  const coverage = await (await request.get('/api/v1/live/coverage.json')).json();
  for (const record of coverage.items) {
    expect(record.official_count).toBe(record.expected_ids.length);
    expect(record.imported_count + record.pending_ids.length).toBe(record.official_count);
    expect(record.complete).toBe(record.pending_ids.length === 0);
  }
  await page.goto('/quellen/');
  await expect(page.getByRole('heading', { name: /Quellen sichtbar machen/ })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'SSW', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('source text and criteria keep their original exact evidence', async ({ page, request }) => {
  const programs = await (await request.get('/api/v1/live/programs.json')).json();
  const program = programs.items[0];
  const tree = await (await request.get(`/api/v1/live/programs/${program.id}/tree.json`)).json();
  const markdown = await (await request.get(tree.markdown)).text();
  for (const leaf of tree.leaves) expect(markdown).toContain(leaf.reference.quote);
  const firstId = program.criteria_extraction.find((leaf: { criterion_ids: string[] }) => leaf.criterion_ids.length)?.criterion_ids[0];
  const criterion = await (await request.get(`/api/v1/live/criteria/${firstId}.json`)).json();
  await page.goto(`/live/kriterien/${criterion.id}/`);
  await expect(page.getByRole('heading', { name: criterion.title, exact: true })).toBeVisible();
  expect(await page.locator('.evidence-box blockquote').first().textContent()).toBe(criterion.reference.quote);
  await page.getByRole('link', { name: 'Im Programm lesen' }).click();
  await expect(page.locator(':target')).toHaveAttribute('id', `reading-page-${criterion.reference.page}`);
  await expect(page.locator(':target .document-prose')).toBeVisible();
});

test('impact proposals keep exact quotes and open the corresponding OCR law page', async ({ page, request }) => {
  const { items: impacts } = await (await request.get('/api/v1/live/impacts.json')).json();
  for (const impact of impacts.slice(0, 8)) {
    const law = await (await request.get(`/api/v1/live/laws/${impact.law_id}.json`)).json();
    const criterion = await (await request.get(`/api/v1/live/criteria/${impact.criterion_id}.json`)).json();
    expect(law.passages.find((p: { id: string }) => p.id === impact.law_passage_id).text).toContain(impact.law_quote);
    expect(criterion.reference.quote).toContain(impact.criterion_quote);
    await page.goto(`/live/gesetze/${law.id}/#${impact.id}`);
    const card = page.locator(`[id="${impact.id}"]`);
    await expect(card).toBeVisible();
    if (impact.review.status === 'proposed') await expect(card).toContainText('KI-Vorschlag, keine Erfüllungsbewertung.');
    await card.locator('h3 a').click();
    await expect(page.getByRole('heading', { name: criterion.title, exact: true })).toBeVisible();
    expect(await page.locator(`[id="${impact.id}"] blockquote`).textContent()).toBe(impact.law_quote);
    await page.locator(`[id="${impact.id}"]`).getByRole('link', { name: 'Gesetzespassage ansehen' }).click();
    const passage = law.passages.find((p: { id: string }) => p.id === impact.law_passage_id);
    await expect(page.locator(':target')).toHaveAttribute('id', `reading-page-${passage.reference.page}`);
    await expect(page.locator(':target .document-prose')).toBeVisible();
    await expect(page.locator('[data-law-text], .law-evidence')).toHaveCount(0);
  }
});

test('URL search values are never rendered as executable HTML', async ({ page }) => {
  await page.goto('/live/kriterien/?q=%3Cscript%3Ealert(1)%3C/script%3E');
  await expect(page.getByRole('searchbox')).toHaveValue('<script>alert(1)</script>');
  await expect(page.getByRole('heading', { name: 'Keine passenden Kriterien' })).toBeVisible();
  await page.getByRole('searchbox').fill('');
  await page.getByRole('combobox', { name: 'Partei', exact: true }).selectOption('ssw');
  await expect(page.locator('.criterion-row:visible')).toHaveCount(100);
  await page.getByRole('button', { name: 'Weitere 100 anzeigen' }).click();
  await expect(page.locator('.criterion-row:visible')).toHaveCount(200);
});

test('public processing page distinguishes OCR, selected pairs and unknowns', async ({ page, request }) => {
  await page.goto('/fortschritt/');
  await expect(page.getByRole('heading', { name: 'Keine unsichtbaren Lücken.' })).toBeVisible();
  await expect(page.getByText(/Nicht ausgewählte Paare bleiben unbekannt/)).toBeVisible();
  await expect(page.getByRole('link', { name: 'Alle Lesefassungen & Seitenhinweise →' })).toBeVisible();
  const readings = await (await request.get('/api/v1/live/readings.json')).json();
  expect(readings.total).toBeGreaterThan(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
