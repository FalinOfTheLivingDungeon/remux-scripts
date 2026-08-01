# Delicious in Dungeon — Season 1

Source-only reconstruction utilities and timing manifests for the Season 1 remux.

## Build

Requirements: Python 3, MKVToolNix, the untouched base release, the untouched release containing Japanese Blu-ray stereo, and the supplementary Pokoljaro font used by E01.

```text
python build_release.py BASE_SOURCE STEREO_SOURCE OUTPUT --font-dir EXTRA_FONTS
```

The output directory must be absent or empty. The constructor builds all 24 episodes and six NC extras, applies the recorded timing shifts, inserts Japanese stereo, deduplicates font attachments, adds only the required font to each NC clip, repairs the affected OP1 vector shadows, and writes the example series NFO.

Use `--episodes 1,4-6` for a partial episode build, `--skip-nc` to omit extras, or `--nc OP1,ED1` to construct selected extras. Optional credit labels are available through `--streaming-credit`, `--styled-credit`, `--dubtitles-credit`, and `--stereo-credit`.

## Files

- `build_release.py`: constructs the release from untouched source directories.
- `FINAL_TRACK_DRIFTS.csv`: per-episode and per-track timing instructions consumed by the builder.
- `NC_TIMING.csv`: NC source-episode, offset, frame-adjustment, style, and font instructions.
- `remove_op1_vector_shadows.py`: path-independent OP1 compatibility transformation called by the builder.
- `tvshow.example.nfo`: Jellyfin series metadata copied into the constructed release.
- `RELEASE_NOTES.md`: technical methodology and manifest description.

No media files, fonts, credentials, source paths, or source subtitle archives are included.
