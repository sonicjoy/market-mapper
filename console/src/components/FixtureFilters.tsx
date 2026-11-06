import { MultiSelect } from "./MultiSelect";

type Props = {
  leagues?: string[];
  sports?: string[];
  platforms?: string[];
  league: string[];
  sport: string[];
  platform: string[];
  ttkoMaxHours?: number;
  onLeague?: (v: string[]) => void;
  onSport?: (v: string[]) => void;
  onPlatform?: (v: string[]) => void;
  onTtko?: (v: number | undefined) => void;
};

export function FixtureFilters({
  leagues = [],
  sports = [],
  platforms = [],
  league,
  sport,
  platform,
  ttkoMaxHours,
  onLeague,
  onSport,
  onPlatform,
  onTtko,
}: Props) {
  return (
    <div className="flex flex-wrap items-end gap-2">
      {leagues.length > 0 && onLeague ? (
        <MultiSelect
          id="filter-league"
          label="League"
          options={leagues}
          values={league}
          onChange={onLeague}
        />
      ) : null}
      {sports.length > 0 && onSport ? (
        <MultiSelect
          id="filter-sport"
          label="Sport"
          options={sports}
          values={sport}
          onChange={onSport}
        />
      ) : null}
      {platforms.length > 0 && onPlatform ? (
        <MultiSelect
          id="filter-platform"
          label="Platform"
          options={platforms}
          values={platform}
          onChange={onPlatform}
        />
      ) : null}
      {onTtko ? (
        <div>
          <label className="label" htmlFor="ttko">
            TTKO ≤ hours
          </label>
          <input
            id="ttko"
            type="number"
            className="input w-24"
            min={0}
            value={ttkoMaxHours ?? ""}
            onChange={(e) => {
              const raw = e.target.value;
              onTtko(raw === "" ? undefined : Number(raw));
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
