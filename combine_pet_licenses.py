"""Upsert a new pet licenses into current data, keeping one row per license.

Usage: python combine_pet_licenses.py CURRENT_FILE NEW_FILE
  CURRENT  Existing license data or previous output of this script
  NEW      New license data
Both file names must contain a date, e.g. 2026.10.31.
Writes the combined data and a log of changes to data/output/.
"""
import argparse
import re
from pathlib import Path

import pandas as pd

# Identifier is 'License Number' + 'Species', a few numbers are reused across species
KEY = ["License Number", "Species"]
FIELDS = ["License Issue Date", "Animal's Name", "Primary Breed", "Secondary Breed", "ZIP Code"]
OUTPUT_DIR = Path("data/output")


def get_file_date(path):
    return pd.Timestamp("-".join(re.search(r"(\d{4})\D(\d{2})\D(\d{2})", path).groups()))


def load(path):
    df = pd.read_csv(path, dtype=str)
    df["License Issue Date"] = pd.to_datetime(df["License Issue Date"], format="mixed")
    # Raw data gets the date from its file name and counts as active; previous outputs keep their own.
    df["last_updated"] = pd.to_datetime(df.get("last_updated", get_file_date(path)))
    df["Is Active"] = df.get("Is Active", "Yes")
    return df.drop_duplicates()


def as_text(df):
    df = df[FIELDS].copy()
    df["License Issue Date"] = df["License Issue Date"].dt.strftime("%Y-%m-%d")
    return df.fillna("")


def change_log(current, new):
    cur = current.drop_duplicates(KEY).set_index(KEY)
    nw = new.drop_duplicates(KEY).set_index(KEY)
    active = cur.index[cur["Is Active"] == "Yes"]
    inactive = cur.index[cur["Is Active"] != "Yes"]

    changes = [
        pd.DataFrame({"Change": "New"}, index=nw.index.difference(cur.index)),
        pd.DataFrame({"Change": "Lapsed"}, index=active.difference(nw.index)),
        pd.DataFrame({"Change": "Reactivated"}, index=inactive.intersection(nw.index)),
    ]

    # One row per field that changed on licenses in both files.
    both = nw.index.intersection(cur.index)
    old, updated = as_text(cur.loc[both]), as_text(nw.loc[both])
    for field in FIELDS:
        diff = old[field] != updated[field]
        changes.append(pd.DataFrame({"Change": "Updated", "Field": field,
                                     "Old Value": old.loc[diff, field],
                                     "New Value": updated.loc[diff, field]}))

    log = pd.concat(changes).rename_axis(KEY).reset_index()
    return log.reindex(columns=KEY + ["Change", "Field", "Old Value", "New Value"])


parser = argparse.ArgumentParser(usage=__doc__)
parser.add_argument("current")
parser.add_argument("new")
args = parser.parse_args()

latest = get_file_date(args.new)
assert latest > get_file_date(args.current), "NEW must be newer than CURRENT"
current, new = load(args.current), load(args.new)

# Add new rows + keep current rows only for licenses missing from the new data.
dropped = current[~current.set_index(KEY).index.isin(new.set_index(KEY).index)]
out = pd.concat([new.assign(**{"Is Active": "Yes"}),
                 dropped.assign(**{"Is Active": "No"})])
out = out.sort_values(["Is Active", "License Issue Date"], ascending=False)

log = change_log(current, new)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
combined_file = OUTPUT_DIR / f"seattle_pet_licenses_combined_{latest:%Y.%m.%d}.csv"
log_file = OUTPUT_DIR / f"seattle_pet_licenses_changes_{latest:%Y.%m.%d}.csv"

out.to_csv(combined_file, index=False, date_format="%Y-%m-%d")
log.to_csv(log_file, index=False)

print(f"Wrote files: {combined_file} and {log_file}")
print(out["Is Active"].value_counts().to_string())
print(log["Change"].value_counts().to_string())