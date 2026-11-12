"""Edit Pro IA - nucleo de edicao de video (ffmpeg)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

FORMATS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
LOGO_POS = {"tr": "W-w-40:60", "tl": "40:60", "br": "W-w-40:H-h-60", "bl": "40:H-h-60"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}


@dataclass
class Options:
    cut_silence: bool = True
    silence_db: float = -35.0
    min_silence: float = 0.6
    pad: float = 0.15
    fmt: str = "9:16"
    crop_x: float = 0.5
    normalize: bool = True
    music: str | None = None
    music_volume: float = 0.2
    logo: str | None = None
    logo_pos: str = "tr"
    logo_width: float = 0.18
    captions: str = "none"  # none | auto | caminho .srt
    whisper_model: str = "small"
    language: str = "pt"
    caption_font: str = "DejaVu Sans"
    max_duration: float | None = None
    crf: int = 20
    fps: int = 30
    log: list = field(default_factory=list)


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou:\n{' '.join(map(str, cmd))}\n{p.stderr[-2000:]}")
    return p


def probe(path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]).stdout
    data = json.loads(out)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    return {
        "duration": float(data["format"].get("duration", 0)),
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
        "has_audio": a is not None,
    }


def detect_keep_segments(path, duration, opt: Options):
    """Retorna trechos com fala (inicio, fim), removendo silencios."""
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af",
         f"silencedetect=n={opt.silence_db}dB:d={opt.min_silence}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    if len(ends) < len(starts):
        ends.append(duration)
    keep, cursor = [], 0.0
    for s, e in zip(starts, ends):
        if s > cursor:
            keep.append((cursor, s))
        cursor = e
    if cursor < duration:
        keep.append((cursor, duration))
    padded = []
    for s, e in keep:
        s, e = max(0.0, s - opt.pad), min(duration, e + opt.pad)
        if padded and s <= padded[-1][1]:
            padded[-1] = (padded[-1][0], max(padded[-1][1], e))
        else:
            padded.append((s, e))
    return [(s, e) for s, e in padded if e - s >= 0.2]


def _crop_filter(opt: Options):
    if opt.fmt == "original":
        return f"fps={opt.fps},setsar=1"
    w, h = FORMATS[opt.fmt]
    r = w / h
    return (f"crop=w='min(iw,ih*{r})':h='min(ih,iw/{r})':x='(iw-ow)*{opt.crop_x}':y='(ih-oh)/2',"
            f"scale={w}:{h},fps={opt.fps},setsar=1")


def _enc(opt: Options):
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(opt.crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]


def pass1_cut(src, dst, info, opt: Options):
    """Corta silencios, ajusta formato e nivela o audio."""
    vf, af = [], []
    if opt.cut_silence and info["has_audio"]:
        segs = detect_keep_segments(src, info["duration"], opt)
        kept = sum(e - s for s, e in segs)
        opt.log.append(f"silencios: {len(segs)} trechos mantidos, {info['duration'] - kept:.1f}s removidos")
        if segs:
            expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in segs)
            vf.append(f"select='{expr}',setpts=N/FRAME_RATE/TB")
            af.append(f"aselect='{expr}',asetpts=N/SR/TB")
    vf.append(_crop_filter(opt))
    if opt.normalize and info["has_audio"]:
        af.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", str(src)]
    if vf and "select" in vf[0]:
        # fps antes do select garante timestamps regulares
        vf.insert(0, f"fps={opt.fps}")
    cmd += ["-vf", ",".join(vf)]
    if info["has_audio"]:
        cmd += ["-af", ",".join(af) if af else "anull"]
    if opt.max_duration:
        cmd += ["-t", str(opt.max_duration)]
    run(cmd + _enc(opt) + [str(dst)])


def _fmt_srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def transcribe_to_srt(src, srt_path, opt: Options):
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("Legenda automatica precisa do pacote faster-whisper (pip install faster-whisper).") from e
    try:
        model = WhisperModel(opt.whisper_model, device="cpu", compute_type="int8")
    except Exception as e:
        raise RuntimeError(
            "Nao consegui baixar o modelo de transcricao (huggingface.co bloqueado?). "
            "Use --captions arquivo.srt ou libere o acesso.") from e
    segments, _ = model.transcribe(str(src), language=opt.language, word_timestamps=True, vad_filter=True)
    words = [w for seg in segments for w in (seg.words or [])]
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 4 or (cur[-1].end - cur[0].start) > 1.6 or w.word.strip()[-1:] in ".,!?":
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    lines = []
    for i, c in enumerate(chunks, 1):
        text = " ".join(x.word.strip() for x in c).upper()
        lines.append(f"{i}\n{_fmt_srt_time(c[0].start)} --> {_fmt_srt_time(c[-1].end)}\n{text}\n")
    Path(srt_path).write_text("\n".join(lines), encoding="utf-8")
    opt.log.append(f"legendas: {len(chunks)} blocos gerados")


def pass2_finish(src, dst, info, opt: Options, workdir: Path):
    """Legendas, musica com ducking e logotipo."""
    inputs = ["-i", str(src)]
    filters, vlabel, alabel = [], "[0:v]", "[0:a]" if info["has_audio"] else None
    idx = 1

    if opt.captions != "none":
        srt = workdir / "subs.srt"
        if opt.captions == "auto":
            transcribe_to_srt(src, srt, opt)
        else:
            shutil.copy(opt.captions, srt)
        style = (f"FontName={opt.caption_font},FontSize=14,Bold=1,PrimaryColour=&H00FFFFFF,"
                 "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=60")
        filters.append(f"{vlabel}subtitles=subs.srt:force_style='{style}'[vs]")
        vlabel = "[vs]"

    if opt.logo:
        inputs += ["-i", str(Path(opt.logo).resolve())]
        lw = int(FORMATS.get(opt.fmt, (1080, 0))[0] * opt.logo_width)
        filters.append(f"[{idx}:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa=0.9[lg]")
        filters.append(f"{vlabel}[lg]overlay={LOGO_POS[opt.logo_pos]}[vl]")
        vlabel = "[vl]"
        idx += 1

    if opt.music:
        inputs += ["-stream_loop", "-1", "-i", str(Path(opt.music).resolve())]
        m = f"[{idx}:a]"
        if alabel:
            filters.append(f"{alabel}asplit=2[voz][sc]")
            filters.append(f"{m}volume={opt.music_volume},aformat=sample_rates=48000:channel_layouts=stereo[mus]")
            filters.append("[mus][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]")
            filters.append("[voz]aformat=sample_rates=48000:channel_layouts=stereo[voz2]")
            filters.append("[voz2][duck]amix=inputs=2:duration=first:normalize=0[am]")
        else:
            filters.append(f"{m}volume={opt.music_volume}[am]")
        alabel = "[am]"
        idx += 1

    if not filters:
        shutil.copy(src, dst)
        return
    cmd = ["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(filters),
           "-map", vlabel if vlabel != "[0:v]" else "0:v"]
    if alabel:
        cmd += ["-map", alabel if alabel != "[0:a]" else "0:a"]
    cmd += ["-t", f"{probe(src)['duration']:.3f}"]
    run(cmd + _enc(opt) + [str(Path(dst).resolve())], cwd=workdir)


def process(src, dst, opt: Options) -> list:
    src, dst = Path(src).resolve(), Path(dst).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    opt.log.append(f"entrada: {src.name} {info['width']}x{info['height']} {info['duration']:.1f}s")
    with tempfile.TemporaryDirectory(prefix="editpro_") as td:
        wd = Path(td)
        mid = wd / "pass1.mp4"
        pass1_cut(src, mid, info, opt)
        pass2_finish(mid, dst, probe(mid), opt, wd)
    out = probe(dst)
    opt.log.append(f"saida: {dst.name} {out['width']}x{out['height']} {out['duration']:.1f}s")
    return opt.log


def batch(indir, outdir, opt_factory) -> list:
    results = []
    for f in sorted(Path(indir).iterdir()):
        if f.suffix.lower() not in VIDEO_EXT:
            continue
        opt = opt_factory()
        try:
            process(f, Path(outdir) / f"{f.stem}_editado.mp4", opt)
            results.append((f.name, "ok", opt.log))
        except Exception as e:  # segue para o proximo video
            results.append((f.name, "erro", [str(e)]))
    return results
