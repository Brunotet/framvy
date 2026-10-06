"""Local stand-ins for your Modal endpoints, so the whole pipeline can be tested without spending credits.
   python tests/mock_modal.py   ->  TTS at :8765/tts   images at :8765/img   (call log in tests/mock_calls.log)"""
import base64, io, json, subprocess, tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LOG = Path(__file__).parent / "mock_calls.log"


def fake_tts(text: str):
    words, t = [], 0.3
    for w in text.split():
        d = 0.18 + 0.045 * len(w)
        words.append({"word": w, "start": round(t, 3), "end": round(t + d, 3)})
        t += d + (0.35 if w[-1] in ".!?" else 0.04)
    dur = t + 0.2
    out = Path(tempfile.mkdtemp()) / "v.wav"
    # quiet "voice" (low noise) so SFX can be measured in the mix
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
                    "-t", f"{dur:.2f}", str(out)], check=True)
    return base64.b64encode(out.read_bytes()).decode(), words


def fake_img(prompt: str):
    from PIL import Image, ImageDraw
    import hashlib
    h = int(hashlib.sha1(prompt.encode()).hexdigest()[:6], 16)
    im = Image.new("RGB", (768, 768), ((h >> 16) & 255, (h >> 8) & 255, h & 255))
    ImageDraw.Draw(im).ellipse([120, 120, 650, 650], outline=(255, 255, 255), width=12)
    b = io.BytesIO(); im.save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with open(LOG, "a") as f:
            f.write(f"{self.path} {json.dumps(body)[:160]}\n")
        if self.path == "/tts":
            a, w = fake_tts(body["text"])
            out = {"audio_base64": a, "words": w}
        else:
            out = {"image": fake_img(body["prompt"]), "seed": 1}
        data = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8765), H).serve_forever()
