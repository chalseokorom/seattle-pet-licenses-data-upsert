"""Combine dated pet license snapshots into one history, one row per license.

Usage: python combine_pet_licenses.py

Combines every dated CSV in data/ (e.g. ..._2026.10.31.csv), oldest first, and
writes combined, changes and summary CSVs to data/output/. To add a snapshot,
put it in data/ and run the script again.

A pet re-licensed under a new number would look like a lapse plus a new
license, so lapsed and new licenses are linked when the pet's profile (name,
species, breeds, ZIP) is unique on both sides. Only the previous snapshot's
lapses are linked; linking further back matched no better than chance.
"""
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

KEY = ["License Number", "Species"]  # some numbers are reused across species
FIELDS = ["License Issue Date", "Animal's Name", "Primary Breed", "Secondary Breed", "ZIP Code"]
PROFILE = ["Animal's Name", "Species", "Primary Breed", "Secondary Breed", "ZIP Code"]
DATA_DIR = Path(__file__).resolve().parent / "data"
DATE = re.compile(r"(\d{4})\D(\d{2})\D(\d{2})")


def file_date(path):
    """Read the snapshot date from a file name like ..._2026.10.31.csv."""
    return pd.Timestamp("-".join(DATE.search(Path(path).name).groups()))


def collect_files(folder):
    """List the dated CSVs directly in a folder, sorted by date."""
    files = sorted((f for f in Path(folder).glob("*.csv") if DATE.search(f.name)), key=file_date)
    dates = [file_date(f) for f in files]
    if len(set(dates)) < len(dates):
        raise SystemExit("Two files share a date.")
    if len(files) < 2:
        raise SystemExit("Need at least two dated files.")
    return files


def load(path):
    """Read one snapshot and add the history columns."""
    with open(path, encoding="utf-8-sig") as fh:
        header = fh.readline()
    sep = ";" if header.count(";") > header.count(",") else ","
    df = pd.read_csv(path, dtype=str, sep=sep, encoding="utf-8-sig")

    df["ZIP Code"] = df["ZIP Code"].str.strip()
    df["License Issue Date"] = pd.to_datetime(df["License Issue Date"], format="mixed")
    df["last_seen"] = file_date(path)
    df["Is Active"] = "Yes"
    for col in ["Relicensed As", "Relicensed From"]:
        df[col] = pd.Series(pd.NA, index=df.index, dtype="string")
    df = df.drop_duplicates().reset_index(drop=True)

    dups = df.duplicated(KEY, keep=False).sum()
    if dups:
        warnings.warn(f"{path}: {dups} rows share a license number and species; all are kept.")
    return df


def unique_profiles(df):
    """Map each profile that occurs once in df to its row label."""
    p = df[PROFILE].fillna("").apply(lambda s: s.str.strip().str.lower()).agg("|".join, axis=1)
    p = p if len(df) else pd.Series([], dtype=str)
    return pd.Series(df.index, index=p)[p.map(p.value_counts()).eq(1).to_numpy()]


def link_relicensed(lapsed, added):
    """Pair each lapsed license with a new one for the same pet."""
    old, new = unique_profiles(lapsed), unique_profiles(added)
    both = old.index.intersection(new.index)
    return pd.DataFrame({
        "old_row": old[both].to_numpy(),
        "new_row": new[both].to_numpy(),
        "old_number": lapsed.loc[old[both], "License Number"].to_numpy(),
        "new_number": added.loc[new[both], "License Number"].to_numpy(),
        "Species": lapsed.loc[old[both], "Species"].to_numpy(),
    })


def chance_match_rate(lapsed, added, n=5, seed=0):
    """Share of lapsed licenses that link when their ZIPs are shuffled."""
    rng = np.random.default_rng(seed)
    rates = []
    for _ in range(n):
        shuffled = lapsed.assign(**{"ZIP Code": rng.permutation(lapsed["ZIP Code"].to_numpy())})
        rates.append(len(link_relicensed(shuffled, added)) / max(len(lapsed), 1))
    return float(np.mean(rates))


def as_text(df):
    """Return the compared fields as plain text so old and new values can be diffed."""
    df = df[FIELDS].copy()
    df["License Issue Date"] = df["License Issue Date"].dt.strftime("%Y-%m-%d")
    df["Animal's Name"] = df["Animal's Name"].str.strip()
    return df.fillna("")


