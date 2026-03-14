"""
Analyze transcription with Google Gemini 2.5 to detect scenes/takes
and select the best take per shot.
"""

import json
import logging
import google.generativeai as genai

log = logging.getLogger(__name__)

SYSTEM_PROMPT_EN = """You are an expert video editor analyzing a news reporter's recording.

## How the reporter works:
- The reporter reads a script divided into paragraphs (shots)
- They read each paragraph multiple times (takes) until satisfied
- Then they move to the next paragraph and repeat
- Sometimes they restart from the middle of a paragraph
- Sometimes they read two consecutive paragraphs without stopping

## Your task:
You are given:
1. The reporter's SCRIPT (numbered shots with exact text)
2. The WHISPER TRANSCRIPT (numbered segments with timestamps)

Match each script shot to the transcript segments. When a shot's text appears
multiple times, those are different takes.

## Rules:
- If the same content is read 2+ times consecutively = takes of the same shot
- If content clearly changes = new shot
- Do NOT merge different shots even if they share words
- A take may start from the middle of a paragraph (partial re-read)
- Select the BEST take per shot (default: last take if quality is equal)
- start_segment_index = first segment number of the take
- end_segment_index = last segment number of the take (inclusive)

## CRITICAL SEQUENCING RULES:
- The selected takes MUST be in chronological order in the source video
- Shot N+1's selected take MUST start AFTER Shot N's selected take ends
- NO overlapping time ranges between selected takes
- If the reporter read shots out of order, still select takes that move forward in time
- When multiple takes exist, prefer the one that maintains forward time progression
- If two shots were read in the same take (consecutive without pause), split the segment range between them — do NOT assign the same segments to both shots

## Response format:
Return ONLY JSON:
```json
{
  "scenes": [
    {
      "scene_number": 1,
      "clean_text": "The exact script text for this shot",
      "takes": [
        {"start_segment_index": 0, "end_segment_index": 4},
        {"start_segment_index": 5, "end_segment_index": 9}
      ],
      "selected_take": 1
    }
  ]
}
```
- scene_number = shot number from the script
- selected_take = index in takes array (0-based) — usually the last one
- clean_text = the script text for this shot (from the CSV, not from transcript)"""

SYSTEM_PROMPT_AR = """أنت محرر فيديو خبير تحلل تسجيل مراسل أخباري.

## طريقة عمل المراسل:
- المراسل يقرأ نص تقرير إخباري مقسم إلى فقرات (شوتات)
- يقرأ كل فقرة عدة مرات متتالية (takes) حتى يرضى عن الأداء
- ثم ينتقل للفقرة التالية ويكررها أيضاً عدة مرات
- أحياناً يعيد القراءة من منتصف الفقرة وليس من البداية
- أحياناً يقرأ فقرتين متتاليتين بدون توقف

## مهمتك:
ستحصل على:
1. السكريبت (شوتات مرقمة مع النص)
2. التفريغ من Whisper (segments مرقمة مع timestamps)

طابق كل شوت من السكريبت مع segments التفريغ. عندما يظهر نص نفس الشوت أكثر من مرة = takes مختلفة.

## قواعد مهمة:
- إذا قرأ المراسل نفس المحتوى مرتين أو أكثر متتالياً = takes لنفس المشهد
- إذا تغير المحتوى بشكل واضح = مشهد جديد
- لا تجمع فقرات مختلفة في مشهد واحد حتى لو فيها كلمات مشتركة
- الـ take قد يبدأ من منتصف الفقرة (إعادة جزئية)
- اختر أفضل take لكل مشهد (الأخير افتراضياً إذا الجودة متساوية)

## قواعد التسلسل الزمني (مهمة جداً):
- الـ takes المختارة يجب أن تكون بترتيب زمني تصاعدي في الفيديو الأصلي
- الـ take المختار للشوت N+1 يجب أن يبدأ بعد نهاية الـ take المختار للشوت N
- لا يجوز وجود تداخل زمني بين الـ takes المختارة
- إذا قرأ المراسل الشوتات بترتيب مختلف، اختر takes تتقدم زمنياً للأمام
- عند وجود عدة takes، فضّل الذي يحافظ على التقدم الزمني
- إذا قرأ المراسل شوتين متتاليين في نفس القراءة (بدون توقف)، قسّم نطاق الـ segments بينهما — لا تعطي نفس الـ segments لشوتين مختلفين

## تنسيق الرد:
أرجع JSON فقط بدون أي نص إضافي:
```json
{
  "scenes": [
    {
      "scene_number": 1,
      "clean_text": "نص السكريبت لهذا الشوت",
      "takes": [
        {"start_segment_index": 0, "end_segment_index": 4},
        {"start_segment_index": 5, "end_segment_index": 9}
      ],
      "selected_take": 1
    }
  ]
}
```
- scene_number = رقم الشوت من السكريبت
- selected_take = index في مصفوفة takes (0-based) — عادةً آخر واحد
- clean_text = نص السكريبت لهذا الشوت"""


def _format_segments(segments: list[dict]) -> str:
    """Format Whisper segments as numbered lines with timestamps."""
    lines = []
    for i, seg in enumerate(segments):
        start_m, start_s = divmod(seg["start"], 60)
        end_m, end_s = divmod(seg["end"], 60)
        ts = f"[{int(start_m):02d}:{start_s:05.2f} - {int(end_m):02d}:{end_s:05.2f}]"
        lines.append(f"Segment {i}: {ts} {seg['text']}")
    return "\n".join(lines)


