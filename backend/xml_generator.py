"""
Generate FCP 7 XML (Final Cut Pro XML) for import into Adobe Premiere Pro.
Creates a sequence/timeline with clips referencing the original video file.
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path
import subprocess
import json


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

        # Parse frame rate
        fps_str = video_stream.get("r_frame_rate", "30/1") if video_stream else "30/1"
        fps_parts = fps_str.split("/")
        fps_num = int(fps_parts[0])
        fps_den = int(fps_parts[1]) if len(fps_parts) > 1 else 1
        fps = fps_num / fps_den

        # Determine timebase (frames per second as fraction)
        # Common rates: 23.976 (24000/1001), 29.97 (30000/1001), 30, 25, 24
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
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "timebase": 30,
            "ntsc": False,
            "duration": 0,
            "audio_rate": 48000,
            "audio_channels": 2,
        }


def seconds_to_frames(seconds: float, timebase: int) -> int:
    """Convert seconds to frame count."""
    return round(seconds * timebase)


def generate_fcp_xml(
    video_path: str,
    clips: list[dict],
    output_path: str,
    sequence_name: str = "Smart Edit",
) -> str:
    """
    Generate FCP 7 XML file.

    Args:
        video_path: Absolute path to the source video file.
        clips: List of clips [{"start": float, "end": float, "shot_number": int}, ...]
        output_path: Where to save the XML file.
        sequence_name: Name for the sequence in Premiere.

    Returns:
        Path to the generated XML file.
    """
    info = get_video_info(video_path)
    tb = info["timebase"]
    ntsc = info["ntsc"]

    # Calculate total timeline duration
    total_duration_sec = sum(c["end"] - c["start"] for c in clips)
    total_frames = seconds_to_frames(total_duration_sec, tb)

    # Video file reference (convert to file:// URL)
    video_file_url = Path(video_path).as_uri()
    video_filename = Path(video_path).name
    source_duration_frames = seconds_to_frames(info["duration"], tb)

    # Build XML
    xmeml = ET.Element("xmeml", version="4")
    sequence = ET.SubElement(xmeml, "sequence")
    ET.SubElement(sequence, "name").text = sequence_name
    ET.SubElement(sequence, "duration").text = str(total_frames)

    rate = ET.SubElement(sequence, "rate")
    ET.SubElement(rate, "timebase").text = str(tb)
    ET.SubElement(rate, "ntsc").text = "TRUE" if ntsc else "FALSE"

    # Timecode
    timecode = ET.SubElement(sequence, "timecode")
    tc_rate = ET.SubElement(timecode, "rate")
    ET.SubElement(tc_rate, "timebase").text = str(tb)
    ET.SubElement(tc_rate, "ntsc").text = "TRUE" if ntsc else "FALSE"
    ET.SubElement(timecode, "string").text = "00:00:00:00"
    ET.SubElement(timecode, "frame").text = "0"
    ET.SubElement(timecode, "displayformat").text = "NDF"

    # Media
    media = ET.SubElement(sequence, "media")

    # === VIDEO TRACK ===
    video = ET.SubElement(media, "video")
    v_format = ET.SubElement(video, "format")
    v_sample = ET.SubElement(v_format, "samplecharacteristics")
    v_rate = ET.SubElement(v_sample, "rate")
    ET.SubElement(v_rate, "timebase").text = str(tb)
    ET.SubElement(v_rate, "ntsc").text = "TRUE" if ntsc else "FALSE"
    ET.SubElement(v_sample, "width").text = str(info["width"])
    ET.SubElement(v_sample, "height").text = str(info["height"])
    ET.SubElement(v_sample, "anamorphic").text = "FALSE"
    ET.SubElement(v_sample, "pixelaspectratio").text = "Square"
    ET.SubElement(v_sample, "fielddominance").text = "none"

    v_track = ET.SubElement(video, "track")

    timeline_pos = 0  # Current position on timeline in frames

    for i, clip in enumerate(clips):
        clip_in = seconds_to_frames(clip["start"], tb)
        clip_out = seconds_to_frames(clip["end"], tb)
        clip_duration = clip_out - clip_in

        shot_num = clip.get("shot_number", i + 1)
        clip_text = clip.get("text", "")
        # Clip name: "Shot N: first 40 chars of text..."
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
            # First clip: full file definition
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
            ET.SubElement(f_vs, "width").text = str(info["width"])
            ET.SubElement(f_vs, "height").text = str(info["height"])

            f_audio = ET.SubElement(f_media, "audio")
            f_as = ET.SubElement(f_audio, "samplecharacteristics")
            ET.SubElement(f_as, "depth").text = "16"
            ET.SubElement(f_as, "samplerate").text = str(info["audio_rate"])
        else:
            # Subsequent clips: reference only
            ET.SubElement(clipitem, "file", id="file-1")

        # Marker with transcription text
        if clip_text:
            marker = ET.SubElement(clipitem, "marker")
            ET.SubElement(marker, "name").text = f"Shot {shot_num}"
            ET.SubElement(marker, "comment").text = clip_text
            ET.SubElement(marker, "in").text = "0"
            ET.SubElement(marker, "out").text = "-1"

        # Link video and audio
        v_link = ET.SubElement(clipitem, "link")
        ET.SubElement(v_link, "linkclipref").text = f"clipitem-{i+1}"
        ET.SubElement(v_link, "mediatype").text = "video"

        a_link = ET.SubElement(clipitem, "link")
        ET.SubElement(a_link, "linkclipref").text = f"clipitem-a{i+1}"
        ET.SubElement(a_link, "mediatype").text = "audio"

        timeline_pos += clip_duration

    # === AUDIO TRACK ===
    audio = ET.SubElement(media, "audio")
    a_format = ET.SubElement(audio, "format")
    a_sample = ET.SubElement(a_format, "samplecharacteristics")
    ET.SubElement(a_sample, "depth").text = "16"
    ET.SubElement(a_sample, "samplerate").text = str(info["audio_rate"])

    a_track = ET.SubElement(audio, "track")

    timeline_pos = 0
    for i, clip in enumerate(clips):
        clip_in = seconds_to_frames(clip["start"], tb)
        clip_out = seconds_to_frames(clip["end"], tb)
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

        # Reference same file
        file_ref = ET.SubElement(clipitem, "file", id="file-1")

        timeline_pos += clip_duration

    # Write XML
    xml_str = ET.tostring(xmeml, encoding="unicode")
    # Pretty print
    dom = minidom.parseString(xml_str)
    pretty_xml = dom.toprettyxml(indent="  ", encoding="UTF-8")

    # Add DOCTYPE
    lines = pretty_xml.decode("UTF-8").split("\n")
    lines.insert(1, '<!DOCTYPE xmeml>')
    final_xml = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_xml)

    return output_path


def add_broll_to_xml(
    existing_xml_path: str,
    broll_clips: list[dict],
    broll_file_registry: dict,
    output_path: str,
) -> str:
    """
    Parse existing FCP7 XML and add a V2 video track with B-Roll clips.

    B-Roll clips are video-only (no audio track) on a separate layer
    above the reporter's V1 track.

    Args:
        existing_xml_path: Path to the XML generated by generate_fcp_xml.
        broll_clips: List of B-Roll placements:
            [
                {
                    "broll_filename": str,
                    "timeline_start_frames": int,
                    "timeline_end_frames": int,
                    "source_in_frames": int,
                    "source_out_frames": int,
                    "file_id": str,  # e.g. "file-broll-1"
                },
                ...
            ]
        broll_file_registry: Dict mapping filename to file info:
            {
                "filename.mp4": {
                    "path": str,
                    "info": dict (from get_video_info),
                    "file_id": str,
                },
                ...
            }
        output_path: Where to save the updated XML.

    Returns:
        Path to the generated XML file.
    """
    tree = ET.parse(existing_xml_path)
    root = tree.getroot()

    # Read sequence timebase
    seq_rate = root.find(".//sequence/rate")
    seq_tb = int(seq_rate.find("timebase").text)
    seq_ntsc = seq_rate.find("ntsc").text

    # Find the <video> element under <media>
    video_elem = root.find(".//sequence/media/video")

    # Create V2 track
    v2_track = ET.SubElement(video_elem, "track")

    # Track which file IDs have been fully defined (first reference gets full def)
    defined_file_ids = set()

    for i, clip in enumerate(broll_clips):
        file_id = clip["file_id"]
        broll_filename = clip["broll_filename"]
        reg = broll_file_registry[broll_filename]
        broll_info = reg["info"]
        broll_path = reg["path"]
        broll_duration_frames = seconds_to_frames(broll_info["duration"], seq_tb)

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
            # First reference: full file definition
            defined_file_ids.add(file_id)

            file_url = Path(broll_path).as_uri()
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
            # Subsequent reference: ID only
            ET.SubElement(clipitem, "file", id=file_id)

        # Video-only link (no audio link for B-Roll)
        v_link = ET.SubElement(clipitem, "link")
        ET.SubElement(v_link, "linkclipref").text = f"clipitem-broll-{i+1}"
        ET.SubElement(v_link, "mediatype").text = "video"

    # Write updated XML
    xml_str = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(xml_str)
    pretty_xml = dom.toprettyxml(indent="  ", encoding="UTF-8")

    lines = pretty_xml.decode("UTF-8").split("\n")
    lines.insert(1, '<!DOCTYPE xmeml>')
    final_xml = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_xml)

    return output_path
