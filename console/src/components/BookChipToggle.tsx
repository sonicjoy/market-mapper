import { BOOK_CHIP_BASE, bookChipClass } from "../lib/leagueBooks";

type Props = {
  book: string;
  text?: string;
  enabled: boolean;
  present?: boolean;
  label?: string;
  title?: string;
  onToggle: (next: boolean) => void;
};

/** Brand / strikethrough / dashed sportsbook pill. Same look as Rules leagues. */
export function BookChipToggle({
  book,
  text,
  enabled,
  present = true,
  label,
  title,
  onToggle,
}: Props) {
  const shown = (text ?? book).trim() || book;
  return (
    <button
      type="button"
      aria-pressed={present && enabled}
      aria-label={label ?? shown}
      title={title}
      className={`${BOOK_CHIP_BASE} ${bookChipClass({ present, enabled })}`}
      onClick={() => onToggle(!enabled)}
    >
      {shown}
    </button>
  );
}
