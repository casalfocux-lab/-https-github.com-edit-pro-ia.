"""Interface visual local do Edit Pro IA (roda so no seu computador: 127.0.0.1)."""
from __future__ import annotations

import json
import re
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .core import Options, process

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "input"
OUTPUTS = ROOT / "output"
JOBS: dict[str, dict] = {}


def safe_name(name: str) -> str:
    name = Path(unquote(name)).name
    name = re.sub(r"[^\w.\- ]", "_", name).strip() or "arquivo"
    return name


def run_job(job_id: str, data: dict):
    job = JOBS[job_id]
    try:
        video = UPLOADS / safe_name(data["video"])
        opt = Options(
            cut_silence=bool(data.get("cut", True)),
            min_silence=float(data.get("min_silence", 0.6)),
            fmt=data.get("format", "9:16"),
            crop_x=float(data.get("crop_x", 0.5)),
            normalize=bool(data.get("normalize", True)),
            music=str(UPLOADS / safe_name(data["music"])) if data.get("music") else None,
            music_volume=float(data.get("music_volume", 0.2)),
            logo=str(UPLOADS / safe_name(data["logo"])) if data.get("logo") else None,
            logo_pos=data.get("logo_pos", "tr"),
            captions=(str(UPLOADS / safe_name(data["srt"])) if data.get("srt")
                      else ("auto" if data.get("captions") == "auto" else "none")),
            max_duration=float(data["max_duration"]) if data.get("max_duration") else None,
        )
        opt.log = job["log"]
        out_name = f"{video.stem}_editado_{job_id[:6]}.mp4"
        process(video, OUTPUTS / out_name, opt)
        job.update(status="pronto", output=out_name)
    except Exception as e:  # mostra o erro na tela
        job["log"].append(f"ERRO: {e}")
        job["status"] = "erro"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode())

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if url.path.startswith("/status/"):
            job = JOBS.get(url.path.rsplit("/", 1)[-1])
            return self._json(job or {"status": "desconhecido"}, 200 if job else 404)
        if url.path == "/prontos":
            files = sorted(OUTPUTS.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
            return self._json([f.name for f in files])
        if url.path.startswith("/video/"):
            return self._serve_file(OUTPUTS / safe_name(url.path.split("/video/", 1)[1]),
                                    download="dl" in parse_qs(url.query))
        self._send(404, b"{}")

    def _serve_file(self, path: Path, download=False):
        if not path.is_file():
            return self._send(404, b"{}")
        size = path.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            elif m.group(2):
                start = max(0, size - int(m.group(2)))
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        if url.path == "/upload":
            name = safe_name(parse_qs(url.query).get("name", ["arquivo"])[0])
            dest = UPLOADS / name
            with open(dest, "wb") as f:
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            return self._json({"name": name})
        if url.path == "/editar":
            data = json.loads(self.rfile.read(length) or b"{}")
            if not data.get("video"):
                return self._json({"erro": "envie um video"}, 400)
            job_id = uuid.uuid4().hex
            JOBS[job_id] = {"status": "editando", "log": [], "output": None}
            threading.Thread(target=run_job, args=(job_id, data), daemon=True).start()
            return self._json({"job": job_id})
        self._send(404, b"{}")


def serve(port=8765, open_browser=True):
    UPLOADS.mkdir(exist_ok=True)
    OUTPUTS.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Edit Pro IA aberto em {url}  (feche esta janela para encerrar)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


PAGE = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Edit Pro IA</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1c1b19;--muted:#6b6862;--line:#e3e0da;--accent:#e2452b;--ok:#1f8a4c}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--ink:#f1efe9;--muted:#9c988f;--line:#2f2e2b;--accent:#ff6a4d;--ok:#4cc27e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:20px 24px;border-bottom:1px solid var(--line);display:flex;align-items:baseline;gap:12px}
h1{margin:0;font-size:20px;letter-spacing:-.01em}h1 b{color:var(--accent)}header span{color:var(--muted);font-size:13px}
main{max-width:1100px;margin:0 auto;padding:24px;display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:24px}
@media (max-width:820px){main{grid-template-columns:1fr;padding:16px}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 12px}
.drop{border:2px dashed var(--line);border-radius:10px;padding:28px;text-align:center;cursor:pointer;color:var(--muted)}
.drop.on{border-color:var(--accent);color:var(--ink)}.drop b{color:var(--ink)}
label{display:block;font-size:13px;color:var(--muted);margin:12px 0 4px}
select,input[type=number],input[type=file]{width:100%;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
.row{display:flex;gap:8px}.row>*{flex:1}.check{display:flex;gap:8px;align-items:center;margin-top:12px;color:var(--ink);font-size:14px}
button{width:100%;margin-top:18px;padding:12px;border:0;border-radius:10px;background:var(--accent);color:#fff;font:600 15px system-ui;cursor:pointer}
button:disabled{opacity:.5;cursor:wait}
video{width:100%;max-height:70vh;background:#000;border-radius:10px;display:none}
#log{font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;color:var(--muted);white-space:pre-wrap;margin-top:12px;min-height:1.5em}
.status{font-weight:600}.status.ok{color:var(--ok)}.status.err{color:var(--accent)}
#lista a{display:block;color:var(--ink);padding:6px 0;border-bottom:1px solid var(--line);text-decoration:none;font-size:14px;overflow-wrap:anywhere}
#lista a:hover{color:var(--accent)}.dl{display:inline-block;margin-top:10px;color:var(--accent);font-weight:600}
</style></head><body>
<header><h1>Edit Pro <b>IA</b></h1><span>editor automático · roda só no seu computador</span></header>
<main>
<section>
  <div class="card">
    <div id="drop" class="drop"><b>Arraste o vídeo aqui</b><br>ou clique para escolher</div>
    <input id="fvideo" type="file" accept="video/*" hidden>
    <video id="player" controls playsinline></video>
    <div id="status" class="status"></div><div id="log"></div><a id="dl" class="dl" hidden>Baixar vídeo pronto</a>
  </div>
  <div class="card" style="margin-top:16px"><h2>Vídeos prontos</h2><div id="lista">Nenhum ainda.</div></div>
</section>
<aside class="card">
  <h2>Ajustes</h2>
  <label>Formato</label>
  <select id="format"><option value="9:16">9:16 · Reels / TikTok / Shorts</option><option value="1:1">1:1 · Feed quadrado</option>
  <option value="4:5">4:5 · Feed retrato</option><option value="16:9">16:9 · YouTube</option><option value="original">Original</option></select>
  <label>Posição do corte</label>
  <select id="crop_x"><option value="0.5">Centro</option><option value="0.25">Esquerda</option><option value="0.75">Direita</option></select>
  <div class="row"><div><label>Duração máx. (s)</label><input id="max_duration" type="number" min="5" placeholder="sem limite"></div>
  <div><label>Pausa mínima (s)</label><input id="min_silence" type="number" step="0.1" min="0.2" value="0.6"></div></div>
  <label class="check"><input id="cut" type="checkbox" checked> Cortar silêncios e pausas</label>
  <label class="check"><input id="normalize" type="checkbox" checked> Nivelar volume da voz</label>
  <label>Legendas</label>
  <select id="captions"><option value="none">Sem legenda</option><option value="auto">Automática (transcrição)</option><option value="srt">Arquivo .srt</option></select>
  <input id="fsrt" type="file" accept=".srt" style="display:none;margin-top:6px">
  <label>Música de fundo</label><input id="fmusic" type="file" accept="audio/*">
  <label>Volume da música</label>
  <select id="music_volume"><option value="0.12">Baixo</option><option value="0.2" selected>Médio</option><option value="0.32">Alto</option></select>
  <label>Logotipo (PNG)</label><input id="flogo" type="file" accept="image/png,image/*">
  <label>Posição do logo</label>
  <select id="logo_pos"><option value="tr">Canto superior direito</option><option value="tl">Canto superior esquerdo</option>
  <option value="br">Canto inferior direito</option><option value="bl">Canto inferior esquerdo</option></select>
  <button id="go" disabled>Editar vídeo</button>
</aside>
</main>
<script>
const $=id=>document.getElementById(id);let videoFile=null;
const drop=$('drop');drop.onclick=()=>$('fvideo').click();
['dragenter','dragover'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('on')}));
['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('on')}));
drop.addEventListener('drop',ev=>pick(ev.dataTransfer.files[0]));$('fvideo').onchange=e=>pick(e.target.files[0]);
$('captions').onchange=e=>$('fsrt').style.display=e.target.value==='srt'?'block':'none';
function pick(f){if(!f)return;videoFile=f;drop.innerHTML='<b>'+f.name+'</b><br>'+(f.size/1048576).toFixed(1)+' MB · clique para trocar';
 const p=$('player');p.src=URL.createObjectURL(f);p.style.display='block';$('go').disabled=false;$('dl').hidden=true;$('status').textContent='';$('log').textContent=''}
async function up(f){const r=await fetch('/upload?name='+encodeURIComponent(f.name),{method:'POST',body:f});return (await r.json()).name}
$('go').onclick=async()=>{const b=$('go');b.disabled=true;const st=$('status');st.className='status';
 try{st.textContent='Enviando arquivos…';const d={video:await up(videoFile)};
  if($('fmusic').files[0])d.music=await up($('fmusic').files[0]);if($('flogo').files[0])d.logo=await up($('flogo').files[0]);
  if($('captions').value==='srt'&&$('fsrt').files[0])d.srt=await up($('fsrt').files[0]);
  Object.assign(d,{format:$('format').value,crop_x:$('crop_x').value,max_duration:$('max_duration').value,min_silence:$('min_silence').value,
   cut:$('cut').checked,normalize:$('normalize').checked,captions:$('captions').value,music_volume:$('music_volume').value,logo_pos:$('logo_pos').value});
  st.textContent='Editando…';const {job}=await (await fetch('/editar',{method:'POST',body:JSON.stringify(d)})).json();
  for(;;){await new Promise(r=>setTimeout(r,1000));const s=await (await fetch('/status/'+job)).json();$('log').textContent=s.log.join('\n');
   if(s.status==='pronto'){st.textContent='Pronto!';st.classList.add('ok');const p=$('player');p.src='/video/'+encodeURIComponent(s.output);
    const dl=$('dl');dl.href='/video/'+encodeURIComponent(s.output)+'?dl=1';dl.hidden=false;lista();break}
   if(s.status==='erro'){st.textContent='Deu erro. Veja abaixo.';st.classList.add('err');break}}
 }catch(e){st.textContent='Erro: '+e;st.classList.add('err')}b.disabled=false};
async function lista(){const l=await (await fetch('/prontos')).json();const el=$('lista');if(!l.length){el.textContent='Nenhum ainda.';return}
 el.innerHTML='';l.forEach(n=>{const a=document.createElement('a');a.href='#';a.textContent=n;a.onclick=e=>{e.preventDefault();const p=$('player');
 p.src='/video/'+encodeURIComponent(n);p.style.display='block';const dl=$('dl');dl.href='/video/'+encodeURIComponent(n)+'?dl=1';dl.hidden=false};el.appendChild(a)})}
lista();
</script></body></html>"""
