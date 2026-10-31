"""Upsert a new pet licenses into current data, keeping one row per license.

Usage: python combine_pet_licenses.py CURRENT_FILE NEW_FILE
  CURRENT  existing license data or previous output of this script
  NEW      new license data (date taken from the file name, e.g. 2026.10.31)
"""
from pathlib import Path
import argparse
import re

import pandas as pd

# Identifier is 'License Number' + 'Species', some owners have multiple pets
KEY = ["License Number", "Species"]
SNAP = "Last Seen In Snapshot"


def load(path):
    df = pd.read_csv(path, dtype=str).drop(
        columns=["Is Active", "Source File"], errors="ignore")
    df["License Issue Date"] = pd.to_datetime(
        df["License Issue Date"], format="mixed")
    if SNAP not in df:
        df[SNAP] = "-".join(
            re.search(r"(\d{4})\D(\d{2})\D(\d{2})", path).groups())
    df[SNAP] = pd.to_datetime(df[SNAP])
    return df.drop_duplicates()


parser = argparse.ArgumentParser(usage=__doc__)
parser.add_argument("current")
parser.add_argument("new")
args = parser.parse_args()

current, new = load(args.current), load(args.new)
latest = new[SNAP].max()
assert latest > current[SNAP].max(), "NEW must be newer than CURRENT"

# Add new rows + keep current rows only to update licenses for where it's missing.
dropped = current[~current.set_index(KEY).index.isin(new.set_index(KEY).index)]
out = pd.concat([new, dropped])
out["Is Active"] = (out[SNAP] == latest).map({True: "Yes", False: "No"})
out = out.sort_values(["Is Active", "License Issue Date"], ascending=False)

output_filename = Path("data/output") / f"seattle_pet_licenses_combined_{latest:%Y.%m.%d}.csv"
output_filename.parent.mkdir(parents=True, exist_ok=True)

out.to_csv(output_filename, index=False, date_format="%Y-%m-%d")
print(f"Wrote file to: {output_filename}")
print(out["Is Active"].value_counts().to_string())
