#Download the HBR input csvs from the shared Drive folder into data_raw/.
#Files already in data_raw/ are skipped, never replaced.

from pathlib import Path

import gdown


RAW_DIR = Path(__file__).resolve().parent / "data_raw"
FOLDER_URL = "https://drive.google.com/drive/folders/1PEP9YHtC_Wm_Arc5NqLWvcqIsxy4tNH3"
FILES = [
    "HBR_PrecChem_1963-2025.csv",
    "HBR_StrChem_1963-2025.csv",
    "HBR_PrecVol_1956-2026.csv",
    "HBR_StrDis_1956-2024.csv",
]


def main():
    RAW_DIR.mkdir(exist_ok=True)
    missing = [name for name in FILES if not (RAW_DIR / name).exists()]
    if not missing:
        print("All inputs already in data_raw/")
        return
    listing = gdown.download_folder(url=FOLDER_URL, skip_download=True,
                                    quiet=True, use_cookies=False)
    drive_ids = {Path(item.path).name: item.id for item in listing}
    for name in missing:
        if name not in drive_ids:
            raise SystemExit(f"{name} not found in folder")
        # Download to .part first so a failed transfer isn't mistaken for the file.
        part = RAW_DIR / (name + ".part")
        if not gdown.download(id=drive_ids[name], output=str(part),
                              quiet=True, use_cookies=False):
            raise SystemExit(f"Download failed: {name}")
        part.rename(RAW_DIR / name)
    print(f"Downloaded {len(missing)} file(s) to {RAW_DIR}")


if __name__ == "__main__":
    main()
