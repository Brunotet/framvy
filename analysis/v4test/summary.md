# v4test

- id: `v4test`  channel: ?  duration: 90.47s  views: ?  upload: ?
- status: {"video_id": "v4test", "cuts": {"ok": true, "count": 4}, "audio": {"ok": true, "onsets": 124, "sfx_clips": 40}, "result": "ok"}

## Cuts
- {"shots": 4, "mean_s": 22.62, "median_s": 17.25, "p10_s": 7.21, "p90_s": 42.32, "min_s": 6.57, "max_s": 49.4}
- cuts per 10 s window: 0s:1 20s:1 70s:1 80s:1

## Audio
- levels: {"speech_rms_db": null, "gap_rms_db": -19.8, "gap_flatness": 0.221, "music_or_ambience_bed_likely": true, "bed_below_voice_db": null}
- pace: {}
- cuts with an audio hit near the cut: 1 / 3 (median offset -0.15 s)
- sfx candidates saved as clips: 40

- guessed sfx types: {"other transient": 23, "whoosh/swipe (noise sweep)": 5, "click/pop": 11, "boom/impact": 1}

## Contact sheets
One file per 60 s, 6 columns x 5 rows, one frame every 2 s (read left-to-right, top-to-bottom).
sheet_00.jpg, sheet_01.jpg

## First shots
| # | start | dur | words | audio hit | frame |
|---|---|---|---|---|---|
| 1 | 00:00.00 | 25.80 |  |  | s001_0000.25.jpg |
| 2 | 00:25.80 | 49.40 |  |  | s002_0026.05.jpg |
| 3 | 01:15.20 | 6.57 |  |  | s003_0075.45.jpg |
| 4 | 01:21.77 | 8.70 |  | click/pop (-0.15s, x2.55) | s004_0082.02.jpg |