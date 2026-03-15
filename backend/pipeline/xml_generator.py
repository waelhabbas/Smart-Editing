"""
Generate FCP 7 XML (Final Cut Pro XML) for import into Adobe Premiere Pro.
Composable functions for base timeline, B-roll overlay, and soundbite insertion.
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path
from urllib.parse import quote
import subprocess
import json
import logging

log = logging.getLogger(__name__)


def get_video_info(video_path: str) -> dict:
    """Get video metadata using FFprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", "-show_format",
                video_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        info = json.loads(result.stdout)

        video_stream = None
        audio_stream = None
        for stream in info.get("streams", []):
            if stream["codec_type"] == "video" and video_stream is None:
                video_stream = stream
            elif stream["codec_type"] == "audio" and audio_stream is None:
                audio_stream = stream

        fps_str = video_stream.get("r_frame_rate", "30/1") if video_stream else "30/1"
        fps_parts = fps_str.split("/")
        fps_num = int(fps_parts[0])
        fps_den = int(fps_parts[1]) if len(fps_parts) > 1 else 1
        fps = fps_num / fps_den

        ntsc = abs(fps - round(fps)) > 0.01
        timebase = round(fps)

        width = int(video_stream.get("width", 1920)) if video_stream else 1920
        height = int(video_stream.get("height", 1080)) if video_stream else 1080
        duration = float(info.get("format", {}).get("duration", 0))

        audio_rate = int(audio_stream.get("sample_rate", 48000)) if audio_stream else 48000
        audio_channels = int(audio_stream.get("channels", 2)) if audio_stream else 2

        return {
            "width": width,
            "height": height,
            "fps": fps,
            "timebase": timebase,
            "ntsc": ntsc,
            "duration": duration,
            "audio_rate": audio_rate,
            "audio_channels": audio_channels,
        }
    except Exception:
        return {
            "width": 1920, "height": 1080,
            "fps": 30.0, "timebase": 30, "ntsc": False,
            "duration": 0, "audio_rate": 48000, "audio_channels": 2,
        }


def _seconds_to_frames(seconds: float, timebase: int) -> int:
    """Convert seconds to frame count."""
    return round(seconds * timebase)


def _path_to_url(file_path: str) -> str:
    """Convert a local file path to Premiere Pro compatible file URL.

    Premiere Pro expects: file://localhost/C%3a/path/to/file.mp4
    (not file:///C:/path/to/file.mp4 from Path.as_uri())
    """
    p = Path(file_path).resolve()
    # Build URL: drive letter with encoded colon + forward-slash path
    drive = p.drive  # e.g. "C:"
    rest = p.as_posix()[len(drive):]  # e.g. "/Users/97431/..."
    encoded_drive = drive[0] + "%3a"  # e.g. "C%3a"
    # Encode path segments but keep forward slashes
    encoded_rest = quote(rest, safe="/")
    return f"file://localhost/{encoded_drive}{encoded_rest}"


def _write_xml(root: ET.Element, output_path: str):
    """Write XML element tree to file with DOCTYPE and pretty printing."""
    xml_str = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(xml_str)
    pretty_xml = dom.toprettyxml(indent="  ", encoding="UTF-8")

    lines = pretty_xml.decode("UTF-8").split("\n")
    # Strip blank lines that toprettyxml adds (they accumulate on re-parse)
    lines = [line for line in lines if line.strip()]
    lines.insert(1, '<!DOCTYPE xmeml>')
    final_xml = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_xml)


