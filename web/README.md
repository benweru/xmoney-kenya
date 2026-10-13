# X Money for Kenya: web

The wallet PWA: Next.js (App Router, static export) + TypeScript + Tailwind, with TanStack Query and a client typed from the API's OpenAPI document. Mobile-first, installable, and sandbox-only.

| Route        | What it does                                                                                                        |
| ------------ | ------------------------------------------------------------------------------------------------------------------- |
| `/`          | Welcome, with links to register and sign in                                                                         |
| `/register/` | Handle, phone, and PIN, then the one-time code                                                                      |
| `/sign-in/`  | Phone and PIN, then the one-time code. The **sandbox inbox** panel shows the code, because the demo never sends SMS |
| `/home/`     | Balance, quick actions, recent activity                                                                             |
| `/top-up/`   | STK Push with a live "waiting for M-PESA" state that polls until the top-up succeeds, fails, or expires             |
| `/send/`     | Send to an @handle: the handle is looked up, you confirm, and one `Idempotency-Key` covers any retry                |
| `/history/`  | Every top-up and send, with cursor pagination ("Load more")                                                         |
| `/inbox/`    | The signed-in phone's sandbox inbox                                                                                 |

Every page shows the sandbox disclaimer: no real money moves, and the project is not affiliated with X Corp or Safaricom. Each data view has loading skeletons, an empty state, and an error state with a retry.

## Run it

```bash
npm ci
npm run dev        # http://localhost:3000, calling the API on http://localhost:8000
```

`npm run dev` talks to the API cross-origin, so `api/.env` needs `CORS_ORIGINS=["http://localhost:3000"]` (it is in `api/.env.example`). `make demo` serves the built site from nginx on <http://localhost:3000> and proxies `/api/*` to the API, which is the same layout CloudFront uses on AWS. Cookies, no CORS.

`NEXT_PUBLIC_API_URL` overrides the API base URL at build time. It defaults to `/api` (same origin) and to `http://localhost:8000` under `next dev`.

## Checks

```bash
npm run lint
npm run format:check
npm run typecheck   # next typegen, then tsc --noEmit
npm run build       # static site in out/
npm run e2e         # Playwright on a mobile viewport, against `make demo`
```

## Typed API client

`lib/api/schema.ts` is generated from `api/openapi.json` by `openapi-typescript`. After an API change, run `make openapi` from the repo root. CI fails if `api/openapi.json` or `schema.ts` is stale.

## End-to-end tests

`e2e/wallet.spec.ts` runs against the Daraja mock and covers:

- Registering, signing in with the code from the sandbox inbox, topping up through STK, sending to an @handle, and checking history and balance.
- A cancelled STK prompt (a phone ending in `032`), an unknown handle, and an overdraft. None of them moves money.
- The disclaimer on every public page, and the redirect for signed-out visitors.

CI runs the suite in the `e2e` job against `docker compose --profile app`. Each run registers a few users, and registration is limited to 10 an hour per IP. If you rerun it many times against one local stack, you'll get `429`s. `make down && docker volume rm xmoney-kenya_xmoney_pg` starts fresh.

## Screenshots and icons

- `node scripts/screenshots.mjs` (or `make screenshots`) seeds @amina, @baraka, and @wanjiku on a fresh stack and writes `docs/images/wallet-*.png`.
- `node scripts/render-icons.mjs` renders the PWA icons in `public/` from `app/icon.svg`.
