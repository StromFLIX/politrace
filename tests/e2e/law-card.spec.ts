import { test, expect } from '@playwright/test';

test('law cards keep party links collapsed and voting visible at a glance', async ({ page }) => {
  await page.goto('/live/aktivitaet/');
  const card = page.locator('.activity-card').filter({ has: page.locator('.party-link-group') }).first();
  const groups = card.locator('.party-link-group');
  expect(await groups.count()).toBeGreaterThan(0);
  await expect(card.locator('.activity-card-main > p')).toHaveCount(0);
  const summaries = await groups.locator('summary').allTextContents();
  expect(new Set(summaries).size).toBe(summaries.length);
  await expect(groups.first()).not.toHaveAttribute('open');
  await groups.first().locator('summary').click();
  await expect(groups.first().locator('li a').first()).toBeVisible();
  await expect(groups.first().locator('li a').first()).toHaveAttribute('href', /\/kriterien\/.*#/);
  await groups.first().locator('summary').click();
  await expect(groups.first().locator('li a').first()).not.toBeVisible();

  const voting = page.locator('.card-votes').first();
  await expect(voting).toBeVisible();
  await expect(voting.locator('.vote-heading').first()).toHaveText(/Schlussabstimmung/);
  await expect(voting.locator('.vote-group').first()).toHaveAttribute('aria-label', /: /);
  await expect(voting.locator('.vote-group').first().locator('.vote-position')).toBeVisible();
  await expect(voting.locator('.vote-group').first()).toHaveAttribute('href', /\/gesetze\/.*#/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('activity shows provisional final votes and links to the same evidence as law details', async ({ page }) => {
  await page.goto('/live/aktivitaet/');
  for (const [lawId, count] of [['bgbl-1-2026-314', 5], ['bgbl-1-2026-307', 5], ['bgbl-1-2026-304', 2]] as const) {
    const card = page.locator('.activity-card').filter({ has: page.locator(`h2 a[href="/live/gesetze/${lawId}/"]`) });
    await expect(card.locator('.vote-heading')).toContainText('Schlussabstimmung');
    await expect(card.locator('.vote-warning')).toContainText('Vorläufige Gesetzeszuordnung');
    await expect(card.locator('.vote-group')).toHaveCount(count);
    await expect(card).not.toContainText('Stimmverhalten offen');
    const voteId = await card.locator('.card-vote').getAttribute('data-vote-id');
    await expect(card.locator('.vote-heading')).toHaveAttribute('href', `/live/gesetze/${lawId}/#${voteId}`);
    await card.locator('.vote-heading').click();
    await expect(page.locator(`[id="${voteId}"]`)).toContainText('Schlussabstimmung');
    await expect(page.locator(`[id="${voteId}"] tbody tr`)).toHaveCount(count);
    await page.goto('/live/aktivitaet/');
  }
  const missing = page.locator('.activity-card').filter({ has: page.locator('h2 a[href="/live/gesetze/bgbl-1-2026-309/"]') });
  await expect(missing.locator('.vote-heading')).toHaveText('Stimmverhalten offen');
  await expect(missing.locator('.vote-group')).toHaveCount(0);
});
