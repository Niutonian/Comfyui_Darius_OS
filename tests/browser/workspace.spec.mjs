import { test, expect } from './fixtures.mjs';

test('creates a project through the project menu', async ({ page, sandbox }) => {
  await page.goto('/?app=home');
  await page.locator('.project-trigger:visible').click();
  await page.locator('.project-menu').getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByRole('textbox', { name: 'Project name', exact: true }).fill('New world');
  await page.locator('.project-form').getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.locator('.project-trigger:visible')).toContainText('New world');
  expect(sandbox.submissions).toHaveLength(0);
});

test('reviews a chat prompt and applies it without rendering', async ({ page, sandbox }) => {
  await page.goto('/?app=talk&project=' + sandbox.project.id);
  await page.getByRole('button', { name: 'Use in board', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Use in board', exact: true });
  await dialog.getByLabel('Destination board').selectOption(sandbox.board.id);
  await dialog.getByLabel('Prompt to apply').fill('Glass flowers under a blue moon');
  await dialog.getByRole('button', { name: 'Replace prompt', exact: true }).click();
  await expect(dialog.getByRole('status')).toHaveText('Prompt added to Garden composition');
  expect(sandbox.transfers).toHaveLength(1);
  expect(sandbox.document.content.globalPrompt).toBe('Glass flowers under a blue moon');
  expect(sandbox.submissions).toHaveLength(0);
});

test('recovers a lost queue acknowledgement and shows the completed board', async ({ page, sandbox }) => {
  sandbox.loseNextReply();
  await page.goto('/?app=create&project=' + sandbox.project.id);
  await page.getByRole('navigation', { name: 'Library sections' }).getByRole('button', { name: 'Canvas', exact: true }).click();
  await page.getByRole('button', { name: 'Generate', exact: true }).first().click();
  await expect.poll(() => sandbox.lookupCount()).toBeGreaterThan(0);
  expect(sandbox.submissions).toHaveLength(1);
  sandbox.complete();
  await expect(page.getByRole('img', { name: 'Garden composition · selected result', exact: true }).first()).toBeVisible();
});

test('fullscreen chat stays readable and can send another turn', async ({ page, sandbox }) => {
  await page.goto('/?app=talk&project=' + sandbox.project.id);
  await page.getByRole('button', { name: 'Fullscreen chat', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Message Darius in fullscreen' });
  await input.fill('Explore the garden further');
  const box = await input.boundingBox(), viewport = page.viewportSize();
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1);
  await page.getByRole('button', { name: 'Send fullscreen message', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Fullscreen conversation' })).toContainText('Let us explore the garden idea.');
  await expect(input).toBeEnabled();
  await page.getByRole('button', { name: 'Close fullscreen voice', exact: true }).click();
  await expect(input).toHaveCount(0);
  expect(sandbox.submissions).toHaveLength(0);
});


test('Qwen Edit opens the shared thumbnail chooser without submitting', async ({ page, sandbox }) => {
 sandbox.configureEdit();
 await page.goto('/?app=create&project=' + sandbox.project.id);
 await page.getByRole('navigation', { name: 'Library sections' }).getByRole('button', { name: 'Canvas', exact: true }).click();
 await page.getByRole('button', { name: /^Open board/ }).first().click();
 await page.getByRole('button', { name: 'Choose image inputs', exact: true }).click();
 const picker = page.getByRole('group', { name: 'Project image inputs' });
 await expect(picker).toBeVisible();
 await picker.getByRole('button', { name: /Synthetic reference/ }).click();
 await expect(picker).toHaveCount(0);
 await expect(page.getByRole('img', { name: 'Image 1', exact: true })).toBeVisible();
 expect(sandbox.submissions).toHaveLength(0);
});


test('video failure opens its saved preview and prepares CPU recovery without rendering', async ({ page, sandbox }) => {
 sandbox.configureVideoFailure();
 page.on('dialog', dialog => dialog.accept());
 await page.goto('/?app=create&project=' + sandbox.project.id);
 await page.getByRole('navigation', { name: 'Library sections' }).getByRole('button', { name: 'Canvas', exact: true }).click();
 await page.getByRole('button', { name: /^Open board/ }).first().click();
 const recovery = page.getByRole('region', { name: 'Video recovery' }).first();
 await expect(recovery).toContainText('Preview saved; final upscale ran out of GPU memory.');
 await recovery.getByText('View saved stage-one preview', { exact: true }).click();
 await expect.poll(() => recovery.locator('video').evaluate(video => video.readyState)).toBeGreaterThan(0);
 await recovery.getByRole('button', { name: 'Use CPU final upscale', exact: true }).click();
 await expect(page.getByRole('combobox', { name: 'Final-stage upscaler' })).toHaveValue('cpu');
 expect(sandbox.board.settings.seed).toBe('18446744073709551615');
 expect(sandbox.board.settings.video.modeDrafts['reference-video'].prompt).toBe('Original failed scene');
 expect(sandbox.submissions).toHaveLength(0);
});
