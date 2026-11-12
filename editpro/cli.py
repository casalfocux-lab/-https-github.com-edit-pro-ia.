"""Linha de comando do Edit Pro IA."""
import argparse
import sys

from .core import FORMATS, LOGO_POS, Options, batch, detect_keep_segments, probe, process


def add_opts(p):
    p.add_argument("--no-cut", action="store_true", help="nao remover silencios")
    p.add_argument("--silence-db", type=float, default=-35.0, help="limite de silencio em dB (padrao -35)")
    p.add_argument("--min-silence", type=float, default=0.6, help="pausa minima a cortar, em s (padrao 0.6)")
    p.add_argument("--pad", type=float, default=0.15, help="respiro mantido antes/depois da fala, em s")
    p.add_argument("--format", dest="fmt", default="9:16", choices=[*FORMATS, "original"])
    p.add_argument("--crop-x", type=float, default=0.5, help="posicao do corte: 0=esquerda 0.5=centro 1=direita")
    p.add_argument("--no-normalize", action="store_true", help="nao nivelar o volume da voz")
    p.add_argument("--music", help="arquivo de musica de fundo")
    p.add_argument("--music-volume", type=float, default=0.2)
    p.add_argument("--logo", help="imagem do logotipo (png)")
    p.add_argument("--logo-pos", default="tr", choices=list(LOGO_POS))
    p.add_argument("--captions", default="none", help="none | auto | caminho do .srt")
    p.add_argument("--whisper-model", default="small")
    p.add_argument("--language", default="pt")
    p.add_argument("--max-duration", type=float, help="duracao maxima final em s")


def to_options(a) -> Options:
    return Options(cut_silence=not a.no_cut, silence_db=a.silence_db, min_silence=a.min_silence, pad=a.pad,
                   fmt=a.fmt, crop_x=a.crop_x, normalize=not a.no_normalize, music=a.music,
                   music_volume=a.music_volume, logo=a.logo, logo_pos=a.logo_pos, captions=a.captions,
                   whisper_model=a.whisper_model, language=a.language, max_duration=a.max_duration)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="editpro", description="Edit Pro IA - editor de video automatico")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("process", help="editar um video")
    p.add_argument("input")
    p.add_argument("-o", "--output")
    add_opts(p)

    b = sub.add_parser("batch", help="editar todos os videos de uma pasta")
    b.add_argument("indir")
    b.add_argument("outdir")
    add_opts(b)

    i = sub.add_parser("info", help="analisar um video sem editar")
    i.add_argument("input")
    i.add_argument("--silence-db", type=float, default=-35.0)
    i.add_argument("--min-silence", type=float, default=0.6)

    w = sub.add_parser("web", help="abrir a interface visual no navegador")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--no-browser", action="store_true")

    a = ap.parse_args(argv)
    if a.cmd == "web":
        from .web import serve
        serve(a.port, open_browser=not a.no_browser)
        return 0
    if a.cmd == "info":
        info = probe(a.input)
        print(f"{info['width']}x{info['height']}  {info['duration']:.1f}s  audio={info['has_audio']}")
        if info["has_audio"]:
            segs = detect_keep_segments(a.input, info["duration"],
                                        Options(silence_db=a.silence_db, min_silence=a.min_silence))
            kept = sum(e - s for s, e in segs)
            print(f"fala: {kept:.1f}s em {len(segs)} trechos; silencio removivel: {info['duration'] - kept:.1f}s")
        return 0
    if a.cmd == "process":
        out = a.output or a.input.rsplit(".", 1)[0] + "_editado.mp4"
        for line in process(a.input, out, to_options(a)):
            print(line)
        return 0
    results = batch(a.indir, a.outdir, lambda: to_options(a))
    for name, status, log in results:
        print(f"[{status}] {name}")
        for line in log:
            print(f"    {line}")
    return 0 if all(s == "ok" for _, s, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
