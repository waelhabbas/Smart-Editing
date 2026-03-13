"""
Parse B-Roll instruction text files.

Expected format (one line per cut, pipe-separated):
    broll_city.mp4 | عند كلمة "المدينة" | 00:05 | 00:15
    broll_city.mp4 | عند كلمة "الشوارع" | 00:20 | 00:30
    broll_sea.mp4 | عند كلمة "الساحل" | full

Lines starting with # are treated as comments.
"""

import re
import logging

log = logging.getLogger(__name__)


def parse_timecode(tc_str: str) -> float:
    """Parse 'SS', 'MM:SS', or 'HH:MM:SS' to seconds."""
    tc_str = tc_str.strip()
    parts = tc_str.split(":")
    if len(parts) == 1:
        return float(parts[0])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return 0.0


def extract_target_word(instruction: str) -> str:
    """
    Extract the target word from an instruction string.

    Handles:
        عند كلمة "المدينة"
        عند كلمة «المدينة»
        كلمة المدينة
        المدينة
    """
    # Match text inside various quote styles
    match = re.search(r'["\u201c\u201d\u00ab\u00bb](.+?)["\u201c\u201d\u00ab\u00bb]', instruction)
    if match:
        return match.group(1).strip()
    # Fallback: take the word after "كلمة"
    match = re.search(r'كلمة\s+(\S+)', instruction)
    if match:
        return match.group(1).strip()
    # Last fallback: the entire instruction is the word
    return instruction.strip()


def parse_broll_instructions(file_path: str) -> list[dict]:
    """
    Parse a B-Roll instruction text file.

    Returns:
        List of dicts:
        [
            {
                "broll_filename": str,
                "target_word": str,
                "source_in": float,   # seconds (0.0 for full)
                "source_out": float | None,  # None for full
                "is_full": bool,
            },
            ...
        ]
    """
    instructions = []

    with open(file_path, "r", encoding="utf-8") as f:
        raw_content = f.read()
    log.info("Instructions file content (%d chars):\n%s", len(raw_content), raw_content[:2000])

    for line_num, line in enumerate(raw_content.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        log.info("Parsing line %d: '%s'", line_num, line)
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            raise ValueError(
                f"سطر {line_num}: يجب أن يحتوي على 3 أجزاء على الأقل مفصولة بـ | "
                f"(اسم الملف | الكلمة | In | Out أو full)"
            )

        filename = parts[0]
        target_word = extract_target_word(parts[1])
        log.info("Line %d: filename='%s', target_word='%s'", line_num, filename, target_word)
        time_part = parts[2].strip().lower()

        if time_part == "full":
            instructions.append({
                "broll_filename": filename,
                "target_word": target_word,
                "source_in": 0.0,
                "source_out": None,
                "is_full": True,
            })
        else:
            source_in = parse_timecode(parts[2])
            if len(parts) >= 4:
                source_out = parse_timecode(parts[3])
            else:
                raise ValueError(
                    f"سطر {line_num}: يجب تحديد نقطة Out عند استخدام In محدد، "
                    f"أو استخدم 'full' لتغطية الفقرة كاملة"
                )
            if source_out <= source_in:
                raise ValueError(
                    f"سطر {line_num}: نقطة Out ({source_out}) يجب أن تكون أكبر من In ({source_in})"
                )
            instructions.append({
                "broll_filename": filename,
                "target_word": target_word,
                "source_in": source_in,
                "source_out": source_out,
                "is_full": False,
            })

    return instructions
