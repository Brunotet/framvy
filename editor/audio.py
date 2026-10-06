"""Mix voiceover + music (ducked under the voice) + sfx into one stereo track."""
from __future__ import annotations
from pathlib import Path
from .util import run


def mix_audio(out: Path, duration: float, voice, music, voice_gain: float, music_gain: float, sfx: list[dict]):
    inputs: list[str] = []
    chains: list[str] = []
    labels: list[str] = []
    idx = 0
    norm = "aformat=sample_fmts=fltp:channel_layouts=stereo,aresample=44100"

    voice_label = None
    if voice:
        inputs += ["-i", str(voice)]
        chains.append(f"[{idx}:a]{norm},volume={voice_gain}[vo]")
        idx += 1
        voice_label = "vo"

    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        chains.append(f"[{idx}:a]{norm},atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:d=0.6,afade=t=out:st={max(0, duration - 1.0):.3f}:d=1.0,volume={music_gain}[mus]")
        idx += 1
        if voice_label:  # duck music while the voice speaks
            chains.append("[vo]asplit=2[vo_a][vo_b]")
            chains.append("[mus][vo_b]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=450[musd]")
            labels.append("musd")
            voice_label = "vo_a"
        else:
            labels.append("mus")

    if voice_label:
        labels.append(voice_label)

    for n, cue in enumerate(sfx):
        inputs += ["-i", cue["path"]]
        ms = max(0, int(round(cue["delay"] * 1000)))
        play, fade = cue["play"], cue["fade"]
        chains.append(f"[{idx}:a]{norm},atrim=start={cue['trim']:.3f}:duration={play:.3f},asetpts=PTS-STARTPTS,"
                      f"afade=t=out:st={max(0.0, play - fade):.3f}:d={fade:.3f},"
                      f"adelay={ms}|{ms},volume={cue['gain']}[fx{n}]")
        labels.append(f"fx{n}")
        idx += 1

    if not labels:  # nothing to mix -> silent track so the mp4 still has audio
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             f"anullsrc=r=44100:cl=stereo", "-t", f"{duration:.3f}", str(out)])
        return out

    mix = "".join(f"[{l}]" for l in labels)
    chains.append(f"{mix}amix=inputs={len(labels)}:normalize=0:duration=longest,"
                  f"apad=whole_dur={duration:.3f},atrim=0:{duration:.3f},alimiter=limit=0.95[out]")
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(chains),
         "-map", "[out]", "-ar", "44100", "-ac", "2", str(out)])
    return out
