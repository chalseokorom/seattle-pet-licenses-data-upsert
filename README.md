# Seattle Pet Licenses: Combined History

Combines dated snapshots of the City of Seattle's pet license data into one history with one row per license. It records what changed between snapshots: new licenses, lapses, renewals, moves, and pets re-licensed under a new number.

## Usage

```bash
pip install -r requirements.txt
python combine_pet_licenses.py   # combine every dated CSV in data/
pytest                           # run the tests
```

To add a snapshot, save it in `data/` with its date in the file name (e.g. `seattle_pet_licenses_2027.01.15.csv`) and run the script again. A full run on the six current snapshots takes about a minute; a progress bar shows each step.

## Outputs (`data/output/`)

Each file is named after the newest snapshot's date.

| File | Contents |
|---|---|
| `combined` | Every license ever seen, with `Is Active`, `last_seen`, and `Relicensed As` / `Relicensed From` links |
| `changes` | Every change at every step: New, Lapsed, Relicensed, Reactivated, or Updated (one row per changed field) |
| `summary` | One row per step: counts of each change type and the re-licensing check |

## How re-licensing is detected

The City sometimes gives a pet a new license number at renewal. That would otherwise look like one lapse plus one new license. A lapsed license is linked to a new one when the pet's profile (name, species, both breeds, ZIP) matches exactly one license on each side, so common profiles are never guessed at.

Each step also shuffles ZIP codes and re-runs the matching to estimate how many links would happen by chance. Real links run at 11–42% of missing licenses, against 2–3% by chance. Only the previous snapshot's lapses are linked: matching further back did no better than chance.

## Data

| Snapshot | Source |
|---|---|
| 2019.01.31 | [OpenIntro](https://github.com/OpenIntroStat/openintro) copy; pulled between Jan and Apr 2019, so the date is approximate |
| 2020.10.23, 2025.04.28, 2025.07.25 | [Internet Archive](https://web.archive.org) captures of the City's CSV export |
| 2024.09.24, 2026.10.31 | Downloaded from [data.seattle.gov](https://data.seattle.gov/City-Administration/Seattle-Pet-Licenses/jguv-t9rb). The 2026 file was retrieved Oct 31, 2026; the portal's data runs through Oct 6, 2026. |

The script reads both comma- and semicolon-separated files, and all three date styles used in the exports.

## What the summary shows

| Step | New | Lapsed | Re-licensed | Re-licensed share of missing |
|---|---|---|---|---|
| 2019 → Oct 2020 | 16,712 | 20,226 | 3,326 | 14% |
| Oct 2020 → Sep 2024 | 24,454 | 29,905 | 3,837 | 11% |
| Sep 2024 → Apr 2025 | 7,049 | 7,777 | 3,041 | 28% |
| Apr 2025 → Jul 2025 | 2,435 | 3,151 | 2,273 | 42% |
| Jul 2025 → Oct 2026 | 10,842 | 15,294 | 9,884 | 39% |

The jump in re-licensing during 2025 suggests the City began issuing new license numbers at renewal around then.

## Limitations

- Snapshots are months or years apart, so a pet licensed and lapsed between two snapshots is never seen.
- Matching is conservative: a pet renamed or moved *and* re-numbered at the same time isn't linked.
- A few license numbers cover two pets; the script warns about these and keeps both rows.
