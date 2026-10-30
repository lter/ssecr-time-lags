# HBR preclean

Gets the HBR files into something close to Deni's input format. 
Only renames columns, converts units, and keeps everything else. 
No QC, no detection limits, no interval matching

## Run

Put the 4 csvs from the [Drive folder](https://drive.google.com/drive/folders/1PEP9YHtC_Wm_Arc5NqLWvcqIsxy4tNH3) in `data_raw/`, then:

```bash
pip install -r requirements.txt
python HBR_preclean.py
```

Output goes to `data_precleaned/`. Won't overwrite unless you add `--overwrite`.

Optional, to pull the csvs from the drive folder instead of downloading by hand:

```bash
pip install -r requirements-download.txt
python download_data.py
```

Only downloads files that are missing from `data_raw/`, never replaces ones we already have. The drive folder needs to be shared as anyone with the link.

## Files expected (in data_raw/)

| File | What it uses |
| --- | --- |
| `HBR_PrecChem_1963-2025.csv` | RG11 only |
| `HBR_StrChem_1963-2025.csv` | W6 only |
| `HBR_PrecVol_1956-2026.csv` | RG11 daily precip (mm) |
| `HBR_StrDis_1956-2024.csv` | WS6 daily runoff (mm/day) |

Change the site with `--precip-site`, `--stream-site`, `--rain-gage`, `--watershed`.

## output

| Table | Units |
| --- | --- |
| `HBR_RG11_precip_precleaned.csv` | TDN, DON, NO3 mg N/L; NH4 ug N/L |
| `HBR_W6_stream_precleaned.csv` | same |
| `HBR_RG11_precipitation_daily_precleaned.csv` | `P_mm_day` |
| `HBR_WS6_discharge_precleaned.csv` | `Q_mm_day` |

NO3 and NH4 in the raw files are ion mass so they get converted to N. Don't convert again. 
-3 and -999.9 are the not-enough-sample codes so those become NA.
Flags, duplicates, sample types and the original row number kept.

Row counts with the current files: 2124, 3747, 18659, 22432

## NB

- RG11 daily precip stops at 2014-12-31, RG11 chem goes to 2017-11
- Repeated collection dates are still in there (21 in RG11, 207 in W6)
- Not a drop in for Deni's script yet. No `TDNf` style flag columns, and flow and precip are still daily, not summed to collection intervals
- Detection limits, which flags to drop, duplicates/storm samples, interval boundaries all still need to be decided
