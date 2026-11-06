/** Three-band market-rule preview. The strings come from market_rule_card. */

export type RuleCard = {
  venue: string;
  transform: string;
  optic: string;
  label: string;
};

export function RulePreviewCards({ cards }: { cards?: RuleCard[] | null }) {
  if (!cards?.length) return null;
  return (
    <ul className="mt-2 space-y-2 text-xs">
      {cards.map((card) => (
        <li key={`${card.label}:${card.venue}`}>
          <div>{card.venue}</div>
          <div>{card.transform}</div>
          <div>{card.optic}</div>
        </li>
      ))}
    </ul>
  );
}
