import { LIVE_ACK, LIVE_ACK_BATCH } from "../lib/sotCopy";

export function LiveAckCheckbox({
  checked,
  onChange,
  batch = false,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  batch?: boolean;
}) {
  return (
    <label className="flex items-start gap-2 text-xs text-amber-800 dark:text-amber-200">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>{batch ? LIVE_ACK_BATCH : LIVE_ACK}</span>
    </label>
  );
}
