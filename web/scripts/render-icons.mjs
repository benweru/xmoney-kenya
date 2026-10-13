// Render the PWA's PNG icons from app/icon.svg: `node scripts/render-icons.mjs`.
// Maskable icons keep the mark inside the central 80% safe zone.
import { readFile } from "node:fs/promises";
import { chromium } from "@playwright/test";

const svg = await readFile(new URL("../app/icon.svg", import.meta.url), "utf8");
const targets = [
  { file: "icon-192.png", size: 192, inset: 0 },
  { file: "icon-512.png", size: 512, inset: 0 },
  { file: "apple-touch-icon.png", size: 180, inset: 0 },
  { file: "icon-maskable-512.png", size: 512, inset: 0.12 },
];

const browser = await chromium.launch();
const page = await browser.newPage();
for (const { file, size, inset } of targets) {
  const pad = Math.round(size * inset);
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(
    `<body style="margin:0;background:#0b1215">
       <div style="padding:${pad}px;width:${size - 2 * pad}px;height:${size - 2 * pad}px">
         ${svg.replace("<svg ", `<svg width="${size - 2 * pad}" height="${size - 2 * pad}" `)}
       </div>
     </body>`,
  );
  await page.screenshot({ path: new URL(`../public/${file}`, import.meta.url).pathname });
}
await browser.close();
