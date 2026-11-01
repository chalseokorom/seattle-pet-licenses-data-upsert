import pytest

import combine_pet_licenses as cpl

HEADER = "License Issue Date,License Number,Animal's Name,Species,Primary Breed,Secondary Breed,ZIP Code\n"


def write(path, rows, sep=","):
    """Write a small snapshot CSV for a test."""
    text = HEADER.replace(",", sep) + "".join(sep.join(r) + "\n" for r in rows)
    path.write_text(("﻿" if sep == ";" else "") + text, encoding="utf-8")
    return path


OLD_DATA_DATA = [
    ["January 01 2024", "100", "Rex", "Dog", "Terrier", "", "98103"],   # renews, then moves
    ["January 01 2024", "S1", "Mo", "Cat", "Siamese", "", "98101"],     # re-licensed as 800
    ["January 01 2024", "101", "Luna", "Cat", "Mix", "", "98115"],      # ambiguous profile
    ["January 01 2024", "102", "Luna", "Cat", "Mix", "", "98115"],      # ambiguous profile
    ["January 01 2024", "103", "Gone", "Dog", "Poodle", "", "98117"],   # lapses
]
NEW_DATA_DATA = [
    ["January 01 2026", "100", "Rex", "Dog", "Terrier", "", "98105"],
    ["January 01 2026", "800", " mo ", "Cat", "Siamese", "", "98101"],
    ["January 01 2026", "801", "Luna", "Cat", "Mix", "", "98115"],
    ["January 01 2026", "900", "Brand New", "Dog", "Pug", "", "98122"],
]


@pytest.fixture
def two(tmp_path):
    """OLD_DATA_DATA (2024) combined with NEW_DATA (2026): returns (combined, change log, chance rate)."""
    files = write(tmp_path / "s_2024.09.24.csv", OLD_DATA), write(tmp_path / "s_2026.10.31.csv", NEW_DATA)
    return cpl.combine(*map(cpl.load, files))


def test_links_only_unique_profiles(two):
    """Re-licensed pets are linked; ambiguous profiles are not."""
    out, log, _ = two
    change = log.groupby("License Number")["Change"].apply(list)
    assert change["S1"] == ["Relicensed"]                        # " mo " matches "Mo"
    assert change["101"] == change["102"] == ["Lapsed"]          # ambiguous, never guessed
    assert change["103"] == ["Lapsed"] and change["900"] == change["801"] == ["New"]
    assert "800" not in change                                    # not double counted as New
    by_num = out.set_index("License Number")
    assert by_num.loc["S1", "Relicensed As"] == "800" and by_num.loc["800", "Relicensed From"] == "S1"


def test_zip_change_logged(two):
    """A pet that moved shows up as a ZIP Code update."""
    _, log, _ = two
    row = log[(log["License Number"] == "100") & (log["Field"] == "ZIP Code")]
    assert row[["Old Value", "New Value"]].values.tolist() == [["98103", "98105"]]


def test_semicolon_file_reads_like_comma_file(tmp_path):
    """Semicolon files with a BOM load the same as comma files."""
    row = [["July 01 2025", "S9", "Mo", "Cat", "Siamese", "", "98101"]]
    a = cpl.load(write(tmp_path / "a_2025.07.25.csv", row, sep=";"))
    b = cpl.load(write(tmp_path / "b_2025.07.26.csv", row))
    assert a.drop(columns="last_seen").equals(b.drop(columns="last_seen"))


def test_collect_files(tmp_path):
    """Dated CSVs come back sorted by date; sub-folders are skipped and same-date files refused."""
    write(tmp_path / "s_2025.07.25.csv.csv", [])
    write(tmp_path / "s_2024.09.24.csv", [])
    (tmp_path / "notes.csv").write_text("no date")
    (tmp_path / "output").mkdir()
    write(tmp_path / "output" / "s_2026.10.31.csv", [])
    assert [f.name for f in cpl.collect_files(tmp_path)] == ["s_2024.09.24.csv", "s_2025.07.25.csv.csv"]
    write(tmp_path / "a_2025.04.28.csv", []), write(tmp_path / "b_2025.04.28.csv", [])
    with pytest.raises(SystemExit):
        cpl.collect_files(tmp_path)


