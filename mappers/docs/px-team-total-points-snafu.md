# PX Team Total Points — opaque prefix problem

PX uses opaque abbreviations as prefixes in team-scoped market names
(e.g. `"CAR: Team Total Points"`).  When the prefix has no plausible
derivation from the team name, our conservative aliasing policy leaves
it unaliased — the pipeline skips the market rather than risk assigning
it to the wrong team.

In this example, `CAR` and `DEN` appear on a Tulsa vs Tulane event.
Neither prefix maps obviously to either team, so both Team Total Points
markets are dropped.  The data that gets lost:

```json
{
  "competitors": [
    {
      "abbreviation": "TULANE",
      "display_name": "Tulane Green Wave",
      "id": 60000010,
      "name": "Tulane Green Wave",
      "side": "home"
    },
    {
      "abbreviation": "TULSA",
      "display_name": "Tulsa Golden Hurricane",
      "id": 60000005,
      "name": "Tulsa Golden Hurricane",
      "side": "away"
    }
  ],
  "display_name": "Tulsa Golden Hurricane at Tulane Green Wave",
  "event_id": 60071884,
  "live_disabled": false,
  "name": "Tulsa Golden Hurricane at Tulane Green Wave",
  "scheduled": "2026-02-26T00:30:00Z",
  "sport_name": "Basketball",
  "status": "not_started",
  "tournament_id": 648,
  "tournament_name": "College Basketball",
  "updated_at": 1771975930986414000
}
```

```json
{
  "id": 930000005,
  "market_lines": [
    {
      "id": 930000005,
      "line": 79.5,
      "name": "Fixed total 79.5",
      "selections": [
        {
          "display_line": "79.5",
          "display_name": "under 79.5",
          "line": 79.5,
          "line_id": "18e77246f4ec2e7670a2736d7c5f46e9",
          "name": "under 79.5",
          "outcome_id": 13
        },
        {
          "display_line": "79.5",
          "display_name": "over 79.5",
          "line": 79.5,
          "line_id": "b3d58c945bdcb49a96925fc3251fc6e5",
          "name": "over 79.5",
          "outcome_id": 12
        }
      ],
      "type": "total"
    },
    {
      "id": 930000005,
      "line": 80,
      "name": "Fixed total 80",
      "selections": [
        {
          "display_line": "80",
          "display_name": "under 80",
          "line": 80,
          "line_id": "130102fd96dfe8bac5dfa0d023b170a7",
          "name": "under 80",
          "outcome_id": 13
        },
        {
          "display_line": "80",
          "display_name": "over 80",
          "line": 80,
          "line_id": "72c131c8f808da744403c7d5449c4615",
          "name": "over 80",
          "outcome_id": 12
        }
      ],
      "type": "total"
    },
    {
      "favourite": true,
      "id": 930000005,
      "line": 80.5,
      "name": "Fixed total 80.5",
      "selections": [
        {
          "display_line": "80.5",
          "display_name": "under 80.5",
          "line": 80.5,
          "line_id": "ec2178b3c7005f534576211938926df6",
          "name": "under 80.5",
          "outcome_id": 13
        },
        {
          "display_line": "80.5",
          "display_name": "over 80.5",
          "line": 80.5,
          "line_id": "43fc28daab5d16a511f720c495af4a16",
          "name": "over 80.5",
          "outcome_id": 12
        }
      ],
      "type": "total"
    },
    {
      "id": 930000005,
      "line": 81.5,
      "name": "Fixed total 81.5",
      "selections": [
        {
          "display_line": "81.5",
          "display_name": "under 81.5",
          "line": 81.5,
          "line_id": "8b51a012bd461ab24253012ccc1821de",
          "name": "under 81.5",
          "outcome_id": 13
        },
        {
          "display_line": "81.5",
          "display_name": "over 81.5",
          "line": 81.5,
          "line_id": "89e210756a6abf8d17fcced5ef8c4ec4",
          "name": "over 81.5",
          "outcome_id": 12
        }
      ],
      "type": "total"
    }
  ],
  "name": "CAR: Team Total Points",
  "status": "active",
  "type": "total",
  "updated_at": 1771980323818766000,
  "sport_event_id": 60071884
}
```

Here's another:

```json
{
  "competitors": [
    {
      "abbreviation": "UWM",
      "display_name": "Milwaukee Panthers",
      "id": 60000151,
      "name": "Milwaukee Panthers",
      "side": "home"
    },
    {
      "abbreviation": "YNGST",
      "display_name": "Youngstown State Penguins",
      "id": 60000155,
      "name": "Youngstown State Penguins",
      "side": "away"
    }
  ],
  "display_name": "Youngstown State Penguins at Milwaukee Panthers",
  "event_id": 60068922,
  "live_disabled": false,
  "name": "Youngstown State Penguins at Milwaukee Panthers",
  "scheduled": "2026-02-26T01:00:00Z",
  "sport_name": "Basketball",
  "status": "not_started",
  "tournament_id": 648,
  "tournament_name": "College Basketball",
  "updated_at": 1771975931105435000
}
```


```json
{
  "id": 930000151,
  "market_lines": [
    {
      "id": 930000151,
      "line": 73.5,
      "name": "Fixed total 73.5",
      "selections": [
        {
          "display_line": "73.5",
          "display_name": "under 73.5",
          "line": 73.5,
          "line_id": "5fe6e3f719802e7ef451f119ce02e51b",
          "name": "under 73.5",
          "outcome_id": 13
        },
        {
          "display_line": "73.5",
          "display_name": "over 73.5",
          "line": 73.5,
          "line_id": "052d11d643b118e1a7d2e889ebd22694",
          "name": "over 73.5",
          "outcome_id": 12
        }
      ],
      "type": "total"
    },
    {
      "favourite": true,
      "id": 930000151,
      "line": 74.5,
      "name": "Fixed total 74.5",
      "selections": [
        {
          "display_line": "74.5",
          "display_name": "under 74.5",
          "line": 74.5,
          "line_id": "51b99e99e85096988924b8c9b6959560",
          "name": "under 74.5",
          "outcome_id": 13
        },
        {
          "display_line": "74.5",
          "display_name": "over 74.5",
          "line": 74.5,
          "line_id": "4cc6ec4593637d7b4c4db13f1fc3db34",
          "name": "over 74.5",
          "outcome_id": 12
        }
      ],
      "type": "total"
    },
    {
      "id": 930000151,
      "line": 75.5,
      "name": "Fixed total 75.5",
      "selections": [
        {
          "display_line": "75.5",
          "display_name": "under 75.5",
          "line": 75.5,
          "line_id": "9db12a2ab6c509e28e899df61028e275",
          "name": "under 75.5",
          "outcome_id": 13
        },
        {
          "display_line": "75.5",
          "display_name": "over 75.5",
          "line": 75.5,
          "line_id": "6daa5265230bb8b79177115825d77368",
          "name": "over 75.5",
          "outcome_id": 12
        }
      ],
      "type": "total"
    }
  ],
  "name": "WBD: Team Total Points",
  "status": "active",
  "type": "total",
  "updated_at": 1771990680614274000,
  "sport_event_id": 60068922
}
```

```json
{
  "id": 930000155,
  "market_lines": [
    {
      "id": 930000155,
      "line": 74.5,
      "name": "Fixed total 74.5",
      "selections": [
        {
          "display_line": "74.5",
          "display_name": "under 74.5",
          "line": 74.5,
          "line_id": "a45b537108c196fc1593eaa377ef9f6e",
          "name": "under 74.5",
          "outcome_id": 13
        },
        {
          "display_line": "74.5",
          "display_name": "over 74.5",
          "line": 74.5,
          "line_id": "230b5679fb10b5cd0b10ec63271361f5",
          "name": "over 74.5",
          "outcome_id": 12
        }
      ],
      "type": "total"
    },
    {
      "favourite": true,
      "id": 930000155,
      "line": 75.5,
      "name": "Fixed total 75.5",
      "selections": [
        {
          "display_line": "75.5",
          "display_name": "under 75.5",
          "line": 75.5,
          "line_id": "2410c3eccf4c8e1b7507421ae0675d67",
          "name": "under 75.5",
          "outcome_id": 13
        },
        {
          "display_line": "75.5",
          "display_name": "over 75.5",
          "line": 75.5,
          "line_id": "8c581bc8717f640a703e4159a486b8f4",
          "name": "over 75.5",
          "outcome_id": 12
        }
      ],
      "type": "total"
    }
  ],
  "name": "YNGST: Team Total Points",
  "status": "active",
  "type": "total",
  "updated_at": 1771990680614274000,
  "sport_event_id": 60068922
}
```