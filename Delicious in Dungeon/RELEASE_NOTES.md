# Delicious in Dungeon Season 1 — Technical release notes

This release contains 24 episodes and six non-credit opening/ending clips. The 10-bit Blu-ray AV1 video streams were retained without re-encoding.

Named source and contributor information is separated into [`SOURCES.md`](SOURCES.md).

## Video and Japanese audio

- The Blu-ray AV1 video was compared against an independent Blu-ray reference and found aligned.
- Japanese 5.1 audio was found aligned and retained unchanged.
- Japanese 2.0 Blu-ray audio was added to every episode immediately after Japanese 5.1.
- The stereo track is Japanese, non-default, and effectively zero-offset relative to the aligned Blu-ray material.

## Multilingual audio correction

Every non-Japanese dub was checked individually rather than receiving one blind season-wide shift. Exact applied values are stored per episode and track in [`FINAL_TRACK_DRIFTS.csv`](FINAL_TRACK_DRIFTS.csv).

Important localized exceptions include:

- E16 Thai: `+224 ms`, versus English at `+128 ms` — a `96 ms` relative exception.
- E20 Spanish (Spain): `-164 ms`, versus English at `-32 ms` — a `132 ms` relative exception.

These exceptions are why the release does not use one global multilingual audio offset.

## Multilingual subtitle correction

- All multilingual SRT tracks were retained.
- Final timing is recorded per episode and track in `FINAL_TRACK_DRIFTS.csv`.
- Exactly four styled English ASS variants remain in every episode:
  - English
  - English Dubtitles
  - English Signs & Songs
  - English Honorifics

## OP1 VLC subtitle correction

VLC flickered during E01 around `24:04.360–24:08.322`, while mpv rendered the same section normally. The dense animated karaoke text was retained; it was not flattened or removed. The four animated ASS tracks retain their E01 `-40 ms` timing correction.

The automation output contained non-standard ASS syntax. The repair normalized 6,968 color tags and 7,256 alpha tags and removed 10,316 editor-only extradata markers.

Comparison with later motion-text shots isolated the VLC problem to rendering load: the affected four-second section refreshed up to eleven large blurred vector-shadow drawings plus moving text about every 40 ms, reaching fourteen simultaneous events and roughly 21 KB in a single vector event. Later motion shots are materially lighter.

The same lyric section was repaired wherever OP1 occurs: E01–E13 and the NC OP1 clip. Only the overloaded vector-shadow events in that section were removed. Moving text, other existing shadow styling, and animation outside the section remain untouched. Detection is based on lyric content rather than absolute episode timestamps.

## ASS style and font optimization

ASS attachments were audited using the effective font state at each visible text span rather than retaining every font merely named by a style or override.

The analysis accounts for:

- Base style fonts
- Inline `\fn` font changes
- `\r` style resets
- Vector drawing mode through `\p`
- Animated font transitions through `\t(\fn...)`
- Font overrides replaced before any glyph is rendered

The final episodes contain only fonts that render visible text. Duplicate fonts, dormant fonts, vector-only font references, cover art, and other non-font attachments were removed.

Specific findings:

- E01 Pokoljaro genuinely renders the “please / pick up / after / yourself” sign and remains embedded.
- E01 Arial is overridden before visible text or used by vector-only events, so it was removed.
- E02 Cutewritten is replaced by Rabiohead before text appears, so it was removed.

## NC opening and ending clips

The NC video and Japanese audio streams were retained unchanged. Each clip received exactly one English styled-song ASS track extracted from a version-matched episode and retimed to the NC timeline.

Version mapping:

- OP1: episodes E02–E13; E01 uses the OP1 sequence at the end rather than as a standard opening.
- ED1: episodes E01–E12.
- OP2 and ED2: episodes E14–E19.
- OP2v2 and ED2v2: episodes E20–E24.
- E23 has no ED.

Only the font rendered by each song track is attached:

- OP1, OP2, OP2v2: Angie-Bold
- ED1, ED2, ED2v2: Ameretto

Representative episodes, episode-to-NC origins, and additional subtitle shifts are stored in [`NC_TIMING.csv`](NC_TIMING.csv). ED1 includes an additional one-frame subtitle delay of `1001/24000` seconds, approximately `41.708 ms`.

## Exact drift manifest

[`FINAL_TRACK_DRIFTS.csv`](FINAL_TRACK_DRIFTS.csv) contains 1,599 rows covering the final audio and subtitle tracks across E01–E24.

Columns:

- `episode`: episode number.
- `final_track_id`: track ID in the final MKV.
- `type`: audio or subtitles.
- `codec`: Matroska-reported codec.
- `language`: final IETF language value.
- `track_name`: final track name.
- `source_track_id`: matching track ID in the source episode; blank for added Japanese stereo.
- `action`: whether timing changed, remained unchanged, or the track was added.
- `applied_shift_ms`: final timestamp minus source timestamp; positive values are later.
- `packet_matches`: number of unique encoded packets supporting the measurement.
- `median_spread_ms`: median absolute spread around the recovered shift.

The manifest records:

- 1,503 non-zero timing corrections.
- 72 tracks with unchanged timing.
- 24 added Japanese stereo tracks.
- Zero matched-source rows without packet evidence.

## Source-only reconstruction

`build_release.py` consumes untouched base and Japanese-stereo source directories, `FINAL_TRACK_DRIFTS.csv`, and `NC_TIMING.csv`. It does not read or compare against an existing finished release.

The constructor validates the expected episode and track layout, applies each recorded track shift, inserts Japanese stereo, rebuilds unique font attachments, constructs the six NC extras from their representative episode song track, applies the OP1 compatibility transformation, and writes the series NFO. E01 additionally requires the externally supplied Pokoljaro font named in the local source documentation.

`remove_op1_vector_shadows.py` accepts explicit MKV files or directories and is invoked on the newly constructed output. It has no fixed release-folder dependency.
