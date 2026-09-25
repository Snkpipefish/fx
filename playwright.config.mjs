// Skjermbilder av hver seksjon i tre bredder, mot frosne fixtures og fast klokke.
// Baselines er tatt i GitHub Actions (ubuntu, Chromium); lokal rendering avviker med
// noen prosent i linjebryting/antialiasing, derfor 5 % toleranse. Ekte layoutbrudd gir langt mer.
// Kjør: npx playwright test            (sammenligner mot tests/screenshots/)
//       npx playwright test -u         (godtar nye baselines)
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  testMatch: /screenshots\.spec\.mjs/,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  outputDir: "test-results",
  snapshotPathTemplate: "tests/screenshots/{projectName}/{arg}{ext}",
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.05, animations: "disabled", caret: "hide", scale: "css" } },
  use: { baseURL: "http://127.0.0.1:8766", colorScheme: "dark", locale: "nb-NO", timezoneId: "Europe/Oslo", deviceScaleFactor: 1 },
  webServer: { command: "python3 -m http.server 8766 --bind 127.0.0.1", url: "http://127.0.0.1:8766/index.html", reuseExistingServer: true, timeout: 20000, stdout: "ignore", stderr: "ignore" },
  projects: [
    { name: "mobil-390", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
    { name: "tablet-768", use: { ...devices["Desktop Chrome"], viewport: { width: 768, height: 1024 } } },
    { name: "desktop-1280", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } },
  ],
});