def change_log(current, new, links):
    """List what changed between the history and one new snapshot."""
    cur = current.drop_duplicates(KEY).set_index(KEY)
    nw = new.drop_duplicates(KEY).set_index(KEY)
    active = cur.index[cur["Is Active"] == "Yes"]
    inactive = cur.index[cur["Is Active"] != "Yes"]
    old_linked = pd.MultiIndex.from_frame(links[["old_number", "Species"]], names=KEY)
    new_linked = pd.MultiIndex.from_frame(links[["new_number", "Species"]], names=KEY)

    changes = [
        pd.DataFrame({"Change": "New"}, index=nw.index.difference(cur.index).difference(new_linked)),
        pd.DataFrame({"Change": "Lapsed"}, index=active.difference(nw.index).difference(old_linked)),
        pd.DataFrame({"Change": "Relicensed", "Field": "License Number",
                      "Old Value": links["old_number"].to_numpy(),
                      "New Value": links["new_number"].to_numpy()}, index=old_linked),
        pd.DataFrame({"Change": "Reactivated"}, index=inactive.intersection(nw.index)),
    ]
    both = nw.index.intersection(cur.index)
    old, updated = as_text(cur.loc[both]), as_text(nw.loc[both])
    for field in FIELDS:
        diff = old[field] != updated[field]
        changes.append(pd.DataFrame({"Change": "Updated", "Field": field,
                                     "Old Value": old.loc[diff, field],
                                     "New Value": updated.loc[diff, field]}))

    log = pd.concat(changes).rename_axis(KEY).reset_index()
    return log.reindex(columns=KEY + ["Change", "Field", "Old Value", "New Value"])


def combine(current, new):
    """Fold one snapshot into the history. Returns (combined, change log, chance match rate)."""
    cur_idx, new_idx = current.set_index(KEY).index, new.set_index(KEY).index
    lapsed = current[(current["Is Active"] == "Yes") & ~cur_idx.isin(new_idx)]
    added = new[~new_idx.isin(cur_idx)]
    links = link_relicensed(lapsed, added)

    # Links are written by row, not key, because one key can cover two pets.
    new = new.copy()
    new["Relicensed From"] = (new_idx.map(current.drop_duplicates(KEY).set_index(KEY)["Relicensed From"])
                              .astype("string"))
    new.loc[links["new_row"], "Relicensed From"] = links["old_number"].to_numpy()
    dropped = current[~cur_idx.isin(new_idx)].copy()
    dropped.loc[links["old_row"], "Relicensed As"] = links["new_number"].to_numpy()

    out = (pd.concat([new.assign(**{"Is Active": "Yes"}), dropped.assign(**{"Is Active": "No"})])
           .sort_values(["Is Active", "License Issue Date"], ascending=False)
           .reset_index(drop=True))  # the next step links by row label, so labels must be unique
    return out, change_log(current, new, links), chance_match_rate(lapsed, added)


def combine_all(files):
    """Fold every file in order. Returns (combined, change log, one summary row per step)."""
    current = load(files[0])
    logs, steps = [], []
    bar = tqdm(files[1:], desc="Combining", unit="snapshot")
    for path in bar:
        bar.set_postfix_str(Path(path).name)  # show which file is being added
        new, snapshot = load(path), file_date(path).date()
        out, log, chance = combine(current, new)
        counts = log["Change"].value_counts()
        missing = counts.get("Lapsed", 0) + counts.get("Relicensed", 0)
        steps.append({
            "Snapshot": snapshot,
            "Previous": current["last_seen"].max().date(),
            "Licenses in snapshot": len(new),
            **{c: counts.get(c, 0) for c in ["New", "Lapsed", "Relicensed", "Reactivated"]},
            "Updated fields": counts.get("Updated", 0),
            "Relicensed share of missing": round(counts.get("Relicensed", 0) / max(missing, 1), 4),
            "Chance share": round(chance, 4),
        })
        log.insert(0, "Snapshot", snapshot)
        logs.append(log)
        current = out
    return current, pd.concat(logs, ignore_index=True), pd.DataFrame(steps)


def main():
    """Run from the command line: combine data/ and write the outputs."""
    files = collect_files(DATA_DIR)
    out, log, steps = combine_all(files)

    out_dir = DATA_DIR / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    date = f"{file_date(files[-1]):%Y.%m.%d}"
    out.to_csv(out_dir / f"seattle_pet_licenses_combined_{date}.csv", index=False, date_format="%Y-%m-%d")
    log.to_csv(out_dir / f"seattle_pet_licenses_changes_{date}.csv", index=False)
    steps.to_csv(out_dir / f"seattle_pet_licenses_summary_{date}.csv", index=False)

    print("Combined, oldest first:", *files, sep="\n  ")
    print(f"\n{len(out):,} licenses ({(out['Is Active'] == 'Yes').sum():,} active), "
          f"written to {out_dir}\n")
    print(steps.to_string(index=False))


if __name__ == "__main__":
    main()