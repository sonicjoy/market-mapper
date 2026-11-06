# Optic Late-Appearing Fixtures

## Summary

Optic activates fixtures on a lag — games can appear on the
`fixtures/active` endpoint anywhere from ~24 hours to ~18 hours
before tip-off.  This is not caused by our date-window filtering;
it is Optic's own activation timing.

Kalshi and PX have no time filtering: Kalshi returns all open
markets for each series ticker, and PX returns all events for the
tournament.  Our Optic fetch uses `start_date_before = now + 48h`
but no lower bound, so the constraint is purely on Optic's side.

## Planned fetch schedule

Mapping fetches are planned for **09:15 UTC** and **21:15 UTC**.
The 09:15 fetch should give Optic enough lead time for most
basketball games (US evening tips are 22:00–03:30 UTC, giving
Optic at least ~13 hours).  Whether this is reliably sufficient
remains to be seen — we may need to decide how close to tip-off
Optic can be before we chase them up.

## Observations

### 2026-03-12 — New Mexico vs San Jose State

NCAAB game: **San Jose State at New Mexico**, scheduled
2026-03-13T03:30:00Z.

| Fetch time (UTC) | Hours to tip-off | Optic has fixture? |
|-------------------|------------------|--------------------|
| 2026-03-12 03:33  | ~24.0            | no                 |
| 2026-03-12 06:40  | ~20.8            | no                 |
| 2026-03-12 09:25  | ~18.1            | yes                |

By the 09:25 fetch there were **no missing Optic fixtures** versus
what PX and Kalshi had fixtured for NCAAB.  The game appeared
sometime between 06:40 and 09:25 UTC.

### 2026-03-11 — Wake Forest/Clemson and Northwestern/Indiana

Two NCAAB games were missing from the early Optic fetch but
present in the later one:

- **Wake Forest at Clemson** (scheduled 2026-03-12T01:30:00Z)
- **Northwestern at Indiana** (scheduled 2026-03-11T22:30:00Z)

| Fetch time (UTC) | Fixture count | Missing games? |
|-------------------|---------------|----------------|
| 02:50             | 49            | yes (2)        |
| 09:15             | 44            | no             |

Both fetches used `fixtures/active` with `league=ncaab` (and
`nba`), `start_date_before = date.today() + 1 day`, and no
sportsbook filter.

The date window was not the cause: the 02:50 snapshot already
contained games starting well after the two missing ones (e.g.
South Carolina at Oklahoma at 01:30Z, UC Santa Barbara at UC
Davis at 03:30Z).  Optic simply had not activated these fixtures
at 02:50 UTC.  They appeared sometime between 02:50 and 09:15
UTC, roughly 13–20 hours before tip-off.

## Full fixture lists from 2026-03-11 (for reference)

### Early snapshot — 02:50 UTC (49 fixtures)

| Start (UTC)          | Game                                      |
|----------------------|-------------------------------------------|
| 2026-03-11T00:30:00Z | Grambling at Jackson State               |
| 2026-03-11T01:00:00Z | Siena at Merrimack                       |
| 2026-03-11T01:00:00Z | Montana at Portland State                |
| 2026-03-11T01:07:00Z | Santa Clara at Gonzaga                   |
| 2026-03-11T01:17:00Z | New Mexico State at Jacksonville State   |
| 2026-03-11T01:30:00Z | UT Rio Grande Valley at McNeese          |
| 2026-03-11T01:43:00Z | Oklahoma State at Colorado               |
| 2026-03-11T02:00:00Z | Indiana Pacers at Sacramento Kings       |
| 2026-03-11T02:00:00Z | Charlotte Hornets at Portland Trail Blazers |
| 2026-03-11T02:00:00Z | Chicago Bulls at Golden State Warriors   |
| 2026-03-11T03:00:00Z | Timberwolves at Los Angeles Lakers       |
| 2026-03-11T03:30:00Z | Idaho at Eastern Washington              |
| 2026-03-11T15:30:00Z | St. Bonaventure at La Salle              |
| 2026-03-11T16:00:00Z | Pittsburgh at North Carolina State       |
| 2026-03-11T16:00:00Z | Maryland at Iowa                         |
| 2026-03-11T16:30:00Z | Arizona State at Iowa State              |
| 2026-03-11T16:30:00Z | LSU at Kentucky                          |
| 2026-03-11T18:00:00Z | Loyola Chicago at Richmond               |
| 2026-03-11T18:00:00Z | Prairie View A&M at Bethune Cookman      |
| 2026-03-11T18:30:00Z | USC at Washington                        |
| 2026-03-11T18:30:00Z | SMU at Louisville                        |
| 2026-03-11T19:00:00Z | Mississippi State at Auburn              |
| 2026-03-11T19:00:00Z | Wyoming at UNLV                          |
| 2026-03-11T19:00:00Z | Cincinnati at UCF                        |
| 2026-03-11T20:00:00Z | Providence at Butler                     |
| 2026-03-11T21:30:00Z | Air Force at Nevada                      |
| 2026-03-11T22:00:00Z | Delaware State at Morgan State           |
| 2026-03-11T22:30:00Z | Missouri State at Liberty                |
| 2026-03-11T22:30:00Z | Xavier at Marquette                      |
| 2026-03-11T23:00:00Z | BYU at West Virginia                     |
| 2026-03-11T23:00:00Z | Ole Miss at Texas                        |
| 2026-03-11T23:00:00Z | California at Florida State              |
| 2026-03-11T23:00:00Z | Tulane at Memphis                        |
| 2026-03-11T23:00:00Z | Boston University at Lehigh              |
| 2026-03-11T23:30:00Z | Cleveland Cavaliers at Orlando Magic     |
| 2026-03-12T00:00:00Z | Toronto Raptors at New Orleans Pelicans  |
| 2026-03-12T00:30:00Z | Tarleton State at Abilene Christian      |
| 2026-03-12T01:00:00Z | Georgetown at DePaul                     |
| 2026-03-12T01:00:00Z | Temple at Florida Atlantic               |
| 2026-03-12T01:00:00Z | Rutgers at Minnesota                     |
| 2026-03-12T01:00:00Z | New York Knicks at Utah Jazz             |
| 2026-03-12T01:00:00Z | Cal Poly at UC San Diego                 |
| 2026-03-12T01:00:00Z | Fresno State at Colorado State           |
| 2026-03-12T01:30:00Z | South Carolina at Oklahoma               |
| 2026-03-12T02:00:00Z | Charlotte Hornets at Sacramento Kings    |
| 2026-03-12T02:00:00Z | Houston Rockets at Denver Nuggets        |
| 2026-03-12T02:30:00Z | Timberwolves at Los Angeles Clippers     |
| 2026-03-12T03:30:00Z | UC Santa Barbara at UC Davis             |
| 2026-03-12T03:30:00Z | San Jose State at Boise State            |

