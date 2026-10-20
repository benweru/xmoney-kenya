import { expect, test } from "@playwright/test";

import { PIN, enterCodeFromInbox, newUser, registerOverApi, signIn } from "./support";

test("the sandbox disclaimer is on every page", async ({ page }) => {
  for (const path of ["/", "/register/", "/sign-in/"]) {
    await page.goto(path);
    const note = page.getByRole("note", { name: "Sandbox disclaimer" });
    await expect(note).toContainText("No real money moves");
    await expect(note).toContainText("Not affiliated with X Corp");
  }
});

test("register, top up through STK, send to an @handle, and see the history", async ({
  page,
  request,
}) => {
  const friend = newUser();
  await registerOverApi(request, friend);
  const me = newUser();

  await page.goto("/");
  await page.getByRole("link", { name: "Create a wallet" }).click();
  await page.getByLabel("Handle").fill(me.handle);
  await page.getByLabel("M-PESA phone number").fill(me.local);
  await page.getByLabel("PIN", { exact: true }).fill(PIN);
  await page.getByLabel("Confirm PIN").fill(PIN);
  await page.getByRole("button", { name: "Create wallet" }).click();
  await enterCodeFromInbox(page);

  await expect(page.getByTestId("handle")).toHaveText(`@${me.handle}`);
  await expect(page.getByTestId("balance")).toHaveText("KES 0.00");
  await expect(page.getByText("No activity yet")).toBeVisible();

  await page
    .getByRole("navigation", { name: "Quick actions" })
    .getByRole("link", { name: "Top up" })
    .click();
  await page.getByRole("button", { name: "500", exact: true }).click();
  await page.getByRole("button", { name: "Top up KES 500.00" }).click();
  const success = page.getByTestId("topup-success");
  await expect(success).toContainText("KES 500.00 added");
  await expect(success).toContainText(/SBOX[A-Z0-9]{8}/);
  await page.getByRole("link", { name: "Back to wallet" }).click();
  await expect(page.getByTestId("balance")).toHaveText("KES 500.00");

  await page
    .getByRole("navigation", { name: "Wallet" })
    .getByRole("link", { name: "Send" })
    .click();
  await page.getByLabel("To").fill(`@${friend.handle}`);
  await page.getByLabel("Amount").fill("120");
  await page.getByLabel("Note (optional)").fill("Lunch");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("confirm-recipient")).toHaveText(`@${friend.handle}`);
  await expect(page.getByTestId("confirm-amount")).toHaveText("KES 120.00");
  await expect(page.getByTestId("confirm-fee")).toHaveText("KES 1.00");
  await expect(page.getByTestId("confirm-total")).toHaveText("KES 121.00");
  await page.getByRole("button", { name: "Send KES 121.00" }).click();
  await expect(page.getByTestId("send-success")).toContainText("Sent KES 120.00");

  await page
    .getByRole("navigation", { name: "Wallet" })
    .getByRole("link", { name: "Home" })
    .click();
  await page
    .getByRole("navigation", { name: "Quick actions" })
    .getByRole("link", { name: "Cash out" })
    .click();
  await page.getByRole("button", { name: "KES 100.00", exact: true }).click();
  await page.getByRole("button", { name: "Cash out KES 100.00" }).click();
  const cashout = page.getByTestId("cashout-success");
  await expect(cashout).toContainText("KES 100.00 sent");
  await expect(cashout).toContainText(/SBOX[A-Z0-9]{8}/);
  await page.getByRole("link", { name: "Back to wallet" }).click();
  await expect(page.getByTestId("balance")).toHaveText("KES 279.00");

  await page
    .getByRole("navigation", { name: "Wallet" })
    .getByRole("link", { name: "History" })
    .click();
  const rows = page.getByTestId("transaction");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("M-PESA cash-out");
  await expect(rows.nth(0)).toContainText("− KES 100.00");
  await expect(rows.nth(1)).toContainText(`To @${friend.handle}`);
  await expect(rows.nth(1)).toContainText("− KES 121.00");
  await expect(rows.nth(1)).toContainText("Lunch");
  await expect(rows.nth(2)).toContainText("M-PESA top-up");
  await expect(rows.nth(2)).toContainText("+ KES 500.00");

  await page
    .getByRole("navigation", { name: "Wallet" })
    .getByRole("link", { name: "Home" })
    .click();
  await expect(page.getByTestId("balance")).toHaveText("KES 279.00");
});

test("a cancelled STK prompt and a refused send move no money", async ({ page, request }) => {
  const friend = newUser();
  await registerOverApi(request, friend);
  const me = newUser("032");
  await registerOverApi(request, me);
  await signIn(page, me);

  await page
    .getByRole("navigation", { name: "Wallet" })
    .getByRole("link", { name: "Top up" })
    .click();
  await page.getByRole("button", { name: "100", exact: true }).click();
  await page.getByRole("button", { name: "Top up KES 100.00" }).click();
  await expect(page.getByTestId("topup-danger")).toContainText("Top-up didn't go through");

  await page
    .getByRole("navigation", { name: "Wallet" })
    .getByRole("link", { name: "Send" })
    .click();
  await page.getByLabel("To").fill("@nobody_here_e2e");
  await page.getByLabel("Amount").fill("50");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("No one has the handle @nobody_here_e2e.")).toBeVisible();

  await page.getByLabel("To").fill(friend.handle);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Send KES 50.00" }).click();
  await expect(page.getByText("You don't have enough in your wallet for that.")).toBeVisible();

  await page
    .getByRole("navigation", { name: "Wallet" })
    .getByRole("link", { name: "Home" })
    .click();
  await expect(page.getByTestId("balance")).toHaveText("KES 0.00");
});

test("signed-out visitors are sent to sign-in", async ({ page }) => {
  await page.goto("/home/");
  await expect(page).toHaveURL(/\/sign-in\/$/);
});
