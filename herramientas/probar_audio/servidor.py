#!/usr/bin/env python3
"""Banco de pruebas de audio (entrada y salida) para elegir STT/TTS y ajustar el modo "Jarvis".

    python3 herramientas/probar_audio/servidor.py      ->  http://127.0.0.1:8400

Solo biblioteca estándar. Sirve la página y hace de proxy hacia cualquier endpoint compatible
con OpenAI (`/audio/transcriptions` y `/audio/speech`), de modo que las claves nunca llegan al
navegador. Escucha solo en 127.0.0.1 y rechaza orígenes ajenos. No guarda audio.

Variables (por defecto, el speaches local de docker-compose.dev.yml con --profile voz):
  STT_BASE_URL  http://127.0.0.1:8300/v1     STT_MODELO  Systran/faster-whisper-small   STT_API_KEY
  TTS_BASE_URL  (= STT_BASE_URL)             TTS_MODELO  speaches-ai/Kokoro-82M-v1.0-ONNX
  TTS_VOZ       ef_dora                      TTS_API_KEY  TTS_FORMATO  mp3
  STT_IDIOMA    es
"""
import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PUERTO = int(os.environ.get("PROBAR_AUDIO_PUERTO", "8400"))
AQUI = Path(__file__).parent
E = os.environ.get
STT_URL = E("STT_BASE_URL", "http://127.0.0.1:8300/v1").rstrip("/")
TTS_URL = E("TTS_BASE_URL", STT_URL).rstrip("/")
CFG = {
    "stt_modelo": E("STT_MODELO", "Systran/faster-whisper-small"),
    "stt_idioma": E("STT_IDIOMA", "es"),
    "tts_modelo": E("TTS_MODELO", "speaches-ai/Kokoro-82M-v1.0-ONNX"),
    "tts_voz": E("TTS_VOZ", "ef_dora"),
    "tts_formato": E("TTS_FORMATO", "mp3"),
}
ORIGENES = {f"http://127.0.0.1:{PUERTO}", f"http://localhost:{PUERTO}"}
EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/wav": "wav", "audio/mpeg": "mp3"}
MIME_TTS = {"mp3": "audio/mpeg", "wav": "audio/wav", "opus": "audio/ogg", "flac": "audio/flac"}


def _auth(clave: str | None) -> dict:
    return {"Authorization": f"Bearer {clave}"} if clave else {}


def _multipart(campos: dict, archivo: tuple[str, str, bytes]) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    partes = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in campos.items()]
    nombre, mime, datos = archivo
    partes.append(
        f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{nombre}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
        + datos + b"\r\n"
    )
    partes.append(f"--{b}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={b}"


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):  # sin ruido; solo errores propios
        pass

    def _origen_ok(self) -> bool:
        o = self.headers.get("Origin")
        return o is None or o in ORIGENES

    def _json(self, codigo: int, cuerpo: dict):
        datos = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            datos = (AQUI / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)
        elif self.path == "/config":
            self._json(200, {**CFG, "stt_url": STT_URL, "tts_url": TTS_URL,
                             "stt_clave": bool(E("STT_API_KEY")), "tts_clave": bool(E("TTS_API_KEY", E("STT_API_KEY")))})
        else:
            self.send_error(404)

    def do_POST(self):
        if not self._origen_ok():
            return self._json(403, {"error": "origen no permitido"})
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(largo) if largo else b""
        try:
            if self.path == "/stt":
                return self._stt(cuerpo)
            if self.path == "/tts":
                return self._tts(cuerpo)
        except (URLError, TimeoutError, ConnectionError) as e:
            return self._json(502, {"error": f"no se pudo contactar al proveedor: {e}"})
        self.send_error(404)

    def _stt(self, audio: bytes):
        mime = (self.headers.get("Content-Type") or "audio/webm").split(";")[0].strip()
        datos, ctype = _multipart(
            {"model": CFG["stt_modelo"], "response_format": "json", "language": CFG["stt_idioma"]},
            (f"audio.{EXT.get(mime, 'webm')}", mime, audio),
        )
        req = Request(f"{STT_URL}/audio/transcriptions", datos, {"Content-Type": ctype, **_auth(E("STT_API_KEY"))})
        t0 = time.perf_counter()
        try:
            with urlopen(req, timeout=60) as r:
                texto = json.load(r).get("text", "")
        except HTTPError as e:
            return self._json(e.code, {"error": e.read().decode(errors="replace")[:500]})
        self._json(200, {"text": texto, "ms": round((time.perf_counter() - t0) * 1000)})

    def _tts(self, cuerpo: bytes):
        p = json.loads(cuerpo or b"{}")
        texto = (p.get("text") or "").strip()[:2000]
        if not texto:
            return self._json(400, {"error": "texto vacío"})
        carga = {"model": CFG["tts_modelo"], "voice": p.get("voz") or CFG["tts_voz"], "input": texto,
                 "response_format": CFG["tts_formato"]}
        req = Request(f"{TTS_URL}/audio/speech", json.dumps(carga).encode(),
                      {"Content-Type": "application/json", **_auth(E("TTS_API_KEY", E("STT_API_KEY")))})
        try:
            r = urlopen(req, timeout=60)
        except HTTPError as e:
            return self._json(e.code, {"error": e.read().decode(errors="replace")[:500]})
        with r:
            self.send_response(200)
            self.send_header("Content-Type", MIME_TTS.get(CFG["tts_formato"], "application/octet-stream"))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()  # sin Content-Length: se cierra la conexión al terminar (streaming)
            while chunk := r.read(4096):
                self.wfile.write(chunk)
                self.wfile.flush()
        self.close_connection = True


if __name__ == "__main__":
    print(f"Banco de pruebas de audio: http://127.0.0.1:{PUERTO}\n  STT {STT_URL} [{CFG['stt_modelo']}]\n  TTS {TTS_URL} [{CFG['tts_modelo']} / {CFG['tts_voz']}]")
    ThreadingHTTPServer(("127.0.0.1", PUERTO), H).serve_forever()
