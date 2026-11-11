#HBR input tables
#Chemistry: knb-lter-hbr.208.14, supplied EML metadata.
#Daily flow: https://hbr-lter.github.io/synthesisbook/Homework.html#hydrology
#Daily precipitation separate until collection intervals are defined.

import argparse
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent


INPUT_FILES = {
    "precip": "HBR_PrecChem_1963-2025.csv",
    "stream": "HBR_StrChem_1963-2025.csv",
    "precip_daily": "HBR_PrecVol_1956-2026.csv",
    "flow": "HBR_StrDis_1956-2024.csv",
}

#site-specific
COLUMN_KEY = {
    "precip": {
        "uniqueID": "UNHID#",
        "site": "Unique_Name",
        "TDN": "TDNmgNL",
        "DON": "DON",
        "NO3": "NO3_Final",
        "NH4": "NH4ugNL_Final",
        "precipCatch": "HBR_PrecipCatch_mm",
    },
    "stream": {
        "uniqueID": "UNHID#",
        "site": "Station_ID",
        "TDN": "TDNmgNL",
        "DON": "DON",
        "NO3": "NO3_Final",
        "NH4": "NH4ugNL",
    },
    "flow": {"DATE": "datetime", "WS": "WS", "Streamflow": "Q_mm_day"},
    "precip_daily": {"DATE": "datetime", "rainGage": "rainGage", "Precip": "P_mm_day"},
}

METADATA_KEY = {
    "fieldCode": "HBR_FieldCode",
    "duplicate": "HBR_Duplicate",
    "sampleType": "HBR_SampleType",
    "canonical": "HBR_Canonical",
    "notes": "HBR_Notes",
    "waterYr": "HBR_WaterYear",
    "ionBalance": "HBR_IonBalance",
}

# EML reports ion mass; Deni's nutrient fields report nitrogen mass.
# Atomic weights: NIST Chemistry WebBook (https://webbook.nist.gov/).
N = 14.0067
NO3_TO_N = N / (N + 3 * 15.9994)
NH4_TO_N = N / (N + 4 * 1.00794)
# HBR codes when sample volume is insufficient for analysis.
CHEMISTRY_MISSING_CODES = (-3.0, -999.9)


# Read as text
def read_table(path, required):
    table = pd.read_csv(path, dtype="string", keep_default_na=False,
                        na_values=["NA", ""])
    missing = set(required) - set(table.columns)
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
    for column in table.columns:
        table[column] = table[column].str.strip().replace({"": pd.NA, "NA": pd.NA})
    table["HBR_SourceRow"] = table.index + 2
    return table


def numeric(values, label, missing_codes=()):
    converted = pd.to_numeric(values, errors="coerce")
    invalid = values.notna() & converted.isna()
    if invalid.any():
        examples = values.loc[invalid].drop_duplicates().head(5).tolist()
        raise ValueError(f"{label}: non-numeric values {examples}")
    if converted.isin([float("inf"), float("-inf")]).any():
        raise ValueError(f"{label}: infinite values")
    return converted.mask(converted.isin(missing_codes))


#sortable timestamps
def collection_dates(table, label):
    dates = pd.to_datetime(table["date"], format="%Y-%m-%d", errors="raise")
    if dates.isna().any():
        raise ValueError(f"{label}: missing collection dates")
    times = table["timeEST"]
    valid = times.str.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?")
    invalid = times.notna() & ~valid.fillna(False)
    if invalid.any():
        raise ValueError(f"{label}: invalid collection times "
                         f"{times.loc[invalid].head(5).tolist()}")
    padded = times.fillna("00:00")
    padded = padded.where(padded.str.count(":").eq(2), padded + ":00")
    # Missing times use midnight for sorting; the missing-time flag is retained.
    stamp = pd.to_datetime(dates.dt.strftime("%Y-%m-%d") + " " + padded,
                           format="%Y-%m-%d %H:%M:%S", errors="raise")
    return dates, stamp


# retain HBR sample metadata.
def prepare_chemistry(path, kind, site):
    required = set(COLUMN_KEY[kind]) | {"date", "timeEST"}
    raw = read_table(path, required)
    table = raw.loc[raw["site"].eq(site).fillna(False)].copy()
    if table.empty:
        raise ValueError(f"{path.name}: site {site!r} not found")
    dates, stamp = collection_dates(table, path.name)
    numbers = list(COLUMN_KEY[kind].keys() & {"TDN", "DON", "NO3", "NH4", "precipCatch"})
    for column in numbers:
        table[column] = numeric(table[column], f"{path.name}: {column}",
                                CHEMISTRY_MISSING_CODES)

    result = table[list(COLUMN_KEY[kind])].rename(columns=COLUMN_KEY[kind])
    result["DateTime"] = stamp
    result["CollectionDate"] = dates.dt.strftime("%m/%d/%Y")
    result["CollectionTime"] = table["timeEST"]
    result["HBR_TimeMissing"] = table["timeEST"].isna()
    result["HBR_NO3_mg_L_as_NO3"] = table["NO3"]
    result["HBR_NH4_mg_L_as_NH4"] = table["NH4"]
    result["NO3_Final"] = table["NO3"] * NO3_TO_N
    nh4_column = COLUMN_KEY[kind]["NH4"]
    result[nh4_column] = table["NH4"] * NH4_TO_N * 1000
    # Negative DON is retained so its treatment happens once in the cleaner.
    for original, target in METADATA_KEY.items():
        if original in table:
            result[target] = table[original]
    result["HBR_SourceRow"] = table["HBR_SourceRow"]
    result["HBR_SourceFile"] = path.name
    result = result.sort_values(["DateTime", "HBR_SourceRow"], kind="stable")
    return result.reset_index(drop=True)