def generate_base_xml(
    video_path: str,
    clips: list[dict],
    output_path: str,
    video_info: dict = None,
    sequence_name: str = "Smart Edit",
) -> str:
    """
    Generate base FCP7 XML with V1 video + A1 audio tracks.

    Args:
        video_path: Absolute path to the source video file.
        clips: List of clips with start, end, shot_number, text, timeline_start, timeline_end.
        output_path: Where to save the XML file.
        video_info: Pre-computed video info (optional, will probe if None).
        sequence_name: Name for the sequence in Premiere.

    Returns:
        Path to the generated XML file.
    """
    if video_info is None:
        video_info = get_video_info(video_path)

    tb = video_info["timebase"]
    ntsc = video_info["ntsc"]

    total_duration_sec = sum(c["end"] - c["start"] for c in clips)
    total_frames = _seconds_to_frames(total_duration_sec, tb)

    video_file_url = _path_to_url(video_path)
    video_filename = Path(video_path).name
    source_duration_frames = _seconds_to_frames(video_info["duration"], tb)

    # Build XML
    xmeml = ET.Element("xmeml", version="5")
    sequence = ET.SubElement(xmeml, "sequence", id="sequence-1")
    ET.SubElement(sequence, "name").text = sequence_name
    ET.SubElement(sequence, "duration").text = str(total_frames)

    rate = ET.SubElement(sequence, "rate")
    ET.SubElement(rate, "timebase").text = str(tb)
    ET.SubElement(rate, "ntsc").text = "TRUE" if ntsc else "FALSE"

    timecode = ET.SubElement(sequence, "timecode")
    tc_rate = ET.SubElement(timecode, "rate")
    ET.SubElement(tc_rate, "timebase").text = str(tb)
    ET.SubElement(tc_rate, "ntsc").text = "TRUE" if ntsc else "FALSE"
    ET.SubElement(timecode, "string").text = "00:00:00:00"
    ET.SubElement(timecode, "frame").text = "0"
    ET.SubElement(timecode, "displayformat").text = "NDF"

    media = ET.SubElement(sequence, "media")

    # === VIDEO TRACK (V1) ===
    video = ET.SubElement(media, "video")
    v_format = ET.SubElement(video, "format")
    v_sample = ET.SubElement(v_format, "samplecharacteristics")
    v_rate = ET.SubElement(v_sample, "rate")
    ET.SubElement(v_rate, "timebase").text = str(tb)
    ET.SubElement(v_rate, "ntsc").text = "TRUE" if ntsc else "FALSE"
    ET.SubElement(v_sample, "width").text = str(video_info["width"])
    ET.SubElement(v_sample, "height").text = str(video_info["height"])
    ET.SubElement(v_sample, "anamorphic").text = "FALSE"
    ET.SubElement(v_sample, "pixelaspectratio").text = "Square"
    ET.SubElement(v_sample, "fielddominance").text = "none"

    v_track = ET.SubElement(video, "track")
    timeline_pos = 0

    for i, clip in enumerate(clips):
        clip_in = _seconds_to_frames(clip["start"], tb)
        clip_out = _seconds_to_frames(clip["end"], tb)
        clip_duration = clip_out - clip_in

        shot_num = clip.get("shot_number", i + 1)
        clip_text = clip.get("text", "")
        clip_label = f"Shot {shot_num}"
        if clip_text:
            snippet = clip_text[:40] + ("..." if len(clip_text) > 40 else "")
            clip_label = f"Shot {shot_num}: {snippet}"

        clipitem = ET.SubElement(v_track, "clipitem", id=f"clipitem-{i+1}")
        ET.SubElement(clipitem, "masterclipid").text = "masterclip-1"
        ET.SubElement(clipitem, "name").text = clip_label

        ci_rate = ET.SubElement(clipitem, "rate")
        ET.SubElement(ci_rate, "timebase").text = str(tb)
        ET.SubElement(ci_rate, "ntsc").text = "TRUE" if ntsc else "FALSE"

        ET.SubElement(clipitem, "enabled").text = "TRUE"
        ET.SubElement(clipitem, "duration").text = str(source_duration_frames)
        ET.SubElement(clipitem, "start").text = str(timeline_pos)
        ET.SubElement(clipitem, "end").text = str(timeline_pos + clip_duration)
        ET.SubElement(clipitem, "in").text = str(clip_in)
        ET.SubElement(clipitem, "out").text = str(clip_out)

        if i == 0:
            file_elem = ET.SubElement(clipitem, "file", id="file-1")
            ET.SubElement(file_elem, "name").text = video_filename
            ET.SubElement(file_elem, "pathurl").text = video_file_url
            ET.SubElement(file_elem, "duration").text = str(source_duration_frames)

            f_rate = ET.SubElement(file_elem, "rate")
            ET.SubElement(f_rate, "timebase").text = str(tb)
            ET.SubElement(f_rate, "ntsc").text = "TRUE" if ntsc else "FALSE"

            f_media = ET.SubElement(file_elem, "media")
            f_video = ET.SubElement(f_media, "video")
            f_vs = ET.SubElement(f_video, "samplecharacteristics")
            f_vr = ET.SubElement(f_vs, "rate")
            ET.SubElement(f_vr, "timebase").text = str(tb)
            ET.SubElement(f_vr, "ntsc").text = "TRUE" if ntsc else "FALSE"
            ET.SubElement(f_vs, "width").text = str(video_info["width"])
            ET.SubElement(f_vs, "height").text = str(video_info["height"])

            f_audio = ET.SubElement(f_media, "audio")
            f_as = ET.SubElement(f_audio, "samplecharacteristics")
            ET.SubElement(f_as, "depth").text = "16"
            ET.SubElement(f_as, "samplerate").text = str(video_info["audio_rate"])
        else:
            ET.SubElement(clipitem, "file", id="file-1")

        if clip_text:
            marker = ET.SubElement(clipitem, "marker")
            ET.SubElement(marker, "name").text = f"Shot {shot_num}"
            ET.SubElement(marker, "comment").text = clip_text
            ET.SubElement(marker, "in").text = "0"
            ET.SubElement(marker, "out").text = "-1"

        v_link = ET.SubElement(clipitem, "link")
        ET.SubElement(v_link, "linkclipref").text = f"clipitem-{i+1}"
        ET.SubElement(v_link, "mediatype").text = "video"

        a_link = ET.SubElement(clipitem, "link")
        ET.SubElement(a_link, "linkclipref").text = f"clipitem-a{i+1}"
        ET.SubElement(a_link, "mediatype").text = "audio"

        timeline_pos += clip_duration

    # === AUDIO TRACK (A1) ===
    audio = ET.SubElement(media, "audio")
    a_format = ET.SubElement(audio, "format")
    a_sample = ET.SubElement(a_format, "samplecharacteristics")
    ET.SubElement(a_sample, "depth").text = "16"
    ET.SubElement(a_sample, "samplerate").text = str(video_info["audio_rate"])

    a_track = ET.SubElement(audio, "track")
    timeline_pos = 0

    for i, clip in enumerate(clips):
        clip_in = _seconds_to_frames(clip["start"], tb)
        clip_out = _seconds_to_frames(clip["end"], tb)
        clip_duration = clip_out - clip_in

        clipitem = ET.SubElement(a_track, "clipitem", id=f"clipitem-a{i+1}")
        ET.SubElement(clipitem, "masterclipid").text = "masterclip-1"
        ET.SubElement(clipitem, "name").text = video_filename

        ci_rate = ET.SubElement(clipitem, "rate")
        ET.SubElement(ci_rate, "timebase").text = str(tb)
        ET.SubElement(ci_rate, "ntsc").text = "TRUE" if ntsc else "FALSE"

        ET.SubElement(clipitem, "enabled").text = "TRUE"
        ET.SubElement(clipitem, "duration").text = str(source_duration_frames)
        ET.SubElement(clipitem, "start").text = str(timeline_pos)
        ET.SubElement(clipitem, "end").text = str(timeline_pos + clip_duration)
        ET.SubElement(clipitem, "in").text = str(clip_in)
        ET.SubElement(clipitem, "out").text = str(clip_out)

        ET.SubElement(clipitem, "file", id="file-1")
        timeline_pos += clip_duration

    _write_xml(xmeml, output_path)
    return output_path


