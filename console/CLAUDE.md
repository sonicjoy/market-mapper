# CLAUDE.md — `console/`
Root rules and deploy facts: `../CLAUDE.md`. **The mapping console is legacy: do not extend it, and do not ship a mapping fix through it** (fix in code under `mappers/`).

## Purpose
React 18 + Vite + TypeScript + Tailwind SPA served by the same uvicorn as the API (`mappers/control_plane/`), at https://mapping.mm.whiteswandata.com (IAP). Pages are in `src/pages/` (gap leaderboard, venue gaps, mapping risk, rules, catalog, coverage, unmapped, bulk override, cart).

## Entry points
- `src/main.tsx` → `src/router.tsx` (routes), `src/nav.ts` (sidebar), `src/pages/`, `src/components/`, `src/lib/`.
- API clients: `src/api.ts` plus `*Api.ts` per feature; shared types `src/types.ts`; state `cartStore.ts`, `chatStore.ts`; TanStack Query for fetching.
- `scripts/*-smoke.mjs`: browser smoke scripts for chat and leagues tabs (run by hand).

## Test
```bash
cd console && npm ci && npm run typecheck && npm test      # vitest; `npm run build` = tsc + vite build
npm run dev                                                 # needs the API from mappers/control_plane
```
Backend tests are in `../tests/control_plane`.

## Gotchas
- Prod sets `MAPPING_CP_ALLOW_ACTIVATE=1` (`../deploy/k8s/mapping-console/overlays/prod-us/env.yaml`), so Approve here still changes the tip; treat the UI as read-only.
- The CronJobs (oom-fold-rank, gap-propose, mismap-alert) run the same image as the console, so a console image deploy also ships them; oom-fold-rank is load-bearing.
- Do not add new pages or Cart / Editor features; cut work belongs in code mappings.