# daily precipitation separate until collection intervals are matched.
def prepare_precipitation(path, rain_gage):
    table = read_table(path, ["DATE", "rainGage", "Precip"])
    table = table.loc[table["rainGage"].eq(rain_gage).fillna(False)].copy()
    if table.empty:
        raise ValueError(f"{path.name}: rain gage {rain_gage!r} not found")
    result = table[list(COLUMN_KEY["precip_daily"])].rename(
        columns=COLUMN_KEY["precip_daily"])
    result["datetime"] = pd.to_datetime(table["DATE"], format="%Y-%m-%d",
                                        errors="raise")
    if result["datetime"].isna().any():
        raise ValueError(f"{path.name}: missing precipitation dates")
    result["P_mm_day"] = numeric(table["Precip"], f"{path.name}: Precip")
    result["HBR_SourceRow"] = table["HBR_SourceRow"]
    result["HBR_SourceFile"] = path.name
    return result.sort_values("datetime", kind="stable").reset_index(drop=True)


#daily runoff for aggregation to collection intervals.
def prepare_flow(path, watershed):
    table = read_table(path, ["DATE", "WS", "Streamflow", "Flag"])
    ws = numeric(table["WS"], f"{path.name}: WS")
    table = table.loc[ws.eq(watershed).fillna(False)].copy()
    if table.empty:
        raise ValueError(f"{path.name}: watershed {watershed} not found")
    result = table[list(COLUMN_KEY["flow"])].rename(columns=COLUMN_KEY["flow"])
    result["datetime"] = pd.to_datetime(table["DATE"], format="%Y-%m-%d",
                                        errors="raise")
    if result["datetime"].isna().any():
        raise ValueError(f"{path.name}: missing discharge dates")
    result["WS"] = watershed
    result["Q_mm_day"] = numeric(table["Streamflow"], f"{path.name}: Streamflow")
    # HBR daily runoff already area-normalized; no cfs conversion needed.
    result["HBR_FlowFlag"] = table["Flag"]
    result["HBR_SourceRow"] = table["HBR_SourceRow"]
    result["HBR_SourceFile"] = path.name
    return result.sort_values("datetime", kind="stable").reset_index(drop=True)


#flags and source metadata remain in the CSVs.
def report(name, table):
    date_column = "DateTime" if "DateTime" in table else "datetime"
    dates = table[date_column]
    measurements = [column for column in (
        "TDNmgNL", "DON", "NO3_Final", "NH4ugNL_Final", "NH4ugNL",
        "P_mm_day", "Q_mm_day",
    ) if column in table]
    missing_cells = int(table[measurements].isna().sum().sum())
    print(f"{name}: {len(table):,} rows; "
          f"{dates.min():%Y-%m-%d} to {dates.max():%Y-%m-%d}; "
          f"{missing_cells:,} missing measurement cells")


#file locations and station choices outside the preparation functions.
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, default=PROJECT_DIR / "data_raw")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--precip-site", default="RG11")
    parser.add_argument("--rain-gage", default="RG11")
    parser.add_argument("--stream-site", default="W6")
    parser.add_argument("--watershed", type=int, default=6)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    output_dir = args.output_dir or PROJECT_DIR / "data_precleaned"
    if any("/" in name or "\\" in name
           for name in [args.precip_site, args.stream_site, args.rain_gage]):
        parser.error("Site names cannot contain path separators")

    try:
        if output_dir.resolve() == args.input_dir.resolve():
            raise ValueError("Input and output directories must be different.")
        # Validate inputs before writing output.
        tables = {
            f"HBR_{args.precip_site}_precip_precleaned.csv": prepare_chemistry(
                args.input_dir / INPUT_FILES["precip"], "precip", args.precip_site),
            f"HBR_{args.stream_site}_stream_precleaned.csv": prepare_chemistry(
                args.input_dir / INPUT_FILES["stream"], "stream", args.stream_site),
            f"HBR_{args.rain_gage}_precipitation_daily_precleaned.csv": prepare_precipitation(
                args.input_dir / INPUT_FILES["precip_daily"], args.rain_gage),
            f"HBR_WS{args.watershed}_discharge_precleaned.csv": prepare_flow(
                args.input_dir / INPUT_FILES["flow"], args.watershed),
        }
        for name in tables:
            if (output_dir / name).is_symlink():
                raise ValueError(f"Output is a symbolic link: {name}. Choose another output directory.")
        existing = [name for name in tables if (output_dir / name).exists()]
        if existing and not args.overwrite:
            raise ValueError(f"Output exists: {', '.join(existing)}. Use --overwrite to replace.")
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, table in tables.items():
            # ISO timestamps chronological
            table.to_csv(output_dir / name, mode="w" if args.overwrite else "x",
                         index=False, na_rep="NA",
                         date_format="%Y-%m-%d %H:%M:%S")
            report(name, table)
        print(f"Saved to {output_dir.resolve()}")
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
