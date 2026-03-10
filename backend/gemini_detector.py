"""
Detect scenes and takes using Google Gemini 2.5 AI.

Sends transcription segments to Gemini for intelligent analysis.
Gemini understands context and semantics to accurately detect:
- Unique paragraphs (scenes)
- Repeated readings (takes)
- Best take selection (last take)
"""

import json
import logging
import google.generativeai as genai

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """أنت محرر فيديو خبير تحلل تسجيل مراسل أخباري.

## طريقة عمل المراسل:
- المراسل يقرأ نص تقرير إخباري مقسم إلى فقرات
- يقرأ كل فقرة عدة مرات متتالية (takes) حتى يرضى عن الأداء
- ثم ينتقل للفقرة التالية ويكررها أيضاً عدة مرات
- أحياناً يعيد القراءة من منتصف الفقرة وليس من البداية
- أحياناً يقرأ فقرتين متتاليتين بدون توقف

## مهمتك:
حلل النص المفرّغ التالي (مع timestamps) وحدد:
1. الفقرات الفريدة (المشاهد) - كل فقرة مختلفة في المحتوى = مشهد
2. لكل مشهد، حدد كل القراءات المكررة (takes)
3. اختر آخر take لكل مشهد (المحاولة الأخيرة = الأفضل عادةً)

## قواعد مهمة:
- إذا قرأ المراسل نفس المحتوى مرتين أو أكثر متتالياً = takes لنفس المشهد
- إذا تغير المحتوى بشكل واضح = مشهد جديد
- لا تجمع فقرات مختلفة في مشهد واحد حتى لو فيها كلمات مشتركة
- الـ take قد يبدأ من منتصف الفقرة (إعادة جزئية)
- رقم أول segment في الـ take = start_segment_index
- رقم آخر segment في الـ take = end_segment_index (inclusive)

## تنسيق الرد:
أرجع JSON فقط بدون أي نص إضافي:
```json
{
  "scenes": [
    {
      "scene_number": 1,
      "clean_text": "النص النظيف للفقرة بدون تكرار — ما قاله المراسل فعلاً في هذا المشهد",
      "takes": [
        {"start_segment_index": 0, "end_segment_index": 4},
        {"start_segment_index": 5, "end_segment_index": 9}
      ],
      "selected_take": 1
    }
  ]
}
```
- selected_take = index في مصفوفة takes (0-based) — عادةً آخر واحد
- clean_text = النص النهائي النظيف للمشهد من الـ take المختار فقط، بدون أي تكرار أو جمل مكررة. هذا النص سيُعرض كترجمة على الفيديو"""

SCRIPT_ADDENDUM = """

## السكريبت الأصلي:
المراسل يقرأ من النص التالي. استخدمه لـ:
1. اختيار أفضل take لكل مشهد (الأكمل والأدق مطابقة للسكريبت)
2. بناء clean_text لكل مشهد — استخدم نص السكريبت المقابل كأساس لـ clean_text
   - اجمع أسطر السكريبت المناسبة لكل مشهد
   - إذا لم تجد فرقاً واضحاً بين التيكات، اختر الأخير

السكريبت:
{script_text}
"""


def _format_segments_for_prompt(segments: list[dict]) -> str:
    """Format transcription segments as numbered lines with timestamps."""
    lines = []
    for i, seg in enumerate(segments):
        start_m, start_s = divmod(seg["start"], 60)
        end_m, end_s = divmod(seg["end"], 60)
        ts = f"[{int(start_m):02d}:{start_s:05.2f} - {int(end_m):02d}:{end_s:05.2f}]"
        lines.append(f"Segment {i}: {ts} {seg['text']}")
    return "\n".join(lines)


