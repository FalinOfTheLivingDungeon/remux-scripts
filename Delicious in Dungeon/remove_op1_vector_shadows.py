import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

TARGET_LYRIC = "Sunlight shining through the glass lighting patches of the floor"
NATIVE_SHADOW = r"\shad3\4c&H000000&\4a&HC0&"


def run(args, capture=False):
    return subprocess.run(
        [str(x) for x in args], check=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        text=capture,
    )


def identify(path):
    return json.loads(run(["mkvmerge", "-J", path], True).stdout)


def seconds(value):
    hours, minutes, secs = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(secs)


def repair_ass(source, output):
    lines = source.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    normalized = []
    syntax_changes = 0
    for line in lines:
        updated, markers = re.subn(r"\{=\d+\}", "", line)
        updated, tags = re.subn(
            r"(\\(?:[1-4]?c|[1-4]?a|alpha)&H[0-9A-Fa-f]{2,8})(?=\\|\})",
            r"\1&",
            updated,
        )
        normalized.append(updated)
        syntax_changes += markers + tags
    lines = normalized
    used_styles = set()
    for line in lines:
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", 9)
        if len(fields) == 10:
            used_styles.add(fields[3].strip())
            used_styles.update(name.strip() for name in re.findall(r"\\r([^\\}]+)", fields[9]) if name.strip())
    pruned = []
    for line in lines:
        if line.startswith("Style:"):
            style_name = line[6:].split(",", 1)[0].strip()
            if style_name not in used_styles:
                syntax_changes += 1
                continue
        pruned.append(line)
    lines = pruned
    dialogue = re.compile(r"Dialogue: \d+,([^,]+),([^,]+),")
    lyric_times = []
    for line in lines:
        match = dialogue.match(line)
        if match and TARGET_LYRIC in line:
            lyric_times.append((seconds(match.group(1)), seconds(match.group(2))))
    if not lyric_times:
        output.write_text("".join(lines), encoding="utf-8-sig")
        return 0, 0, syntax_changes > 0

    start = min(x[0] for x in lyric_times)
    end = max(x[1] for x in lyric_times)
    repaired = []
    vectors = native = 0
    for line in lines:
        match = dialogue.match(line)
        if match:
            event_start, event_end = seconds(match.group(1)), seconds(match.group(2))
            overlaps = event_start < end and event_end > start
            if overlaps and r"\p1" in line:
                vectors += 1
                continue
            if overlaps and NATIVE_SHADOW in line:
                line = line.replace(NATIVE_SHADOW, "")
                native += 1
        repaired.append(line)
    output.write_text("".join(repaired), encoding="utf-8-sig")
    return vectors, native, bool(vectors or native or syntax_changes)


def extracted_hashes(container, tracks, directory, prefix):
    if not tracks:
        return {}
    args = ["mkvextract", "tracks", container]
    paths = {}
    for track in tracks:
        path = directory / f"{prefix}_{track['id']}.srt"
        paths[track["id"]] = path
        args.append(f"{track['id']}:{path}")
    run(args)
    return {track_id: hashlib.sha256(path.read_bytes()).digest() for track_id, path in paths.items()}


parser = argparse.ArgumentParser(description="Remove the VLC-overloading OP1 vector shadows in place.")
parser.add_argument("paths", type=Path, nargs="+", help="MKV files or directories containing constructed MKVs")
args = parser.parse_args()

targets = []
for path in args.paths:
    if path.is_file() and path.suffix.lower() == ".mkv":
        targets.append(path)
    elif path.is_dir():
        targets.extend(path.rglob("*.mkv"))
targets = sorted(set(targets))
if not targets:
    parser.error("no MKV files found")
changed_files = changed_tracks = removed_vectors = removed_native = 0
for target in targets:
    if not target.exists():
        continue
    meta = identify(target)
    ass_tracks = [t for t in meta["tracks"] if t["codec"] == "SubStationAlpha"]
    if not ass_tracks:
        continue
    with tempfile.TemporaryDirectory(prefix="op1_shadow_", dir=target.parent) as td:
        work = Path(td)
        extracts = []
        args = ["mkvextract", "tracks", target]
        for track in ass_tracks:
            path = work / f"source_{track['id']}.ass"
            extracts.append(path)
            args.append(f"{track['id']}:{path}")
        run(args)

        cleaned = []
        results = []
        for track, source in zip(ass_tracks, extracts):
            output = work / f"clean_{track['id']}.ass"
            result = repair_ass(source, output)
            cleaned.append(output)
            results.append(result)
        if not any(result[2] for result in results):
            continue

        non_ass_subs = [t for t in meta["tracks"] if t["type"] == "subtitles" and t["codec"] != "SubStationAlpha"]
        before_srt = extracted_hashes(target, non_ass_subs, work, "before")
        temp = target.with_suffix(".op1-shadow.tmp.mkv")
        if temp.exists():
            temp.unlink()
        mux = ["mkvmerge", "-o", temp]
        if non_ass_subs:
            mux += ["--subtitle-tracks", ",".join(str(t["id"]) for t in non_ass_subs), target]
        else:
            mux += ["--no-subtitles", target]
        ass_inputs = {}
        for input_index, (track, path) in enumerate(zip(ass_tracks, cleaned), start=1):
            ass_inputs[track["id"]] = input_index
            props = track.get("properties", {})
            mux += [
                "--language", f"0:{props.get('language_ietf', props.get('language', 'en'))}",
                "--track-name", f"0:{props.get('track_name', '')}",
                "--default-track-flag", f"0:{'yes' if props.get('default_track') else 'no'}",
                "--forced-display-flag", f"0:{'yes' if props.get('forced_track') else 'no'}",
                path,
            ]
        order = [f"{ass_inputs[t['id']]}:0" if t["id"] in ass_inputs else f"0:{t['id']}" for t in meta["tracks"]]
        mux[3:3] = ["--track-order", ",".join(order)]
        run(mux)

        after = identify(temp)
        if len([t for t in after["tracks"] if t["codec"] == "SubStationAlpha"]) != len(ass_tracks):
            raise RuntimeError(f"{target.name}: ASS track count changed")
        if [(a["file_name"], a["size"]) for a in after.get("attachments", [])] != [(a["file_name"], a["size"]) for a in meta.get("attachments", [])]:
            raise RuntimeError(f"{target.name}: attachments changed")
        after_srt = extracted_hashes(temp, non_ass_subs, work, "after")
        if before_srt != after_srt:
            raise RuntimeError(f"{target.name}: retained SRT content changed")
        temp.replace(target)

        changed_files += 1
        changed_tracks += sum(result[2] for result in results)
        removed_vectors += sum(result[0] for result in results)
        removed_native += sum(result[1] for result in results)
        print(f"Updated {target.name}", flush=True)

print(
    f"Updated {changed_files} files / {changed_tracks} ASS tracks; removed "
    f"{removed_vectors} vector-shadow events and {removed_native} native-shadow tags."
)