def add_broll_track(
    existing_xml_path: str,
    broll_clips: list[dict],
    broll_file_registry: dict,
    output_path: str,
) -> str:
    """
    Add a V2 video track with B-Roll clips (video-only, no audio).

    Args:
        existing_xml_path: Path to base XML.
        broll_clips: List of B-Roll placements with timeline/source frame positions.
        broll_file_registry: Dict mapping filename to {path, info, file_id}.
        output_path: Where to save the updated XML.
    """
    tree = ET.parse(existing_xml_path)
    root = tree.getroot()

    seq_rate = root.find(".//sequence/rate")
    seq_tb = int(seq_rate.find("timebase").text)
    seq_ntsc = seq_rate.find("ntsc").text

    video_elem = root.find(".//sequence/media/video")
    v2_track = ET.SubElement(video_elem, "track")

    defined_file_ids = set()

    for i, clip in enumerate(broll_clips):
        file_id = clip["file_id"]
        broll_filename = clip["broll_filename"]
        reg = broll_file_registry[broll_filename]
        broll_info = reg["info"]
        broll_path = reg["path"]
        broll_duration_frames = _seconds_to_frames(broll_info["duration"], seq_tb)

        clipitem = ET.SubElement(v2_track, "clipitem", id=f"clipitem-broll-{i+1}")
        ET.SubElement(clipitem, "masterclipid").text = f"masterclip-broll-{i+1}"
        ET.SubElement(clipitem, "name").text = f"B-Roll: {broll_filename}"

        ci_rate = ET.SubElement(clipitem, "rate")
        ET.SubElement(ci_rate, "timebase").text = str(seq_tb)
        ET.SubElement(ci_rate, "ntsc").text = seq_ntsc

        ET.SubElement(clipitem, "enabled").text = "TRUE"
        ET.SubElement(clipitem, "duration").text = str(broll_duration_frames)
        ET.SubElement(clipitem, "start").text = str(clip["timeline_start_frames"])
        ET.SubElement(clipitem, "end").text = str(clip["timeline_end_frames"])
        ET.SubElement(clipitem, "in").text = str(clip["source_in_frames"])
        ET.SubElement(clipitem, "out").text = str(clip["source_out_frames"])

        if file_id not in defined_file_ids:
            defined_file_ids.add(file_id)
            file_url = _path_to_url(broll_path)
            file_elem = ET.SubElement(clipitem, "file", id=file_id)
            ET.SubElement(file_elem, "name").text = broll_filename
            ET.SubElement(file_elem, "pathurl").text = file_url
            ET.SubElement(file_elem, "duration").text = str(broll_duration_frames)

            f_rate = ET.SubElement(file_elem, "rate")
            ET.SubElement(f_rate, "timebase").text = str(seq_tb)
            ET.SubElement(f_rate, "ntsc").text = seq_ntsc

            f_media = ET.SubElement(file_elem, "media")
            f_video = ET.SubElement(f_media, "video")
            f_vs = ET.SubElement(f_video, "samplecharacteristics")
            f_vr = ET.SubElement(f_vs, "rate")
            ET.SubElement(f_vr, "timebase").text = str(seq_tb)
            ET.SubElement(f_vr, "ntsc").text = seq_ntsc
            ET.SubElement(f_vs, "width").text = str(broll_info["width"])
            ET.SubElement(f_vs, "height").text = str(broll_info["height"])
        else:
            ET.SubElement(clipitem, "file", id=file_id)

        v_link = ET.SubElement(clipitem, "link")
        ET.SubElement(v_link, "linkclipref").text = f"clipitem-broll-{i+1}"
        ET.SubElement(v_link, "mediatype").text = "video"

    _write_xml(root, output_path)
    return output_path