def _parse_gemini_response(response_text: str, segments: list[dict]) -> dict:
    """Parse Gemini's JSON response and build scene/clip structures."""
    # Extract JSON from response (handle markdown code blocks)
    text = response_text.strip()
    if text.startswith("```"):
        # Remove ```json ... ```
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

    scenes = []
    selected_clips = []

    for scene_data in data["scenes"]:
        scene_num = scene_data["scene_number"]
        takes = []

        for take_data in scene_data["takes"]:
            start_idx = take_data["start_segment_index"]
            end_idx = take_data["end_segment_index"]

            # Clamp indices
            start_idx = max(0, min(start_idx, len(segments) - 1))
            end_idx = max(start_idx, min(end_idx, len(segments) - 1))

            take_segments = segments[start_idx:end_idx + 1]
            combined_text = " ".join(s["text"] for s in take_segments)

            takes.append({
                "start": take_segments[0]["start"],
                "end": take_segments[-1]["end"],
                "text": combined_text,
            })

        if not takes:
            continue

        # Select the chosen take (default: last one)
        selected_idx = scene_data.get("selected_take", len(takes) - 1)
        selected_idx = max(0, min(selected_idx, len(takes) - 1))
        selected = takes[selected_idx]

        # Use clean_text from Gemini if available, otherwise fall back to raw text
        clean_text = scene_data.get("clean_text", "") or selected["text"]

        scenes.append({
            "scene_number": scene_num,
            "total_takes": len(takes),
            "selected_take": {
                "start": selected["start"],
                "end": selected["end"],
                "text": clean_text,
            },
            "takes": takes,
        })

        selected_clips.append({
            "start": selected["start"],
            "end": selected["end"],
            "shot_number": scene_num,
            "text": clean_text,
        })

    return {
        "scenes": scenes,
        "selected_clips": selected_clips,
        "total_scenes": len(scenes),
        "total_readings": sum(s["total_takes"] for s in scenes),
    }


def detect_scenes_with_gemini(segments: list[dict], api_key: str,
                              script_text: str | None = None) -> dict:
    """
    Use Gemini 2.5 to analyze transcription and detect scenes/takes.

    Args:
        segments: Whisper transcription segments [{"start", "end", "text"}, ...]
        api_key: Google Gemini API key
        script_text: Optional original script text. If provided, Gemini selects
                     the take closest to the script instead of the last take.

    Returns:
        Dict with scenes, selected_clips, total_scenes, total_readings
    """
    if not segments:
        return {"scenes": [], "selected_clips": [], "total_scenes": 0, "total_readings": 0}

    # Build system instruction: add script addendum if script provided
    system = SYSTEM_PROMPT
    if script_text:
        system += SCRIPT_ADDENDUM.format(script_text=script_text)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=system,
    )

    # Build the user prompt with segments
    formatted = _format_segments_for_prompt(segments)
    user_prompt = f"حلل هذه الـ segments وحدد المشاهد والتيكات:\n\n{formatted}"

    log.info("Sending %d segments to Gemini 2.5 for analysis...", len(segments))

    # Call Gemini API
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

            result = _parse_gemini_response(response.text, segments)

            # Extract token usage
            usage = getattr(response, "usage_metadata", None)
            if usage:
                result["token_usage"] = {
                    "input_tokens": getattr(usage, "prompt_token_count", 0),
                    "output_tokens": getattr(usage, "candidates_token_count", 0),
                    "total_tokens": getattr(usage, "total_token_count", 0),
                }
                log.info("Gemini tokens: %d input, %d output, %d total",
                         result["token_usage"]["input_tokens"],
                         result["token_usage"]["output_tokens"],
                         result["token_usage"]["total_tokens"])

            log.info("Gemini detected %d scenes from %d readings",
                     result["total_scenes"], result["total_readings"])
            return result

        except json.JSONDecodeError as e:
            last_error = e
            log.warning("Gemini returned invalid JSON (attempt %d/%d): %s",
                        attempt + 1, max_retries, e)
            continue
        except Exception as e:
            last_error = e
            log.warning("Gemini API error (attempt %d/%d): %s",
                        attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                continue
            break

    raise RuntimeError(f"فشل تحليل Gemini بعد {max_retries} محاولات: {last_error}")
