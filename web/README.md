# X Money for Kenya: web

Placeholder Next.js (App Router) + TypeScript + Tailwind app. It will become the wallet PWA and the `/console` back office. For now it renders one static page with the sandbox disclaimer and a link to the API docs.

```bash
npm ci
npm run dev        # http://localhost:3000
npm run lint
npm run typecheck  # next typegen, then tsc --noEmit
npm run build      # standalone output for the Docker image
```

`NEXT_PUBLIC_API_URL` sets the API base URL (default `http://localhost:8000`). It is inlined at build time.
