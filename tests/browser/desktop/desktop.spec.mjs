// Smoke checks for the Darius desktop against fictional fixture data. Every test fails
// on an uncaught page error and saves a screenshot for a quick visual review.
import { test as base, expect } from '@playwright/test';

const test = base.extend({
  page: async ({ page }, use, info) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await use(page);
    await page.screenshot({ path: info.outputPath(`${info.project.name}.png`) });
    expect(errors, 'uncaught page errors').toEqual([]);
  },
});
const desktopOnly = info => test.skip(info.project.name !== 'desktop', 'desktop layout');
const phoneOnly = info => test.skip(info.project.name !== 'phone', 'phone layout');
const openProject = page => page.goto('/?app=create&project=p1');
const rail = page => page.getByRole('navigation', { name: 'Apps' });

test('a project opens onto its canvas with Darius present', async ({ page }) => {
  await openProject(page);
  await expect(page.getByRole('region', { name: 'MOSS board workspace' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Start voice conversation' }).first()).toBeAttached();
});

test('every app opens as a window and they all come back after a reload', async ({ page }, info) => {
  desktopOnly(info);
  await openProject(page);
  for (const app of ['Chat', 'Library', 'Ideas', 'Characters', 'Scenes', 'Shots', 'World map', 'Edit', 'Cloud · FLUX 3', 'Trusted workflows', 'Settings']) {
    await rail(page).getByRole('button', { name: app, exact: true }).click();
    await expect(page.getByRole('region', { name: `${app} window` })).toBeVisible();
    await expect(page.locator('.dk-window-error')).toHaveCount(0);
  }
  await page.reload();
  await expect(rail(page)).toBeVisible();
  await expect(page.locator('.dk-window:not([hidden])')).toHaveCount(11);
});

test('a board zooms open and Esc returns to the same view', async ({ page }, info) => {
  desktopOnly(info);
  await openProject(page);
  const stage = page.locator('.moss-stage');
  const before = await stage.getAttribute('data-scale');
  await page.locator('article[data-board-id=b1]').dblclick({ position: { x: 150, y: 200 } });
  await expect(page.getByRole('group', { name: 'Forest gate editor' })).toBeVisible();
  await expect(page).toHaveURL(/board=b1/);
  await page.keyboard.press('Escape'); await page.keyboard.press('Escape');
  await expect(page.locator('.board-zoom-layer')).toHaveCount(0);
  await expect(stage).toHaveAttribute('data-scale', before);
});

test('right-click offers new boards on the canvas and actions on a board', async ({ page }, info) => {
  desktopOnly(info);
  await openProject(page);
  await expect(page.locator('article[data-board-id=b1]')).toBeVisible();
  await page.mouse.click(700, 520, { button: 'right' });
  await expect(page.getByRole('menu', { name: 'Canvas actions' }).getByRole('menuitem', { name: /MOSS board/ })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.locator('article[data-board-id=b1]').click({ button: 'right', position: { x: 150, y: 220 } });
  await expect(page.getByRole('menu', { name: 'Forest gate actions' }).getByRole('menuitem', { name: 'Duplicate' })).toBeVisible();
});

test('Edit shows the saved cut with its clips', async ({ page }, info) => {
  desktopOnly(info);
  await page.goto('/?app=edit&project=p1');
  await expect(page.getByRole('region', { name: 'Project timeline' })).toContainText('3 clips');
  await expect(page.getByRole('button', { name: 'Save new version' })).toBeVisible();
});

test('on a phone, apps open as sheets above the dock', async ({ page }, info) => {
  phoneOnly(info);
  await openProject(page);
  await rail(page).getByRole('button', { name: 'Chat', exact: true }).click();
  const sheet = page.getByRole('region', { name: 'Chat window' });
  await expect(sheet).toBeVisible();
  const box = await sheet.boundingBox();
  expect(box.width).toBeGreaterThan(380);
});

test('the launcher lists projects as tiles', async ({ page }) => {
  await page.goto('/?app=home');
  await expect(page.getByText('Your projects')).toBeVisible();
  await expect(page.locator('.folder-card', { hasText: 'Moss Kingdom' })).toBeVisible();
});

test('notes, frames and several selected boards', async ({ page }, info) => {
  desktopOnly(info);
  await openProject(page);
  await expect(page.getByRole('group', { name: /Frame Scene 1/ })).toBeAttached();
  await page.getByRole('button', { name: 'Add a sticky note' }).click();
  await expect(page.getByRole('textbox', { name: 'Note text' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.locator('article[data-board-id=b1]').click({ position: { x: 150, y: 220 } });
  await page.locator('article[data-board-id=b4]').click({ position: { x: 150, y: 220 }, modifiers: ['Shift'] });
  await expect(page.getByRole('toolbar', { name: '2 boards selected' })).toBeVisible();
  await expect(page.getByRole('progressbar').first()).toBeVisible();
});

test('the command bar opens apps by name', async ({ page }, info) => {
  desktopOnly(info);
  await openProject(page);
  await expect(page.getByRole('region', { name: 'MOSS board workspace' })).toBeVisible();
  await page.keyboard.press('Control+k');
  await page.getByRole('combobox', { name: /Search apps, boards and actions/ }).fill('open the library');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('region', { name: 'Library window' })).toBeVisible();
  await expect(page.getByText('Opened Library.')).toBeVisible();
});

test('on a phone, an opened board fills the screen', async ({ page }, info) => {
  phoneOnly(info);
  await page.goto('/?app=create&project=p1&board=b1');
  const editor = page.getByRole('group', { name: 'Forest gate editor' });
  await expect(editor).toBeVisible();
  const box = await editor.boundingBox();
  expect(box.width).toBeGreaterThan(380);
  expect(box.height).toBeGreaterThan(600);
});
