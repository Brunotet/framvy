# video-editor (the "mother" tool)

n8n sends a **script + a scene plan**. This repo does the rest: narrates it with your Chatterbox TTS, generates the
images (batched, credit-safe), edits everything cinematically with HyperFrames, mixes sound effects in sync, and
returns the finished video to n8n. No LLM lives here: your n8n LLM plans, this repo executes.

```
n8n (Gemini plans scenes) --dispatch--> GitHub Actions: narrate -> images -> edit -> render -> upload R2
        ^                                                                  |
        +------------------ callback_url (video_url, meta) <---------------+
```

## 1. Setup (once)
1. Push this repo to GitHub. Add **Actions secrets** (Settings -> Secrets and variables -> Actions):
   `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE` (public bucket URL),
   `SFX_BASE_URL` (= `<R2_PUBLIC_BASE>/sfx`). Optional: `FREESOUND_API_KEY`, `MODAL_TTS_URL`, `QWEN_IMAGE_URL`
   (both default to the endpoints already in the code; set them only if the URLs change).
2. Import `n8n/video-pipeline.workflow.json` into n8n and follow the yellow note inside it.
3. Build the sound library (section 5), then `python scripts/fetch_sfx.py publish`.

## 2. The job n8n sends (script mode)
```json
{
  "job_id": "ch1-001", "channel": "default", "aspect": "9:16", "resolution": "1080p",
  "callback_url": "https://YOUR-N8N/webhook/video-done", "meta": {"topic": "memory"},
  "voiceover": {"script": "Watch this. Boom, the whole city shakes.", "voice": "", "exaggeration": 0.5, "speed": 1.0},
  "scenes": [
    {"text": "Watch this.", "visual": {"type": "image", "prompt": "a calm city skyline at dawn"}},
    {"text": "Boom, the whole city shakes.", "visual": {"type": "text"},
     "popups": [{"text": "BOOM", "word": "Boom"}],
     "sfx": [{"query": "punch impact", "word": "Boom", "align": "peak"}], "transition": "glitch"}
  ]
}
```
- **Scene `text` values must be consecutive slices of `voiceover.script`.** Timing comes from the narration, so
  nothing is ever hand-timed. Pop-ups and SFX use `word` (lands exactly on that spoken word) or `offset` seconds.
- **Subtitles are in sync by construction:** captions use the TTS word timestamps themselves.
- **Voice is one TTS call for the whole script** (same `get_tts_safe` + `assign_timing` logic as your other pipelines).
- Already have audio? Send `voiceover: {"url": ..., "words": [...]}` and scenes with explicit `start`/`end` instead.
- **Aspect ratios:** `aspect` = `9:16` (shorts), `16:9` (long-form), `1:1`, `4:5`, `21:9`...; `resolution` = short side
  (`720p` fast drafts, `1080p`, `4k`). Captions switch to longer lines automatically on wide videos.
  GitHub dispatch inputs cap near 65k characters (~150 scenes). Longer videos: send `job_url` instead of `job_json`.

## 3. Images (credit-safe)
- Channel has `features.images: false` -> **no image calls are ever made**, every scene becomes kinetic text.
- Identical prompts are generated once; results are cached; a failed image becomes a text scene, never a failed video.
- Default = sequential calls that reuse one warm Modal container (cheapest). If your Modal function can accept a list,
  set `image.batch_key: prompts` in `channels/default.yaml` to send **one request for all images**.
- The response parser accepts raw image bytes, base64 anywhere in the JSON, or image URLs. If your endpoint's
  response is unusual, the job log shows a warning with a preview of what came back.

## 4. Render engine: HyperFrames (default)
Scenes compile to a real HyperFrames composition (HTML + one paused GSAP timeline), rendered by its CLI
(Apache-2.0, no per-render fees, no account). If it ever fails the job falls back to the built-in Playwright renderer.
- Transitions: `cut fade whip zoom flash` plus GPU shader transitions `glitch light-leak cinematic-zoom whip-pan
  flash-through-white cross-warp-morph chromatic-split swirl-vortex ripple-waves gravitational-lens domain-warp
  ridged-burn sdf-iris thermal-distortion`. HyperShader allows one contiguous run per video; others become `flash`.
- Cinematic layer: grade, vignette, film grain, letterbox, Ken Burns / push / shake motion, kinetic text, stamp pop-ups.
- Per-channel look lives in `channels/<name>.yaml`; characters in `characters/<name>/` (see its README).
- Local: `pip install -r requirements.txt && npm install && npx hyperframes browser ensure`.

## 5. Sound effects: library, sync, search
**Build it once** (Python + ffmpeg on your PC; Sonniss bundles unzipped, any folder layout):
```
python scripts/fetch_sfx.py ingest --raw "C:\Users\simon\Downloads\Sonniss.com-GDC2026-GameAudioBundle*"
python scripts/fetch_sfx.py search punch        # see what the editor will find
python scripts/fetch_sfx.py stats
python scripts/fetch_sfx.py publish             # uploads to R2 (needs the R2_* variables in your shell)
```
Ingest is additive: run it again when you unzip more bundles. It understands the pack folders and the UCS file names
(`FGHTImpt_4 x Punch, Body 02_344 Audio.wav` -> name "4x Punch, Body", category fight/impact, tags fight impact hit
punch body cinematic) and reads the bundle's .xlsx file list when its columns are recognisable.

**Sync (the part that makes it feel right):**
- Leading/trailing silence is trimmed at ingest and each sound's real **onset, peak and end** are measured.
- Cue `align`: `onset` (sound starts on the cue, default) | `peak` (the loudest hit lands on the cue) | `end` (sound ends on the cue, for risers).
  Use `peak` for hits and `end` for risers; sustained noise has no clear peak.
- A sound never plays past its scene: it is cut with a short fade. `dur` shortens it further. Cues whose scene ends before they can play are skipped with a warning.
- Search prefers sounds whose natural length fits the slot. Fallback chain: library -> live Freesound CC0 -> built-in synthesized sound.
- `out/<job>/credits.json` logs every sound used (id, name, source, license, whether it was cut). No source can guarantee zero Content ID claims; the log tells you what to swap if one appears.
- Keep `License - GDC Game Audio.pdf` from the bundle somewhere safe, and read it once.

## 6. n8n workflow (importable)
`n8n/video-pipeline.workflow.json`: Manual/Webhook start -> **Config & Input** (every setting in one Code node)
-> Gemini scene planner -> job builder (validates that the plan matches the script, caps images, falls back safely)
-> GitHub dispatch; plus the *Render Done* webhook that outputs `video_url` for your upload step.

## Layout
```
editor/      cli, prepare (narration/images/cue timing), voice, images, timeline, hf_compose, sfx*, audio, render, publish
channels/    default.yaml + one yaml per channel     characters/  per-character PNG poses + manifest
scripts/     fetch_sfx.py, seed queries              n8n/         importable workflow
examples/    sample jobs     tests/   smoke.sh + mock_modal.py (fake TTS/image servers for credit-free testing)
```
