import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
DRIFTS = HERE / "FINAL_TRACK_DRIFTS.csv"
NC_TIMING = HERE / "NC_TIMING.csv"
EPISODE_RE = re.compile(r"S01E(\d{2})", re.IGNORECASE)
NC_NAMES = {
    "OP1": "NC Opening 1.mkv",
    "ED1": "NC Ending 1.mkv",
    "OP2": "NC Opening 2 Version 1.mkv",
    "ED2": "NC Ending 2 Version 1.mkv",
    "OP2v2": "NC Opening 2 Version 2.mkv",
    "ED2v2": "NC Ending 2 Version 2.mkv",
}


def run(command, capture=False):
    return subprocess.run(
        [str(x) for x in command],
        check=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=capture,
    )


def identify(path):
    return json.loads(run(["mkvmerge", "-J", path], True).stdout)


def episode_index(directory):
    result = {}
    for path in directory.rglob("*.mkv"):
        match = EPISODE_RE.search(path.name)
        if match:
            episode = int(match.group(1))
            if episode in result:
                raise RuntimeError(f"Multiple E{episode:02d} files below {directory}")
            result[episode] = path
    return result


def parse_episode_selection(value):
    if not value:
        return list(range(1, 25))
    selected = set()
    for part in value.split(","):
        if "-" in part:
            start, end = (int(x) for x in part.split("-", 1))
            selected.update(range(start, end + 1))
        else:
            selected.add(int(part))
    if not selected or min(selected) < 1 or max(selected) > 24:
        raise argparse.ArgumentTypeError("episodes must be within 1-24")
    return sorted(selected)


def load_drifts():
    grouped = defaultdict(list)
    with DRIFTS.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            row["episode"] = int(row["episode"])
            row["source_track_id"] = int(row["source_track_id"]) if row["source_track_id"] else None
            row["applied_shift_ms"] = int(row["applied_shift_ms"])
            grouped[row["episode"]].append(row)
    return grouped


def credited_name(row, credits):
    name = row["track_name"]
    if row["action"] == "unchanged_timing":
        return name
    if row["action"] == "added":
        source = credits.get("stereo")
        return f"Japanese 2.0 (Blu-ray) [{source}; FALIN Added]" if source else "Japanese 2.0 (Blu-ray) [FALIN Added]"
    if row["type"] == "audio" or row["codec"] == "SubRip/SRT":
        source = credits.get("streaming")
    elif "Dub" in name:
        source = credits.get("dubtitles")
    else:
        source = credits.get("styled")
    return f"{name} [{source}; FALIN Modified]" if source else f"{name} [FALIN Modified]"


def find_stereo_track(meta, episode):
    matches = []
    for track in meta["tracks"]:
        props = track.get("properties", {})
        language = props.get("language_ietf", props.get("language"))
        if track["type"] == "audio" and language == "ja" and props.get("audio_channels") == 2:
            matches.append(track)
    if len(matches) != 1:
        raise RuntimeError(f"E{episode:02d}: expected one Japanese stereo track in stereo source, found {len(matches)}")
    return matches[0]


def build_episode(episode, base_source, stereo_source, rows, destination, font_dir=None, credits=None):
    credits = credits or {}
    source_meta = identify(base_source)
    source_ids = {track["id"] for track in source_meta["tracks"]}
    manifest_ids = {row["source_track_id"] for row in rows if row["source_track_id"] is not None}
    missing = manifest_ids - source_ids
    if missing:
        raise RuntimeError(f"E{episode:02d}: tracks missing from base source: {sorted(missing)}")

    stereo = find_stereo_track(identify(stereo_source), episode)
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = ["mkvmerge", "-o", destination, "--title", f"S01E{episode:02d} [FALIN]"]

    for row in rows:
        track_id = row["source_track_id"]
        if track_id is None:
            continue
        if row["applied_shift_ms"]:
            command += ["--sync", f"{track_id}:{row['applied_shift_ms']}"]
        command += ["--track-name", f"{track_id}:{credited_name(row, credits)}"]
    command += ["--no-attachments", base_source]

    stereo_id = stereo["id"]
    command += [
        "--no-video", "--no-subtitles", "--no-attachments", "--no-chapters",
        "--audio-tracks", str(stereo_id),
        "--language", f"{stereo_id}:ja",
        "--track-name", f"{stereo_id}:{credited_name(next(row for row in rows if row['action'] == 'added'), credits)}",
        "--default-track-flag", f"{stereo_id}:no",
        stereo_source,
    ]

    order = []
    for track in source_meta["tracks"]:
        order.append(f"0:{track['id']}")
        if track["type"] == "audio" and track["id"] == 1:
            order.append(f"1:{stereo_id}")
    command[3:3] = ["--track-order", ",".join(order)]

    with tempfile.TemporaryDirectory(prefix=f"E{episode:02d}_fonts_") as temp_name:
        temp = Path(temp_name)
        unique = {}
        for attachment in source_meta.get("attachments", []):
            if not attachment.get("content_type", "").startswith("font/"):
                continue
            unique.setdefault((attachment["file_name"].lower(), attachment["size"]), attachment)
        fonts = []
        for attachment in unique.values():
            path = temp / attachment["file_name"]
            run(["mkvextract", "attachments", base_source, f"{attachment['id']}:{path}"])
            fonts.append((attachment["file_name"], path))
        if episode == 1:
            candidates = list(font_dir.glob("Pokoljaro.*")) if font_dir else []
            if len(candidates) != 1:
                raise RuntimeError("E01 requires exactly one Pokoljaro font in --font-dir")
            fonts.append((candidates[0].name, candidates[0]))
        for name, path in fonts:
            command += ["--attachment-name", name, "--attach-file", path]
        run(command)


