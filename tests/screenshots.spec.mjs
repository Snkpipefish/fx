/* Visuell kontroll: siden rendres fra tests/fixtures/ med fast klokke, hver seksjon fotograferes
 * (bildene lastes opp som artifact i Actions) og sammenlignes mot baselines i tests/screenshots/.
 * I tillegg: ingen horisontal scroll i noen bredde, og detaljvisningen av kortene. */
import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = (name) => readFileSync(join(here, "fixtures", name), "utf8");
const SECTIONS = ["top", "renter", "styrke", "tre-ting", "handel", "land"];

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-09-25T12:00:00+02:00"));
  await page.route(/\/data\/dashboard\.json/, (route) => route.fulfill({ contentType: "application/json", body: fixture("dashboard.json") }));
  await page.route(/\/data\/history\.json/, (route) => route.fulfill({ contentType: "application/json", body: fixture("history.json") }));
  await page.goto("/index.html");
  await page.waitForSelector("#pairResult .pair-card");
  await page.evaluate(() => document.fonts.ready);
  await page.addStyleTag({ content: "*, *::before, *::after { animation: none !important; transition: none !important; }" });
});

test("ingen horisontal scroll", async ({ page }) => {
  const [scroll, client] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(scroll, `scrollWidth ${scroll} > clientWidth ${client}`).toBeLessThanOrEqual(client + 1);
  await page.click("#cardMode");
  const [scroll2, client2] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(scroll2, "detaljvisning").toBeLessThanOrEqual(client2 + 1);
});

for (const id of SECTIONS) {
  test(`seksjon ${id}`, async ({ page }, testInfo) => {
    const section = page.locator(`#${id}`);
    // Den faste navigasjonslinjen ville lagt seg over toppen av utsnittet; hero-bildet beholder den
    if (id !== "top") await page.addStyleTag({ content: ".nav { visibility: hidden !important; }" });
    await section.scrollIntoViewIfNeeded();
    const png = await section.screenshot();
    await testInfo.attach(`${id}.png`, { body: png, contentType: "image/png" });
    await expect(section).toHaveScreenshot(`${id}.png`);
  });
}

test("kort i detaljvisning", async ({ page }, testInfo) => {
  await page.click("#cardMode");
  await page.waitForSelector(".grid:not(.compact)");
  await page.addStyleTag({ content: ".nav { visibility: hidden !important; }" });
  const card = page.locator("#card-no");
  await card.scrollIntoViewIfNeeded();
  await testInfo.attach("kort-no-detaljert.png", { body: await card.screenshot(), contentType: "image/png" });
  await expect(card).toHaveScreenshot("kort-no-detaljert.png");
});

test("hele siden som artifact", async ({ page }, testInfo) => {
  await testInfo.attach("hele-siden.png", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
});
