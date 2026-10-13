// Capture README screenshots from a running stack on the mock (`make demo`):
//   node scripts/screenshots.mjs [baseURL]   → docs/images/wallet-*.png
// Seeds @amina, @baraka, and @wanjiku with a little activity first. Run it on a fresh database:
// it registers three users, which uses most of one IP's hourly registration allowance.
import { chromium, devices, request as playwrightRequest } from "@playwright/test";

const BASE = process.argv[2] ?? "http://localhost:3000";
const OUT = new URL("../../docs/images/", import.meta.url).pathname;
const PIN = "2580";
const USERS = {
  amina: "+254712345000",
  baraka: "+254733111000",
  wanjiku: "+254701222000",
};

async function session(handle) {
  const http = await playwrightRequest.newContext({ baseURL: BASE });
  const phone = USERS[handle];
  await http.post("/api/v1/users", { data: { handle, phone, pin: PIN } });
  const challenge = await (
    await http.post("/api/v1/auth/sign-in", { data: { phone, pin: PIN } })
  ).json();
  const inbox = await (
    await http.get(`/api/v1/sandbox/inbox?phone=${encodeURIComponent(phone)}`)
  ).json();
  const code = /code is (\d{6})/.exec(inbox[0].body)[1];
  const verified = await http.post("/api/v1/auth/verify", {
    data: { challenge_id: challenge.challenge_id, code },
  });
  if (!verified.ok()) throw new Error(`sign-in failed for @${handle}: ${await verified.text()}`);
  return http;
}

async function topUp(http, cents) {
  const topup = await (
    await http.post("/api/v1/topups", {
      data: { amount_cents: cents },
      headers: { "Idempotency-Key": crypto.randomUUID() },
    })
  ).json();
  for (let i = 0; i < 20; i++) {
    const current = await (await http.get(`/api/v1/topups/${topup.id}`)).json();
    if (current.status === "succeeded") return;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error("top-up did not succeed");
}

async function send(http, to, cents, note) {
  const response = await http.post("/api/v1/transfers", {
    data: { to, amount_cents: cents, note },
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
  if (!response.ok()) throw new Error(`send failed: ${await response.text()}`);
}

const amina = await session("amina");
const baraka = await session("baraka");
const wanjiku = await session("wanjiku");
await topUp(amina, 250_000);
await topUp(baraka, 300_000);
await topUp(wanjiku, 100_000);
await send(amina, "@baraka", 35_000, "Lunch at Java");
await send(baraka, "@amina", 120_000, "Rent share");
await send(amina, "@wanjiku", 50_000, "Matatu fare");
await send(wanjiku, "@amina", 20_000, "Chai");

const browser = await chromium.launch();
const context = await browser.newContext({ ...devices["iPhone 13"], baseURL: BASE });
const page = await context.newPage();
await page.goto("/sign-in/");
await page.getByLabel("Phone number").fill("0712 345 000");
await page.getByLabel("PIN").fill(PIN);
await page.getByRole("button", { name: "Continue" }).click();
await page.getByRole("button", { name: "Use code" }).click();
await page.getByRole("button", { name: "Verify and continue" }).click();
await page.waitForURL("**/home/");
await page.getByTestId("transaction").first().waitFor();
await page.screenshot({ path: `${OUT}wallet-home.png` });

await amina.put("/api/sandbox/daraja/__control/behavior", { data: { delay_ms: 10_000 } });
await page.goto("/top-up/");
await page.getByRole("button", { name: "1,000", exact: true }).click();
await page.getByRole("button", { name: "Top up KES 1,000.00" }).click();
await page.getByText("Waiting for M-PESA · 3s").waitFor();
await page.screenshot({ path: `${OUT}wallet-top-up.png` });
await amina.put("/api/sandbox/daraja/__control/behavior", { data: { delay_ms: 0 } });

await page.goto("/send/");
await page.getByLabel("To").fill("baraka");
await page.getByLabel("Amount").fill("750");
await page.getByLabel("Note (optional)").fill("Football tickets");
await page.getByRole("button", { name: "Continue" }).click();
await page.getByTestId("confirm-recipient").waitFor();
await page.screenshot({ path: `${OUT}wallet-send.png` });

await page.goto("/history/");
await page.getByTestId("transaction").nth(3).waitFor();
await page.screenshot({ path: `${OUT}wallet-history.png` });

await browser.close();
console.log(`screenshots written to ${OUT}`);