def test_three_snapshot_chain(tmp_path):
    """Three snapshots combine step by step."""
    rex, mo = OLD_DATA[0], OLD_DATA[1]
    files = [write(tmp_path / "s_2024.09.24.csv", [rex, mo]),
             write(tmp_path / "s_2025.04.28.csv", [rex]),                                         # Mo skips
             write(tmp_path / "s_2026.10.31.csv", [rex, ["May 01 2026", "800", "Mo", "Cat", "Siamese", "", "98101"]])]
    out, log, steps = cpl.combine_all(files)
    assert steps["Lapsed"].tolist() == [1, 0] and len(out) == 3
    # Only the previous step's lapses are linked, so Mo's return is a new license.
    assert log.loc[log["License Number"] == "800", "Change"].tolist() == ["New"]


def test_duplicate_keys_warn(tmp_path):
    """Two pets on one license number trigger a warning."""
    with pytest.warns(UserWarning, match="share a license number"):
        cpl.load(write(tmp_path / "d_2024.09.24.csv", [OLD_DATA[0], OLD_DATA[0][:2] + ["Rex II"] + OLD_DATA[0][3:]]))


def test_main_combines_data_folder(tmp_path, monkeypatch):
    """A plain run combines data/ and writes the three outputs."""
    monkeypatch.setattr(cpl, "DATA_DIR", tmp_path)
    write(tmp_path / "s_2024.09.24.csv", OLD_DATA)
    write(tmp_path / "s_2026.10.31.csv", NEW_DATA)
    cpl.main()
    for name in ["combined", "changes", "summary"]:
        assert (tmp_path / "output" / f"seattle_pet_licenses_{name}_2026.10.31.csv").exists()


def test_reactivated_license(tmp_path):
    """A license that misses a snapshot and returns with the same number is Reactivated."""
    rex, mo = OLD_DATA[0], OLD_DATA[1]
    files = [write(tmp_path / "s_2024.09.24.csv", [rex, mo]),
             write(tmp_path / "s_2025.04.28.csv", [rex]),                                         # Mo skips
             write(tmp_path / "s_2026.10.31.csv", [rex, mo])]                                     # Mo back as S1
    out, log, steps = cpl.combine_all(files)
    assert log.loc[log["License Number"] == "S1", "Change"].tolist() == ["Lapsed", "Reactivated"]
    assert steps["Reactivated"].tolist() == [0, 1]
    assert len(out) == 2 and out.set_index("License Number").loc["S1", "Is Active"] == "Yes"


def test_relicensed_link_carried_forward(tmp_path):
    """A re-licensed pet keeps its Relicensed From link when it renews in a later snapshot."""
    mo_2024 = ["January 01 2024", "S1", "Mo", "Cat", "Siamese", "", "98101"]
    mo_2025 = ["April 01 2025", "800", "Mo", "Cat", "Siamese", "", "98101"]
    mo_2026 = ["April 01 2026", "800", "Mo", "Cat", "Siamese", "", "98101"]                    # renewal
    files = [write(tmp_path / "s_2024.09.24.csv", [mo_2024]),
             write(tmp_path / "s_2025.04.28.csv", [mo_2025]),
             write(tmp_path / "s_2026.10.31.csv", [mo_2026])]
    out, log, _ = cpl.combine_all(files)
    by_num = out.set_index("License Number")
    assert by_num.loc["800", "Relicensed From"] == "S1" and by_num.loc["S1", "Relicensed As"] == "800"
    renewal = log[(log["License Number"] == "800") & (log["Field"] == "License Issue Date")]
    assert renewal[["Old Value", "New Value"]].values.tolist() == [["2025-04-01", "2026-04-01"]]


def test_date_formats(tmp_path):
    """All three date styles in the City's exports are read correctly."""
    rows = [['"December 12, 2022"', "1", "A", "Cat", "Mix", "", "98101"],
            ["December 18 2015", "2", "B", "Cat", "Mix", "", "98101"],
            ["2026-10-06", "3", "C", "Cat", "Mix", "", "98101"]]
    df = cpl.load(write(tmp_path / "s_2026.10.31.csv", rows))
    assert df["License Issue Date"].dt.strftime("%Y-%m-%d").tolist() == ["2022-12-12", "2015-12-18", "2026-10-06"]