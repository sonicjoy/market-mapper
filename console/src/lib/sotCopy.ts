/** Copy for live SoT (M4). API still sends `acknowledge_shadow`. */

export const LIVE_ACK =
  "I acknowledge Approve will activate this change on live mapping in this environment.";

export const LIVE_ACK_BATCH =
  "I acknowledge Approve will activate this batch on live mapping in this environment (ack once for the whole cart).";

export const LIVE_BANNER =
  "Approve activates the BQ tip (live classify) in this environment.";

export const LAYOUT_LIVE_BANNER =
  "Approve activates live mapping in this environment.";

export const LAYOUT_SHADOW_BANNER =
  "This environment does not activate. Live classify still uses Python/TOML until the mapper SoT flip.";