def add_scale_keyframes(
    existing_xml_path: str,
    output_path: str,
    min_duration_sec: float = 3.0,
    scale_from: float = 100.0,
    scale_to: float = 107.0,
) -> str:
    """
    Add slow zoom-in keyframes to V1 clips.

    Clips longer than min_duration_sec: scale 100→107 (start to end).
    Clips shorter: left unchanged (no keyframes).
    """
    import re

    tree = ET.parse(existing_xml_path)
    root = tree.getroot()

    seq_rate = root.find(".//sequence/rate")
    seq_tb = int(seq_rate.find("timebase").text)

    video_elem = root.find(".//sequence/media/video")
    tracks = video_elem.findall("track")

    # Find V1 track
    v1_track = None
    for track in tracks:
        clips = track.findall("clipitem")
        if not clips:
            continue
        first_id = clips[0].get("id", "")
        if re.match(r"^clipitem-\d+$", first_id):
            v1_track = track
            break

    if v1_track is None:
        _write_xml(root, output_path)
        return output_path

    min_dur_frames = _seconds_to_frames(min_duration_sec, seq_tb)
    count = 0

    for clipitem in v1_track.findall("clipitem"):
        in_frame = int(clipitem.find("in").text)
        out_frame = int(clipitem.find("out").text)
        clip_dur = out_frame - in_frame

        if clip_dur < min_dur_frames:
            continue

        # Create filter: scale 100→107 over full clip duration
        filter_elem = ET.SubElement(clipitem, "filter")
        effect = ET.SubElement(filter_elem, "effect")
        ET.SubElement(effect, "name").text = "Basic Motion"
        ET.SubElement(effect, "effectid").text = "basic"
        ET.SubElement(effect, "effectcategory").text = "motion"
        ET.SubElement(effect, "effecttype").text = "motion"
        ET.SubElement(effect, "mediatype").text = "video"

        param = ET.SubElement(effect, "parameter", authoringApp="PremierePro")
        ET.SubElement(param, "parameterid").text = "scale"
        ET.SubElement(param, "name").text = "Scale"
        ET.SubElement(param, "valuemin").text = "0"
        ET.SubElement(param, "valuemax").text = "1000"
        ET.SubElement(param, "value").text = str(scale_from)

        for when, value in [(in_frame, scale_from), (out_frame, scale_to)]:
            keyframe_el = ET.SubElement(param, "keyframe")
            ET.SubElement(keyframe_el, "when").text = str(when)
            ET.SubElement(keyframe_el, "value").text = str(value)
            interp = ET.SubElement(keyframe_el, "interpolation")
            ET.SubElement(interp, "name").text = "bezier"

        count += 1

    log.info("Added scale keyframes (100→107) to %d V1 clips (>%.1fs)", count, min_duration_sec)

    _write_xml(root, output_path)
    return output_path


