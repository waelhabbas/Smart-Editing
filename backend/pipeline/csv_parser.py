"""
Parse the unified CSV template format.

CSV format:
shot_number,text,Type,File_name,cut-01/in,cut-01/out,cut-02/in,cut-02/out,cut-03/in,cut-03/out
"""

import csv
import logging
from backend.utils.timecode import parse_timecode

log = logging.getLogger(__name__)


def parse_csv_template(csv_path: str) -> list[dict]:
    """
    Parse a unified CSV template file into a list of shot dictionaries.

    Each shot dict contains:
        - shot_number: int
        - text: str
        - type: str ("None", "BRoll", "soundbite")
        - file_name: str or None
        - cuts: list of {"in": float, "out": float} in seconds

    Args:
        csv_path: Path to the CSV file.

    Returns:
        List of shot dicts sorted by shot_number.
    """
    shots = []

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            shot_num = row.get("shot_number", "").strip()
            if not shot_num:
                continue

            try:
                shot_number = int(shot_num)
            except ValueError:
                log.warning("Invalid shot_number: %s, skipping row", shot_num)
                continue

            text = row.get("text", "").strip()
            shot_type = row.get("Type", "").strip() or "None"
            file_name = row.get("File_name", "").strip() or None

            # Parse cuts (up to 3)
            cuts = []
            for i in range(1, 4):
                in_key = f"cut-{i:02d}/in"
                out_key = f"cut-{i:02d}/out"
                in_val = row.get(in_key, "").strip()
                out_val = row.get(out_key, "").strip()

                if in_val and out_val:
                    try:
                        cut_in = parse_timecode(in_val)
                        cut_out = parse_timecode(out_val)
                        if cut_out > cut_in:
                            cuts.append({"in": cut_in, "out": cut_out})
                        else:
                            log.warning("Shot %d cut-%02d: out <= in (%s <= %s), skipping",
                                        shot_number, i, out_val, in_val)
                    except ValueError as e:
                        log.warning("Shot %d cut-%02d: invalid timecode: %s", shot_number, i, e)

            # Validate: if type is BRoll or soundbite, file_name is required
            if shot_type.lower() in ("broll", "soundbite") and not file_name:
                log.warning("Shot %d has type '%s' but no File_name, treating as None",
                            shot_number, shot_type)
                shot_type = "None"

            shots.append({
                "shot_number": shot_number,
                "text": text,
                "type": shot_type,
                "file_name": file_name,
                "cuts": cuts,
            })

    shots.sort(key=lambda s: s["shot_number"])
    log.info("Parsed %d shots from CSV", len(shots))
    return shots
