> Retired: the mapping console / tip is not a way to ship mapping. Rules are code — see CLAUDE.md.

# Mapper Chat (M3c) — switch off & monitor

**Audience:** operators turning Mapper Chat off or checking what it still
does. Do not extend Mapper Chat or use it to fix a gap.

## On / off

- `MAPPING_CP_CHAT` on the mapping-console Deployment
  (`deploy/k8s/mapping-console/overlays/*/env.yaml`). Default off in code
  (`mappers/control_plane/settings.py`); the prod overlay sets `1` today.
  Set `0` and redeploy to switch it off. The `gap-propose` CronJob already
  runs with `MAPPING_CP_CHAT=0`.
- Provider config: `MAPPING_CP_CHAT_PROVIDER` (`gemini`),
  `MAPPING_CP_CHAT_MODEL` (`gemini-3.8-flash`), secret
  `MAPPING_CP_CHAT_API_KEY_SECRET` (`mm-mapping-bot-gemini-key`, Secret
  Manager). Removing chat frees that secret.

Chat never approves, activates or writes rule tables. It stages pins into the
console cart for a human to submit, so switching chat off removes no
data path the mapper depends on.

Turns route to skills first (`probe_gap`, `entity_add`, `fixture_coverage`,
`rules_lookup`, `alias_pin`, `onboard_league`, `market_rules`), then a scoped
Gemini loop (`path=llm`).

## Budgets

| Env | Default | Effect |
| --- | --- | --- |
| `MAPPING_CP_CHAT_TOOL_ROUNDS` | 5 | Max tool rounds per LLM turn |
| `MAPPING_CP_CHAT_TIMEOUT_SEC` | 30 | Soft LLM budget |
| `MAPPING_CP_CHAT_DAILY_TURN_BUDGET` | 0 (off) | Per-pod soft turn cap |
| `MAPPING_CP_CHAT_DAILY_TOKEN_BUDGET` | 0 (off) | Per-pod soft token cap |
| `MAPPING_CP_PROBE_CACHE_TTL_SEC` | 900 | LiveLookup / probe cache TTL |

## Monitor (is anyone still using it?)

Cloud Logging:

```text
jsonPayload.event_type="mapping_chat_turn"
jsonPayload.event_type="mapping_chat_step"   # join on conversation_id
```

Turn fields include `outcome`, `path`, `actor` (IAP subject), `page_path`,
`duration_ms`. Closed `outcome` set: `ok`, `ask_slot`, `confirm`,
`refuse_soft`, `needs_code`, `probe_fail`, `deadline`, `no_ui`, `llm_error`,
`unavailable`.

## Tests

Chat tests live under `tests/control_plane/chat_skills/` and
`tests/control_plane/test_chat_*.py`; they go when the code goes.