def add_transition_track(
    existing_xml_path: str,
    transition_video_path: str,
    output_path: str,
) -> str:
    """
    Add a transition overlay track (V4 alpha video + A3 audio).

    The transition file contains both alpha video and embedded audio (SFX).
    At each cut point, places the transition centered on the cut frame.
    Transition points are detected from:
    - V1 shot boundaries (where shot_number changes)
    - V2 (B-Roll) clip start positions
    - V3 (Soundbite) clip start positions

    Args:
        existing_xml_path: Path to existing XML (after B-Roll/Soundbite/Scale).
        transition_video_path: Path to transition file (.mov with alpha video + embedded audio).
        output_path: Where to save the updated XML.
    """
    import re

    tree = ET.parse(existing_xml_path)
    root = tree.getroot()

    seq_rate = root.find(".//sequence/rate")
    seq_tb = int(seq_rate.find("timebase").text)
    seq_ntsc = seq_rate.find("ntsc").text

    # Get transition info (single file has both video and audio)
    trans_info = get_video_info(transition_video_path)
    trans_dur = _seconds_to_frames(trans_info["duration"], seq_tb)

    if trans_dur <= 0:
        _write_xml(root, output_path)
        return output_path

    video_elem = root.find(".//sequence/media/video")
    audio_elem = root.find(".//sequence/media/audio")
    tracks = video_elem.findall("track")

    # --- Detect transition points ---
    transition_points = set()
    shot_pattern = re.compile(r"^Shot (\d+)")

    # V1: find shot boundaries
    for track in tracks:
        clips = track.findall("clipitem")
        if not clips:
            continue
        first_id = clips[0].get("id", "")
        if not re.match(r"^clipitem-\d+$", first_id):
            continue

        shot_ends = {}
        for clip in clips:
            name = clip.find("name")
            if name is None or name.text is None:
                continue
            m = shot_pattern.match(name.text)
            if not m:
                continue
            shot_num = int(m.group(1))
            end_frame = int(clip.find("end").text)
            shot_ends[shot_num] = end_frame

        for end_frame in shot_ends.values():
            transition_points.add(end_frame)
        break

    # V2 (B-Roll): clip start positions
    for track in tracks:
        clips = track.findall("clipitem")
        if not clips:
            continue
        first_id = clips[0].get("id", "")
        if not first_id.startswith("clipitem-broll-"):
            continue
        for clip in clips:
            start_frame = int(clip.find("start").text)
            transition_points.add(start_frame)

    # V3 (Soundbite): clip start positions
    for track in tracks:
        clips = track.findall("clipitem")
        if not clips:
            continue
        first_id = clips[0].get("id", "")
        if not first_id.startswith("clipitem-sb-"):
            continue
        for clip in clips:
            start_frame = int(clip.find("start").text)
            transition_points.add(start_frame)

    transition_points.discard(0)
    sorted_points = sorted(transition_points)

    if not sorted_points:
        _write_xml(root, output_path)
        return output_path

    # --- Build placement list, skip overlapping transitions ---
    placements = []
    prev_end = -1

    for point in sorted_points:
        # Center transition on cut point
        t_start = point - trans_dur // 2
        t_in = 0
        if t_start < 0:
            t_in = -t_start
            t_start = 0
        t_end = t_start + (trans_dur - t_in)

        # Check overlap with previous placement
        if t_start < prev_end:
            continue

        placements.append({
            "point": point,
            "t_start": t_start, "t_end": t_end, "t_in": t_in, "t_out": trans_dur,
        })
        prev_end = t_end

    if not placements:
        _write_xml(root, output_path)
        return output_path

    # --- V4: Transition video track ---
    trans_track = ET.SubElement(video_elem, "track")
    trans_filename = Path(transition_video_path).name
    trans_file_url = _path_to_url(transition_video_path)
    trans_source_dur = _seconds_to_frames(trans_info["duration"], seq_tb)

    for i, pl in enumerate(placements):
        clipitem = ET.SubElement(trans_track, "clipitem", id=f"clipitem-trans-{i+1}")
        ET.SubElement(clipitem, "masterclipid").text = "masterclip-trans-1"
        ET.SubElement(clipitem, "name").text = "Transition"

        ci_rate = ET.SubElement(clipitem, "rate")
        ET.SubElement(ci_rate, "timebase").text = str(seq_tb)
        ET.SubElement(ci_rate, "ntsc").text = seq_ntsc

        ET.SubElement(clipitem, "enabled").text = "TRUE"
        ET.SubElement(clipitem, "duration").text = str(trans_source_dur)
        ET.SubElement(clipitem, "start").text = str(pl["t_start"])
        ET.SubElement(clipitem, "end").text = str(pl["t_end"])
        ET.SubElement(clipitem, "in").text = str(pl["t_in"])
        ET.SubElement(clipitem, "out").text = str(pl["t_out"])

        if i == 0:
            file_elem = ET.SubElement(clipitem, "file", id="file-trans-1")
            ET.SubElement(file_elem, "name").text = trans_filename
            ET.SubElement(file_elem, "pathurl").text = trans_file_url
            ET.SubElement(file_elem, "duration").text = str(trans_source_dur)

            f_rate = ET.SubElement(file_elem, "rate")
            ET.SubElement(f_rate, "timebase").text = str(seq_tb)
            ET.SubElement(f_rate, "ntsc").text = seq_ntsc

            f_media = ET.SubElement(file_elem, "media")
            f_video = ET.SubElement(f_media, "video")
            f_vs = ET.SubElement(f_video, "samplecharacteristics")
            f_vr = ET.SubElement(f_vs, "rate")
            ET.SubElement(f_vr, "timebase").text = str(seq_tb)
            ET.SubElement(f_vr, "ntsc").text = seq_ntsc
            ET.SubElement(f_vs, "width").text = str(trans_info["width"])
            ET.SubElement(f_vs, "height").text = str(trans_info["height"])

            f_audio = ET.SubElement(f_media, "audio")
            f_as = ET.SubElement(f_audio, "samplecharacteristics")
            ET.SubElement(f_as, "depth").text = "16"
            ET.SubElement(f_as, "samplerate").text = str(trans_info.get("audio_rate", 48000))
        else:
            ET.SubElement(clipitem, "file", id="file-trans-1")

        v_link = ET.SubElement(clipitem, "link")
        ET.SubElement(v_link, "linkclipref").text = f"clipitem-trans-{i+1}"
        ET.SubElement(v_link, "mediatype").text = "video"
        a_link = ET.SubElement(clipitem, "link")
        ET.SubElement(a_link, "linkclipref").text = f"clipitem-trans-a{i+1}"
        ET.SubElement(a_link, "mediatype").text = "audio"

    # --- A3: Transition audio track (same file, embedded audio) ---
    sfx_track = ET.SubElement(audio_elem, "track")

    for i, pl in enumerate(placements):
        a_clip = ET.SubElement(sfx_track, "clipitem", id=f"clipitem-trans-a{i+1}")
        ET.SubElement(a_clip, "masterclipid").text = "masterclip-trans-1"
        ET.SubElement(a_clip, "name").text = f"Transition Audio"

        ai_rate = ET.SubElement(a_clip, "rate")
        ET.SubElement(ai_rate, "timebase").text = str(seq_tb)
        ET.SubElement(ai_rate, "ntsc").text = seq_ntsc

        ET.SubElement(a_clip, "enabled").text = "TRUE"
        ET.SubElement(a_clip, "duration").text = str(trans_source_dur)
        ET.SubElement(a_clip, "start").text = str(pl["t_start"])
        ET.SubElement(a_clip, "end").text = str(pl["t_end"])
        ET.SubElement(a_clip, "in").text = str(pl["t_in"])
        ET.SubElement(a_clip, "out").text = str(pl["t_out"])

        # Reference the same file as the video track
        ET.SubElement(a_clip, "file", id="file-trans-1")

    log.info("Added %d transition clips at cut points (V4 + A3)", len(placements))

    _write_xml(root, output_path)
    return output_path