### Late snapshot — 09:15 UTC (44 fixtures)

| Start (UTC)          | Game                                      |
|----------------------|-------------------------------------------|
| 2026-03-11T15:30:00Z | St. Bonaventure at La Salle              |
| 2026-03-11T16:00:00Z | Pittsburgh at North Carolina State       |
| 2026-03-11T16:00:00Z | Maryland at Iowa                         |
| 2026-03-11T16:30:00Z | Arizona State at Iowa State              |
| 2026-03-11T16:30:00Z | LSU at Kentucky                          |
| 2026-03-11T18:00:00Z | Loyola Chicago at Richmond               |
| 2026-03-11T18:00:00Z | Prairie View A&M at Bethune Cookman      |
| 2026-03-11T18:30:00Z | USC at Washington                        |
| 2026-03-11T18:30:00Z | SMU at Louisville                        |
| 2026-03-11T19:00:00Z | Mississippi State at Auburn              |
| 2026-03-11T19:00:00Z | Wyoming at UNLV                          |
| 2026-03-11T19:00:00Z | Cincinnati at UCF                        |
| 2026-03-11T20:00:00Z | Providence at Butler                     |
| 2026-03-11T21:00:00Z | McNeese at Stephen F. Austin             |
| 2026-03-11T21:30:00Z | Air Force at Nevada                      |
| 2026-03-11T22:00:00Z | Delaware State at Morgan State           |
| 2026-03-11T22:30:00Z | Missouri State at Liberty                |
| 2026-03-11T22:30:00Z | Xavier at Marquette                      |
| **2026-03-11T22:30:00Z** | **Northwestern at Indiana**          |
| 2026-03-11T23:00:00Z | BYU at West Virginia                     |
| 2026-03-11T23:00:00Z | Ole Miss at Texas                        |
| 2026-03-11T23:00:00Z | California at Florida State              |
| 2026-03-11T23:00:00Z | Tulane at Memphis                        |
| 2026-03-11T23:00:00Z | Boston University at Lehigh              |
| 2026-03-11T23:30:00Z | Cleveland Cavaliers at Orlando Magic     |
| 2026-03-12T00:00:00Z | Toronto Raptors at New Orleans Pelicans  |
| 2026-03-12T00:30:00Z | Tarleton State at Abilene Christian      |
| 2026-03-12T00:30:00Z | Jackson State at Florida A&M             |
| 2026-03-12T01:00:00Z | Georgetown at DePaul                     |
| 2026-03-12T01:00:00Z | Temple at Florida Atlantic               |
| 2026-03-12T01:00:00Z | Rutgers at Minnesota                     |
| 2026-03-12T01:00:00Z | New Mexico State at Sam Houston State    |
| 2026-03-12T01:00:00Z | New York Knicks at Utah Jazz             |
| 2026-03-12T01:00:00Z | Cal Poly at UC San Diego                 |
| 2026-03-12T01:00:00Z | Fresno State at Colorado State           |
| **2026-03-12T01:30:00Z** | **Wake Forest at Clemson**           |
| 2026-03-12T01:30:00Z | South Carolina at Oklahoma               |
| 2026-03-12T01:30:00Z | Oklahoma State at TCU                    |
| 2026-03-12T02:00:00Z | Charlotte Hornets at Sacramento Kings    |
| 2026-03-12T02:00:00Z | Houston Rockets at Denver Nuggets        |
| 2026-03-12T02:30:00Z | Timberwolves at Los Angeles Clippers     |
| 2026-03-12T03:30:00Z | UC Santa Barbara at UC Davis             |
| 2026-03-12T03:30:00Z | San Jose State at Boise State            |
| 2026-03-12T03:30:00Z | Idaho at Montana                         |
