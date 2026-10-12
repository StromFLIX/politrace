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
  await expect(voting.locator('.vote-heading')).toHaveText(/Schlussabstimmung/);
  await expect(voting.locator('.vote-group').first()).toHaveAttribute('aria-label', /: /);
  await expect(voting.locator('.vote-group').first().locator('.vote-position')).toBeVisible();
  await expect(voting.locator('.vote-group').first()).toHaveAttribute('href', /\/gesetze\/.*#/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