def add_logo_track(
    existing_xml_path: str,
    logo_path: str,
    output_path: str,
) -> str:
    """
    Add a logo image overlay as the topmost video track.

    The logo spans the entire sequence duration as a still frame.
    No size modification - the image is assumed to match the video dimensions.

    Args:
        existing_xml_path: Path to existing XML.
        logo_path: Path to the logo image file (PNG/JPEG).
        output_path: Where to save the updated XML.
    """
    tree = ET.parse(existing_xml_path)
    root = tree.getroot()

    seq_rate = root.find(".//sequence/rate")
    seq_tb = int(seq_rate.find("timebase").text)
    seq_ntsc = seq_rate.find("ntsc").text
    seq_duration = int(root.find(".//sequence/duration").text)

    # Get video dimensions from sequence format
    v_sample = root.find(".//sequence/media/video/format/samplecharacteristics")
    width = v_sample.find("width").text
    height = v_sample.find("height").text

    video_elem = root.find(".//sequence/media/video")

    # Create new track (appended last = topmost layer)
    logo_track = ET.SubElement(video_elem, "track")

    logo_filename = Path(logo_path).name
    file_url = _path_to_url(logo_path)

    clipitem = ET.SubElement(logo_track, "clipitem", id="clipitem-logo-1")
    ET.SubElement(clipitem, "masterclipid").text = "masterclip-logo-1"
    ET.SubElement(clipitem, "name").text = logo_filename

    ci_rate = ET.SubElement(clipitem, "rate")
    ET.SubElement(ci_rate, "timebase").text = str(seq_tb)
    ET.SubElement(ci_rate, "ntsc").text = seq_ntsc

    ET.SubElement(clipitem, "enabled").text = "TRUE"
    ET.SubElement(clipitem, "duration").text = str(seq_duration)
    ET.SubElement(clipitem, "start").text = "0"
    ET.SubElement(clipitem, "end").text = str(seq_duration)
    ET.SubElement(clipitem, "in").text = "0"
    ET.SubElement(clipitem, "out").text = str(seq_duration)

    # Still frame flag - tells Premiere this is a static image
    ET.SubElement(clipitem, "stillframe").text = "TRUE"

    # File element (image - video only, no audio)
    file_elem = ET.SubElement(clipitem, "file", id="file-logo-1")
    ET.SubElement(file_elem, "name").text = logo_filename
    ET.SubElement(file_elem, "pathurl").text = file_url
    ET.SubElement(file_elem, "duration").text = str(seq_duration)

    f_rate = ET.SubElement(file_elem, "rate")
    ET.SubElement(f_rate, "timebase").text = str(seq_tb)
    ET.SubElement(f_rate, "ntsc").text = seq_ntsc

    f_media = ET.SubElement(file_elem, "media")
    f_video = ET.SubElement(f_media, "video")
    f_vs = ET.SubElement(f_video, "samplecharacteristics")
    f_vr = ET.SubElement(f_vs, "rate")
    ET.SubElement(f_vr, "timebase").text = str(seq_tb)
    ET.SubElement(f_vr, "ntsc").text = seq_ntsc
    ET.SubElement(f_vs, "width").text = width
    ET.SubElement(f_vs, "height").text = height

    # Video-only link (like B-Roll)
    v_link = ET.SubElement(clipitem, "link")
    ET.SubElement(v_link, "linkclipref").text = "clipitem-logo-1"
    ET.SubElement(v_link, "mediatype").text = "video"

    log.info("Added logo overlay track: %s (duration: %d frames)", logo_filename, seq_duration)

    _write_xml(root, output_path)
    return output_path