def _format_shots(csv_shots: list[dict]) -> str:
    """Format CSV shots as numbered lines."""
    lines = []
    for shot in csv_shots:
        lines.append(f"Shot {shot['shot_number']}: {shot['text']}")
    return "\n".join(lines)


def _parse_response(response_text: str, segments: list[dict], csv_shots: list[dict]) -> dict:
    """Parse Gemini's JSON response and build scene/clip structures."""
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```") and not in_block:
                in_block = True
                continue
            elif line.strip() == "```" and in_block:
                break
            elif in_block:
                json_lines.append(line)
        text = "\n".join(json_lines)

    data = json.loads(text)

    # Build a lookup for CSV shot text
    csv_text_map = {s["shot_number"]: s["text"] for s in csv_shots}

    scenes = []
    selected_clips = []

    for scene_data in data["scenes"]:
        scene_num = scene_data["scene_number"]
        takes = []

        for take_data in scene_data["takes"]:
            start_idx = take_data["start_segment_index"]
            end_idx = take_data["end_segment_index"]

            start_idx = max(0, min(start_idx, len(segments) - 1))
            end_idx = max(start_idx, min(end_idx, len(segments) - 1))

            take_segments = segments[start_idx:end_idx + 1]
            combined_text = " ".join(s["text"] for s in take_segments)

            # Use word-level boundaries for tighter clips
            all_words = [
                w for seg in take_segments
                for w in seg.get("words", [])
                if w.get("start") is not None and w.get("end") is not None
            ]

            if all_words:
                take_start = all_words[0]["start"]
                take_end = all_words[-1]["end"]
            else:
                take_start = take_segments[0]["start"]
                take_end = take_segments[-1]["end"]

            takes.append({
                "start": take_start,
                "end": take_end,
                "text": combined_text,
                "start_segment_index": start_idx,
                "end_segment_index": end_idx,
            })

        if not takes:
            continue

        selected_idx = scene_data.get("selected_take", len(takes) - 1)
        selected_idx = max(0, min(selected_idx, len(takes) - 1))
        selected = takes[selected_idx]

        # Use CSV text as the canonical text (not Whisper/Gemini)
        canonical_text = csv_text_map.get(scene_num, scene_data.get("clean_text", "") or selected["text"])

        scenes.append({
            "scene_number": scene_num,
            "total_takes": len(takes),
            "selected_take": {
                "start": selected["start"],
                "end": selected["end"],
                "text": canonical_text,
            },
            "takes": takes,
        })

        selected_clips.append({
            "start": selected["start"],
            "end": selected["end"],
            "shot_number": scene_num,
            "text": canonical_text,
            "start_segment_index": selected.get("start_segment_index"),
            "end_segment_index": selected.get("end_segment_index"),
        })

    return {
        "scenes": scenes,
        "selected_clips": selected_clips,
        "total_scenes": len(scenes),
        "total_readings": sum(s["total_takes"] for s in scenes),
    }


def analyze_with_gemini(
    segments: list[dict],
    csv_shots: list[dict],
    api_key: str,
    language: str | None = None,
) -> dict:
    """
    Use Gemini 2.5 Flash to analyze transcription and select best takes.

    Args:
        segments: Whisper transcription segments.
        csv_shots: Parsed CSV shots with text.
        api_key: Google Gemini API key.
        language: Language hint ('ar', 'en', or None).

    Returns:
        Dict with scenes, selected_clips, total_scenes, total_readings, token_usage.
    """
    if not segments:
        return {"scenes": [], "selected_clips": [], "total_scenes": 0, "total_readings": 0}

    # Choose prompt language
    is_arabic = language == "ar" if language else any(
        '\u0600' <= c <= '\u06FF' for s in csv_shots[:3] for c in s.get("text", "")
    )
    system = SYSTEM_PROMPT_AR if is_arabic else SYSTEM_PROMPT_EN

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=system,
    )

    formatted_segments = _format_segments(segments)
    formatted_shots = _format_shots(csv_shots)

    if is_arabic:
        user_prompt = f"السكريبت:\n{formatted_shots}\n\nالتفريغ:\n{formatted_segments}"
    else:
        user_prompt = f"Script shots:\n{formatted_shots}\n\nTranscript:\n{formatted_segments}"

    log.info("Sending %d segments + %d shots to Gemini...", len(segments), len(csv_shots))

    max_retries = 2
    last_error = None

    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                user_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )

            result = _parse_response(response.text, segments, csv_shots)

            usage = getattr(response, "usage_metadata", None)
            if usage:
                result["token_usage"] = {
                    "input_tokens": getattr(usage, "prompt_token_count", 0),
                    "output_tokens": getattr(usage, "candidates_token_count", 0),
                    "total_tokens": getattr(usage, "total_token_count", 0),
                }

            log.info("Gemini detected %d scenes from %d readings",
                     result["total_scenes"], result["total_readings"])
            return result

        except json.JSONDecodeError as e:
            last_error = e
            log.warning("Gemini returned invalid JSON (attempt %d/%d): %s",
                        attempt + 1, max_retries, e)
        except Exception as e:
            last_error = e
            log.warning("Gemini API error (attempt %d/%d): %s",
                        attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                continue
            break

    raise RuntimeError(f"Gemini analysis failed after {max_retries} attempts: {last_error}")
