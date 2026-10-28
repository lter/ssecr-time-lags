
import argparse
from pathlib import Path

import pandas as pd


INPUT_FILES = {
    "precip": "HBR_PrecChem_1963-2024.csv",
    "stream": "HBR_StrChem_1963-2024.csv",
    "flow": "HBR_Discharge_1956-2024.csv",
}

#site-specific names separate from the processing steps.
COLUMN_KEY = {
    "precip": {
        "uniqueID": "UNHID#",
        "site": "Unique_Name",
        "TDN": "TDNmgNL",
        "DON": "DON",
        "NO3": "NO3_Final",
        "NH4": "NH4ugNL_Final",
        "precipCatch": "TF_Sum_P_wUNHfilled_mm",
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

# EML reports ion mass
N = 14.0067
NO3_TO_N = N / (N + 3 * 15.9994)
NH4_TO_N = N / (N + 4 * 1.00794)
# HBR uses these codes when sample volume is insufficient for analysis.
CHEMISTRY_MISSING_CODES = (-3.0, -999.9)


# Read as text so sample identifiers and field codes survive import.
def read_table(path, required):
    table = pd.read_csv(path, dtype="string", keep_default_na=False,
                        na_values=["NA", ""])
    missing = set(required) - set(table.columns)
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
    for column in table.columns:
        table[column] = table[column].str.strip().replace("", pd.NA)
    table["HBR_SourceRow"] = table.index + 2
    return table


#unformatted measurements before they become missing values.
def numeric(values, label, missing_codes=()):
    converted = pd.to_numeric(values, errors="coerce")
    invalid = values.notna() & converted.isna()
    if invalid.any():
        examples = values.loc[invalid].drop_duplicates().head(5).tolist()
        raise ValueError(f"{label}: non-numeric values {examples}")
    if converted.isin([float("inf"), float("-inf")]).any():
        raise ValueError(f"{label}: infinite values")
    return converted.mask(converted.isin(missing_codes))


#sortable timestamps while preserving missing-time information.
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


# Preserve daily runoff for later aggregation to collection intervals.
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
    # HBR daily runoff is already area-normalized; no cfs conversion is needed.
    result["HBR_FlowFlag"] = table["Flag"]
    result["HBR_SourceRow"] = table["HBR_SourceRow"]
    result["HBR_SourceFile"] = path.name
    return result.sort_values("datetime", kind="stable").reset_index(drop=True)


# Expose missingness and repeated dates before downstream cleaning.
def report(name, table):
    date_column = "DateTime" if "DateTime" in table else "datetime"
    dates = table[date_column]
    print(f"{name}: {len(table):,} rows; "
          f"{dates.min():%Y-%m-%d} to {dates.max():%Y-%m-%d}")
    print(f"  Repeated dates retained: {dates.dt.normalize().duplicated().sum():,}")
    if "TDNmgNL" in table:
        columns = [c for c in ["TDNmgNL", "DON", "NO3_Final", "NH4ugNL_Final",
                               "NH4ugNL"] if c in table]
        print("  Missing: " + "; ".join(f"{c}={table[c].isna().sum():,}" for c in columns))
        if "HBR_Duplicate" in table:
            print(f"  Marked duplicates retained: {table['HBR_Duplicate'].notna().sum():,}")
        print(f"  Missing collection times: {table['HBR_TimeMissing'].sum():,}")
    if "TF_Sum_P_wUNHfilled_mm" in table:
        count = table["TF_Sum_P_wUNHfilled_mm"].notna().sum()
        print(f"  Precipitation amounts available: {count:,}/{len(table):,}")
    if "Q_mm_day" in table:
        print(f"  Missing discharge: {table['Q_mm_day'].isna().sum():,}")


# Keep file locations and station choices outside the preparation functions.
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--precip-site", default="RG11")
    parser.add_argument("--stream-site", default="W6")
    parser.add_argument("--watershed", type=int, default=6)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    output_dir = args.output_dir or args.input_dir / "precleaned"
    if any("/" in name or "\\" in name for name in [args.precip_site, args.stream_site]):
        parser.error("Site names cannot contain path separators")

    try:
        # Validate all three inputs before writing any output.
        tables = {
            f"HBR_{args.precip_site}_precip_precleaned.csv": prepare_chemistry(
                args.input_dir / INPUT_FILES["precip"], "precip", args.precip_site),
            f"HBR_{args.stream_site}_stream_precleaned.csv": prepare_chemistry(
                args.input_dir / INPUT_FILES["stream"], "stream", args.stream_site),
            f"HBR_WS{args.watershed}_discharge_precleaned.csv": prepare_flow(
                args.input_dir / INPUT_FILES["flow"], args.watershed),
        }
        existing = [name for name in tables if (output_dir / name).exists()]
        if existing and not args.overwrite:
            raise ValueError(f"Output exists: {', '.join(existing)}. Use --overwrite to replace.")
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, table in tables.items():
            # ISO timestamps remain chronological if read back as text.
            table.to_csv(output_dir / name, index=False, na_rep="NA",
                         date_format="%Y-%m-%d %H:%M:%S")
            report(name, table)
        print(f"Saved to {output_dir.resolve()}")
        print("Murray's cleaner still needs HBR site, QC and daily-flow settings.")
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