def add_soundbite_with_shift(
    existing_xml_path: str,
    soundbite_clips: list[dict],
    soundbite_file_registry: dict,
    output_path: str,
) -> str:
    """
    Add soundbite clips with timeline shifting.

    Inserts soundbites between scenes, shifting all subsequent clips forward.
    Creates V3 video + A2 audio tracks for soundbites.

    Args:
        existing_xml_path: Path to existing XML (base or with B-Roll).
        soundbite_clips: List of soundbite placements.
        soundbite_file_registry: Dict mapping filename to {path, info, file_id}.
        output_path: Where to save the updated XML.
    """
    tree = ET.parse(existing_xml_path)
    root = tree.getroot()

    seq_rate = root.find(".//sequence/rate")
    seq_tb = int(seq_rate.find("timebase").text)
    seq_ntsc = seq_rate.find("ntsc").text

    sorted_sbs = sorted(soundbite_clips, key=lambda x: x["insertion_point_frames"])

    video_elem = root.find(".//sequence/media/video")
    audio_elem = root.find(".//sequence/media/audio")

    # Shift all existing clips
    for track in video_elem.findall("track") + audio_elem.findall("track"):
        for clipitem in track.findall("clipitem"):
            start_el = clipitem.find("start")
            end_el = clipitem.find("end")
            if start_el is None or end_el is None:
                continue
            clip_start = int(start_el.text)
            shift = sum(
                sb["duration_frames"]
                for sb in sorted_sbs
                if sb["insertion_point_frames"] <= clip_start
            )
            if shift > 0:
                start_el.text = str(clip_start + shift)
                end_el.text = str(int(end_el.text) + shift)

    # Update sequence duration
    seq_duration = root.find(".//sequence/duration")
    total_sb_duration = sum(sb["duration_frames"] for sb in sorted_sbs)
    seq_duration.text = str(int(seq_duration.text) + total_sb_duration)

    # Create V3 + A2 tracks
    v3_track = ET.SubElement(video_elem, "track")
    a2_track = ET.SubElement(audio_elem, "track")

    defined_file_ids = set()

    for i, sb in enumerate(sorted_sbs):
        file_id = sb["file_id"]
        sb_filename = sb["sb_filename"]
        reg = soundbite_file_registry[sb_filename]
        sb_info = reg["info"]
        sb_path = reg["path"]
        sb_source_duration_frames = _seconds_to_frames(sb_info["duration"], seq_tb)

        preceding_shift = sum(sorted_sbs[j]["duration_frames"] for j in range(i))
        tl_start = sb["insertion_point_frames"] + preceding_shift
        tl_end = tl_start + sb["duration_frames"]

        # V3 video clip
        v_clip = ET.SubElement(v3_track, "clipitem", id=f"clipitem-sb-{i+1}")
        ET.SubElement(v_clip, "masterclipid").text = f"masterclip-sb-{i+1}"
        ET.SubElement(v_clip, "name").text = f"Sound Bite: {sb_filename}"

        ci_rate = ET.SubElement(v_clip, "rate")
        ET.SubElement(ci_rate, "timebase").text = str(seq_tb)
        ET.SubElement(ci_rate, "ntsc").text = seq_ntsc

        ET.SubElement(v_clip, "enabled").text = "TRUE"
        ET.SubElement(v_clip, "duration").text = str(sb_source_duration_frames)
        ET.SubElement(v_clip, "start").text = str(tl_start)
        ET.SubElement(v_clip, "end").text = str(tl_end)
        ET.SubElement(v_clip, "in").text = str(sb["source_in_frames"])
        ET.SubElement(v_clip, "out").text = str(sb["source_out_frames"])

        if file_id not in defined_file_ids:
            defined_file_ids.add(file_id)
            file_url = _path_to_url(sb_path)
            file_elem = ET.SubElement(v_clip, "file", id=file_id)
            ET.SubElement(file_elem, "name").text = sb_filename
            ET.SubElement(file_elem, "pathurl").text = file_url
            ET.SubElement(file_elem, "duration").text = str(sb_source_duration_frames)

            f_rate = ET.SubElement(file_elem, "rate")
            ET.SubElement(f_rate, "timebase").text = str(seq_tb)
            ET.SubElement(f_rate, "ntsc").text = seq_ntsc

            f_media = ET.SubElement(file_elem, "media")
            f_video = ET.SubElement(f_media, "video")
            f_vs = ET.SubElement(f_video, "samplecharacteristics")
            f_vr = ET.SubElement(f_vs, "rate")
            ET.SubElement(f_vr, "timebase").text = str(seq_tb)
            ET.SubElement(f_vr, "ntsc").text = seq_ntsc
            ET.SubElement(f_vs, "width").text = str(sb_info["width"])
            ET.SubElement(f_vs, "height").text = str(sb_info["height"])

            f_audio = ET.SubElement(f_media, "audio")
            f_as = ET.SubElement(f_audio, "samplecharacteristics")
            ET.SubElement(f_as, "depth").text = "16"
            ET.SubElement(f_as, "samplerate").text = str(sb_info["audio_rate"])
        else:
            ET.SubElement(v_clip, "file", id=file_id)

        v_link = ET.SubElement(v_clip, "link")
        ET.SubElement(v_link, "linkclipref").text = f"clipitem-sb-{i+1}"
        ET.SubElement(v_link, "mediatype").text = "video"
        a_link = ET.SubElement(v_clip, "link")
        ET.SubElement(a_link, "linkclipref").text = f"clipitem-sb-a{i+1}"
        ET.SubElement(a_link, "mediatype").text = "audio"

        # A2 audio clip
        a_clip = ET.SubElement(a2_track, "clipitem", id=f"clipitem-sb-a{i+1}")
        ET.SubElement(a_clip, "masterclipid").text = f"masterclip-sb-{i+1}"
        ET.SubElement(a_clip, "name").text = sb_filename

        ai_rate = ET.SubElement(a_clip, "rate")
        ET.SubElement(ai_rate, "timebase").text = str(seq_tb)
        ET.SubElement(ai_rate, "ntsc").text = seq_ntsc

        ET.SubElement(a_clip, "enabled").text = "TRUE"
        ET.SubElement(a_clip, "duration").text = str(sb_source_duration_frames)
        ET.SubElement(a_clip, "start").text = str(tl_start)
        ET.SubElement(a_clip, "end").text = str(tl_end)
        ET.SubElement(a_clip, "in").text = str(sb["source_in_frames"])
        ET.SubElement(a_clip, "out").text = str(sb["source_out_frames"])

        ET.SubElement(a_clip, "file", id=file_id)

    _write_xml(root, output_path)
    return output_path