def ass_time(value):
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def format_ass_time(value):
    value = max(0.0, value)
    hours = int(value // 3600)
    value -= hours * 3600
    minutes = int(value // 60)
    seconds = value - minutes * 60
    return f"{hours}:{minutes:02d}:{seconds:05.2f}"


def retime_ass(source, destination, origin, adjustment, duration):
    output = []
    dialogue = re.compile(r"^(Dialogue: \d+,)([^,]+),([^,]+),(.*)$")
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        match = dialogue.match(line)
        if not match:
            output.append(line)
            continue
        start = ass_time(match.group(2)) - origin + adjustment
        end = ass_time(match.group(3)) - origin + adjustment
        if end <= 0 or start >= duration:
            continue
        start, end = max(0, start), min(duration, end)
        output.append(f"{match.group(1)}{format_ass_time(start)},{format_ass_time(end)},{match.group(4)}")
    destination.write_text("\n".join(output) + "\n", encoding="utf-8-sig")


def find_nc_source(base_root, clip):
    token = clip.replace("v2", "v2")
    candidates = [p for p in base_root.rglob("*.mkv") if not EPISODE_RE.search(p.name)]
    exact = [p for p in candidates if re.search(rf" - {re.escape(token)} ", p.name, re.IGNORECASE)]
    if len(exact) != 1:
        raise RuntimeError(f"{clip}: expected one base NC source, found {len(exact)}")
    return exact[0]


def build_nc(row, base_root, built_episode, destination):
    clip = row["clip"]
    nc_source = find_nc_source(base_root, clip)
    episode_meta = identify(built_episode)
    signs = [
        track for track in episode_meta["tracks"]
        if track["codec"] == "SubStationAlpha" and "Signs" in track.get("properties", {}).get("track_name", "")
    ]
    if len(signs) != 1:
        raise RuntimeError(f"{clip}: expected one Signs & Songs ASS track, found {len(signs)}")

    duration = float(identify(nc_source)["container"]["properties"]["duration"]) / 1_000_000_000
    with tempfile.TemporaryDirectory(prefix=f"{clip}_") as temp_name:
        temp = Path(temp_name)
        source_ass = temp / "source.ass"
        final_ass = temp / "song.ass"
        run(["mkvextract", "tracks", built_episode, f"{signs[0]['id']}:{source_ass}"])
        retime_ass(
            source_ass,
            final_ass,
            float(row["episode_to_nc_origin_seconds"]),
            float(row["additional_subtitle_shift_seconds"]),
            duration,
        )
        wanted_font = re.sub(r"[^a-z0-9]", "", row["rendered_font"].lower())
        font_matches = []
        for attachment in episode_meta.get("attachments", []):
            normalized = re.sub(r"[^a-z0-9]", "", attachment["file_name"].lower())
            if wanted_font in normalized or normalized in wanted_font:
                font_matches.append(attachment)
        unique_fonts = {(item["file_name"], item["size"]): item for item in font_matches}
        if len(unique_fonts) != 1:
            raise RuntimeError(f"{clip}: expected one attachment for {row['rendered_font']}, found {len(unique_fonts)}")
        attachment = next(iter(unique_fonts.values()))
        font_path = temp / attachment["file_name"]
        run(["mkvextract", "attachments", built_episode, f"{attachment['id']}:{font_path}"])
        command = [
            "mkvmerge", "-o", destination,
            "--title", f"{clip} [FALIN]",
            "--no-subtitles", "--no-attachments", nc_source,
            "--language", "0:en", "--track-name", "0:English (Songs) [FALIN Modified]",
            "--default-track-flag", "0:yes", final_ass,
            "--attachment-name", attachment["file_name"], "--attach-file", font_path,
        ]
        run(command)


def main():
    parser = argparse.ArgumentParser(description="Construct the FALIN Season 1 release from untouched sources.")
    parser.add_argument("base_source", type=Path, help="Untouched base release directory")
    parser.add_argument("stereo_source", type=Path, help="Untouched release containing Japanese stereo")
    parser.add_argument("output", type=Path, help="New release directory")
    parser.add_argument("--font-dir", type=Path, help="Directory containing supplementary Pokoljaro font for E01")
    parser.add_argument("--streaming-credit", default="", help="Optional source label for streaming tracks")
    parser.add_argument("--styled-credit", default="", help="Optional source label for styled subtitles")
    parser.add_argument("--dubtitles-credit", default="", help="Optional source label for dubtitles")
    parser.add_argument("--stereo-credit", default="", help="Optional source label for Japanese stereo")
    parser.add_argument("--episodes", help="Comma-separated episodes/ranges, e.g. 1,4-6")
    parser.add_argument("--skip-nc", action="store_true", help="Do not construct NC extras")
    parser.add_argument("--nc", help="Comma-separated NC clips to build, e.g. OP1,ED1 (default: all)")
    args = parser.parse_args()

    for tool in ("mkvmerge", "mkvextract"):
        if shutil.which(tool) is None:
            parser.error(f"required executable not found: {tool}")
    for path, label in ((args.base_source, "base source"), (args.stereo_source, "stereo source")):
        if not path.is_dir():
            parser.error(f"{label} directory does not exist: {path}")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output directory must be absent or empty")

    episodes = parse_episode_selection(args.episodes)
    base_files = episode_index(args.base_source)
    stereo_files = episode_index(args.stereo_source)
    drifts = load_drifts()
    missing = [episode for episode in episodes if episode not in base_files or episode not in stereo_files or episode not in drifts]
    if missing:
        parser.error(f"missing source or manifest episodes: {missing}")

    credits = {
        "streaming": args.streaming_credit,
        "styled": args.styled_credit,
        "dubtitles": args.dubtitles_credit,
        "stereo": args.stereo_credit,
    }
    season = args.output / "Season 01"
    built = {}
    for episode in episodes:
        target = season / f"Delicious.in.Dungeon.S01E{episode:02d}.1080p.BluRay.Multi-Audio.Opus.5.1.AV1-FALIN.mkv"
        print(f"Building E{episode:02d}", flush=True)
        build_episode(episode, base_files[episode], stereo_files[episode], drifts[episode], target, args.font_dir, credits)
        built[episode] = target

    if not args.skip_nc:
        timing_rows = list(csv.DictReader(NC_TIMING.open(newline="", encoding="utf-8-sig")))
        if args.nc:
            requested = {value.strip() for value in args.nc.split(",") if value.strip()}
            unknown = requested - NC_NAMES.keys()
            if unknown:
                parser.error(f"unknown NC clips: {sorted(unknown)}")
            timing_rows = [row for row in timing_rows if row["clip"] in requested]
        required = {int(row["representative_episode"]) for row in timing_rows}
        unavailable = required - built.keys()
        if unavailable:
            parser.error(f"NC construction requires representative episodes: {sorted(unavailable)}")
        extras = season / "extras"
        extras.mkdir(parents=True, exist_ok=True)
        for row in timing_rows:
            clip = row["clip"]
            print(f"Building {clip}", flush=True)
            build_nc(row, args.base_source, built[int(row["representative_episode"])], extras / NC_NAMES[clip])

    run([sys.executable, HERE / "remove_op1_vector_shadows.py", season])

    nfo = HERE / "tvshow.example.nfo"
    if nfo.exists():
        shutil.copy2(nfo, args.output / "tvshow.nfo")
    print(f"Built release at {args.output}")


if __name__ == "__main__":
    main()
