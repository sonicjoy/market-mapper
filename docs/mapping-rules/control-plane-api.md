> Retired: the mapping console / tip is not a way to ship mapping. Rules are code — see CLAUDE.md.

# Mapping control plane API

**Audience:** engineers who need to recognise, switch off or remove the
M3a–M3c control plane (`mappers/control_plane/`, served by
`mappers.control_plane.app:app`). Do not use it to fix a gap; make the code
change instead.

With the API running, its own docs are at `/docs` (Swagger), `/redoc` and
`/openapi.json`. The console embeds Swagger at `/api-docs`.

## Auth

Identity comes from the **IAP** header `X-Goog-Authenticated-User-Email`
(`accounts.google.com:user@domain`). Roles:

| Env var | Role |
|---------|------|
| `MAPPING_CP_ADMIN_EMAILS` | `admin` |
| any other authenticated email | `approver` |
| missing header | `viewer` (`operator=unknown`) |

Maker/checker is off unless `MAPPING_CP_REQUIRE_MAKER_CHECKER=1`.

## What can still write the tip

Approve on a Review card activates the candidate rule set when
`allow_activate` is on: always on test, on prod when
`MAPPING_CP_ALLOW_ACTIVATE=1` (the prod overlay sets `1` today). `GET /meta`
reports `live_sot` and `allow_activate`. To stop the console changing what
the mapper loads, set `MAPPING_CP_ALLOW_ACTIVATE=0` in
`deploy/k8s/mapping-console/overlays/prod-us/env.yaml` and redeploy.

## Surfaces

| Audience | Prefix | Notes |
|----------|--------|-------|
| Console | `/entry`, `/review`, `/console/rules`, `/meta`, `/chat` | Paste → verify → submit; Mapper Chat |
| Automation (M3a) | `/proposals`, `/rules`, `/rule-sets` | Full proposal records |

Artifact types: `entity_alias`, `mapping_league`, `mapping_market_rules`,
`batch_changes`. `/review/{ref}/approve` is the activating call;
`/chat` and `/chat/stream` never write BQ (see [`mapper-chat.md`](mapper-chat.md)).
`POST /review/combine-pipeline` merges open `pipeline-gap-fix` cards.

## Kill switches

| Switch | Effect |
|---|---|
| `MAPPING_CP_ALLOW_ACTIVATE=0` | Approve no longer activates (prod only; test always activates, `settings.py`) |
| `MAPPING_CP_CHAT=0` | Mapper Chat off |
| `MAPPING_CP_CATALOG=0` | Catalog page + override API off |
| `MAPPING_PIPELINE_GAP_PROPOSE=0` | `gap-propose` CronJob exits 0 without harvesting ([`gap-propose.md`](gap-propose.md)) |
| `MAPPING_PIPELINE_GAP_SUGGEST=0` | No AI suggestion pins on gap cards |

## Error shape

```json
{ "detail": { "reason_code": "stale_rule_set" } }
```

Common `reason_code`s: `stale_rule_set`, `no_rule_set`, `forbidden`,
`maker_checker`, `dry_run_failed`, `not_validated`, `bad_preview`, `not_found`.