def add_outro_track(
    existing_xml_path: str,
    outro_path: str,
    outro_info: dict,
    output_path: str,
) -> str:
    """
    Add an outro video+audio overlay as the topmost video track.

    The outro is an alpha-channel animation that overlaps the last 2 seconds
    and 7 frames of the timeline. The remaining frames extend the sequence.

    Args:
        existing_xml_path: Path to existing XML.
        outro_path: Path to the outro video file.
        outro_info: Video info dict from get_video_info().
        output_path: Where to save the updated XML.
    """
    tree = ET.parse(existing_xml_path)
    root = tree.getroot()

    seq_rate = root.find(".//sequence/rate")
    seq_tb = int(seq_rate.find("timebase").text)
    seq_ntsc = seq_rate.find("ntsc").text
    seq_duration_el = root.find(".//sequence/duration")
    seq_duration = int(seq_duration_el.text)

    # Alpha overlap: 2 seconds and 7 frames
    overlap_frames = 2 * seq_tb + 7

    # Outro total duration in frames
    outro_duration_frames = _seconds_to_frames(outro_info["duration"], seq_tb)

    # Outro starts before the current sequence end by overlap amount
    outro_start = seq_duration - overlap_frames
    outro_end = outro_start + outro_duration_frames

    # Extend the sequence duration if outro goes beyond
    extension_frames = outro_end - seq_duration
    if extension_frames > 0:
        new_seq_duration = seq_duration + extension_frames
        seq_duration_el.text = str(new_seq_duration)

        # Extend logo clip if it exists to cover the new duration
        video_elem = root.find(".//sequence/media/video")
        for track in video_elem.findall("track"):
            for clipitem in track.findall("clipitem"):
                if clipitem.get("id", "").startswith("clipitem-logo-"):
                    clipitem.find("end").text = str(new_seq_duration)
                    clipitem.find("out").text = str(new_seq_duration)
                    clipitem.find("duration").text = str(new_seq_duration)
                    file_el = clipitem.find("file")
                    if file_el is not None:
                        dur_el = file_el.find("duration")
                        if dur_el is not None:
                            dur_el.text = str(new_seq_duration)
    else:
        video_elem = root.find(".//sequence/media/video")

    # === Outro VIDEO track (topmost layer) ===
    outro_track = ET.SubElement(video_elem, "track")

    outro_filename = Path(outro_path).name
    file_url = _path_to_url(outro_path)

    clipitem = ET.SubElement(outro_track, "clipitem", id="clipitem-outro-1")
    ET.SubElement(clipitem, "masterclipid").text = "masterclip-outro-1"
    ET.SubElement(clipitem, "name").text = f"Outro: {outro_filename}"

    ci_rate = ET.SubElement(clipitem, "rate")
    ET.SubElement(ci_rate, "timebase").text = str(seq_tb)
    ET.SubElement(ci_rate, "ntsc").text = seq_ntsc

    ET.SubElement(clipitem, "enabled").text = "TRUE"
    ET.SubElement(clipitem, "duration").text = str(outro_duration_frames)
    ET.SubElement(clipitem, "start").text = str(outro_start)
    ET.SubElement(clipitem, "end").text = str(outro_end)
    ET.SubElement(clipitem, "in").text = "0"
    ET.SubElement(clipitem, "out").text = str(outro_duration_frames)

    # File definition (video + audio)
    file_elem = ET.SubElement(clipitem, "file", id="file-outro-1")
    ET.SubElement(file_elem, "name").text = outro_filename
    ET.SubElement(file_elem, "pathurl").text = file_url
    ET.SubElement(file_elem, "duration").text = str(outro_duration_frames)

    f_rate = ET.SubElement(file_elem, "rate")
    ET.SubElement(f_rate, "timebase").text = str(seq_tb)
    ET.SubElement(f_rate, "ntsc").text = seq_ntsc

    f_media = ET.SubElement(file_elem, "media")
    f_video = ET.SubElement(f_media, "video")
    f_vs = ET.SubElement(f_video, "samplecharacteristics")
    f_vr = ET.SubElement(f_vs, "rate")
    ET.SubElement(f_vr, "timebase").text = str(seq_tb)
    ET.SubElement(f_vr, "ntsc").text = seq_ntsc
    ET.SubElement(f_vs, "width").text = str(outro_info["width"])
    ET.SubElement(f_vs, "height").text = str(outro_info["height"])

    f_audio = ET.SubElement(f_media, "audio")
    f_as = ET.SubElement(f_audio, "samplecharacteristics")
    ET.SubElement(f_as, "depth").text = "16"
    ET.SubElement(f_as, "samplerate").text = str(outro_info["audio_rate"])

    # Links: video + audio
    v_link = ET.SubElement(clipitem, "link")
    ET.SubElement(v_link, "linkclipref").text = "clipitem-outro-1"
    ET.SubElement(v_link, "mediatype").text = "video"
    a_link = ET.SubElement(clipitem, "link")
    ET.SubElement(a_link, "linkclipref").text = "clipitem-outro-a1"
    ET.SubElement(a_link, "mediatype").text = "audio"

    # === Outro AUDIO track ===
    audio_elem = root.find(".//sequence/media/audio")
    outro_audio_track = ET.SubElement(audio_elem, "track")

    a_clip = ET.SubElement(outro_audio_track, "clipitem", id="clipitem-outro-a1")
    ET.SubElement(a_clip, "masterclipid").text = "masterclip-outro-1"
    ET.SubElement(a_clip, "name").text = outro_filename

    ai_rate = ET.SubElement(a_clip, "rate")
    ET.SubElement(ai_rate, "timebase").text = str(seq_tb)
    ET.SubElement(ai_rate, "ntsc").text = seq_ntsc

    ET.SubElement(a_clip, "enabled").text = "TRUE"
    ET.SubElement(a_clip, "duration").text = str(outro_duration_frames)
    ET.SubElement(a_clip, "start").text = str(outro_start)
    ET.SubElement(a_clip, "end").text = str(outro_end)
    ET.SubElement(a_clip, "in").text = "0"
    ET.SubElement(a_clip, "out").text = str(outro_duration_frames)

    ET.SubElement(a_clip, "file", id="file-outro-1")

    log.info("Added outro track: %s (overlap: %d frames, extension: %d frames)",
             outro_filename, overlap_frames, max(0, extension_frames))

    _write_xml(root, output_path)
    return output_path
