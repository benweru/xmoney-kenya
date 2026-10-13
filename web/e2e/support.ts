import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const PIN = "2580";

/** A handle and a mock phone that are new on every run. The suffix picks the mock's outcome. */
export function newUser(suffix: "000" | "032" = "000") {
  const tag = `${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`.slice(-10);
  const digits = String(Math.floor(Math.random() * 1e5)).padStart(5, "0");
  return { handle: `e2e${tag}`, phone: `+2547${digits}${suffix}`, local: `07${digits}${suffix}` };
}

export async function registerOverApi(
  request: APIRequestContext,
  user: ReturnType<typeof newUser>,
) {
  const response = await request.post("/api/v1/users", {
    data: { handle: user.handle, phone: user.phone, pin: PIN },
  });
  expect(response.status(), await response.text()).toBe(201);
}

/** Finish the code step by reading the code from the sandbox inbox panel. */
export async function enterCodeFromInbox(page: Page) {
  await expect(page.getByRole("heading", { name: "Enter your code" })).toBeVisible();
  await expect(page.getByTestId("inbox-code")).toHaveText(/^\d{6}$/);
  await page.getByRole("button", { name: "Use code" }).click();
  await page.getByRole("button", { name: "Verify and continue" }).click();
  await expect(page).toHaveURL(/\/home\/$/);
}

export async function signIn(page: Page, user: ReturnType<typeof newUser>) {
  await page.goto("/sign-in/");
  await page.getByLabel("Phone number").fill(user.local);
  await page.getByLabel("PIN").fill(PIN);
  await page.getByRole("button", { name: "Continue" }).click();
  await enterCodeFromInbox(page);
}
