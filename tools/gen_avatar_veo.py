#!/usr/bin/env python3
"""
Generate clawd-web avatar clips from darkclaw.png using Google Veo (Gemini API).

Image-to-video: each clip uses darkclaw.png as the reference frame + a per-clip
motion prompt, then ffmpeg crops the 16:9/9:16 output to a 624x624 24fps loop.

Usage:
  GOOGLE_API_KEY in .env (or GEMINI_API_KEY).
  python3 tools/gen_avatar_veo.py --only idle.mp4        # pilot one clip
  python3 tools/gen_avatar_veo.py --list                 # show clip names
  python3 tools/gen_avatar_veo.py                         # generate ALL (costs $$)
  python3 tools/gen_avatar_veo.py --aspect 9:16 --duration 6 --model veo-2.0-generate-001
"""
import argparse, base64, json, os, subprocess, sys, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "darkclaw.png"
OUT = ROOT / "clawdassets"
API = "https://generativelanguage.googleapis.com/v1beta"

CHAR = ("A red triangular crystalline Pepe-like character with heavy-lidded sly "
        "eyes and a smug half-smirk, wearing a black hoodie with glowing cyan "
        "drawstrings; neon cyberpunk lighting, a bank vault and a glowing 'HSM' "
        "server rack behind him. The camera is completely locked and static — "
        "absolutely NO zoom, NO pan, NO dolly, NO shake; only the character and "
        "small ambient scene details move. Keep the whole character in frame at "
        "reference scale with margin; the pointed top of his head and his claw "
        "hands stay visible the entire time. ")

# clip -> (motion prompt, duration seconds)
CLIPS = {
    # idle
    "idle.mp4": ("Subtle idle: slow breathing, one lazy blink, neon glow shimmering. Almost still. MOUTH CLOSED and still the whole time — he is NOT talking, no lip or jaw movement.", 5),
    "idle_1.mp4": ("Lifts a sleek vape pen to his mouth in one claw, takes a slow drag, lowers it, and exhales a thin curl of neon-lit vapor, unbothered and cool. A clear vaping action — not talking.", 6),
    "idle_2.mp4": ("Calm thinking pose: he rests one claw thoughtfully against the side of his chin, eyes drift slowly upward as if pondering, then a single slow blink. Extremely subtle, almost perfectly still. His MOUTH stays firmly closed and motionless the entire time — no lip or jaw movement, not talking. Locked, fixed, tripod camera — no zoom, no push-in, no pan.", 5),
    "idle_lookaround.mp4": ("Eyes glance left, then right, scanning, then back to camera. MOUTH CLOSED and still the whole time — he is NOT talking, no lip movement; only the eyes move.", 5),
    "idle-smoking.mp4": ("Takes a slow drag from a thin vape, exhales a curl of neon-lit smoke, unbothered.", 6),
    "idle-rare-eats-a-burger.mp4": ("Casually takes a bite of a cheeseburger held in a claw, chews, satisfied nod.", 6),
    "idle-sipping-coffee.mp4": ("Occasionally lifts a steaming coffee mug in a claw, takes a slow relaxed sip, sets it down, content.", 6),
    # funny rare idles
    "idle-deal-with-it.mp4": ("A pair of pixelated black sunglasses drops down from above and lands perfectly over his eyes; he gives a tiny smug nod — classic 'deal with it' meme energy.", 5),
    "idle-evil-laugh.mp4": ("Rubs his two claws together scheming, eyes narrowing, then tips his head back in a silent maniacal evil laugh, shoulders shaking, very pleased with himself.", 6),
    "idle-finger-guns.mp4": ("Points dual finger-guns (claw-guns) at the camera with a confident wink and a cocky smirk, then a little recoil like he fired them.", 5),
    "idle-texting.mp4": ("Casually pulls out a sleek black smartphone in one claw, glances down and taps out a quick text with his thumb, the screen glow lighting his face, then a small satisfied smirk as he pockets it. Mouth stays closed — not talking.", 6),
    "idle-guy-fawkes-mask.mp4": ("Slowly raises a pale white theatrical mask with a wide upward-curled mustache, a thin pointed goatee, and arched eyebrows (plain white cheeks, no blush), places it over his face, then a sly confident head tilt.", 6),
    # talking
    "chatting_1.mp4": ("Talking to camera, natural mouth movement, relaxed gestures, occasional smirk.", 6),
    "short-subtle-talking.mp4": ("Brief low-key talking, small mouth movements, minimal motion.", 5),
    "talking-saying-hello.mp4": ("Says hello, small claw wave, friendly smirk.", 5),
    "saying-hello-for-the-first-time.mp4": ("Warm first greeting, looks up, brightens, raises a claw in greeting.", 5),
    "talking-explaining-with-his-hands.mp4": ("Animated explaining, both claws gesturing, leaning in, expressive.", 6),
    "explaining.mp4": ("Calm explaining to camera, measured hand gestures, confident.", 6),
    "talking-satisfied-just-finished-something-good.mp4": ("Leans back satisfied, smug grin, slow approving nod.", 5),
    "talking-lil-drunk.mp4": ("Loose woozy talking, slight sway, droopy smirk, playful.", 5),
    # building / tools
    "quick-command-line-tool-use.mp4": ("Quick burst of typing on a neon keyboard, screen-glow flickering on his face.", 5),
    "medium-cli-or-tool-use.mp4": ("Focused typing at a terminal, code reflections in his eyes, steady rhythm.", 6),
    "longer-cli-command-line-tool-use.mp4": ("Extended hacking, rapid typing, scrolling code glow, in the zone.", 8),
    "building.mp4": ("Tinkering with something techy in his claws, sparks of neon, focused.", 5),
    "hammering-tool-use-building-medium.mp4": ("Swinging a small glowing hammer, rhythmic impacts, determined.", 6),
    "longer-hammering-tool-use.mp4": ("Longer building montage, repeated hammering, effort, satisfied pauses.", 8),
    # thinking / listening
    "thinking-idle-light-thinking.mp4": ("Light thinking, eyes up and to the side, a claw to the chin, slow ponder.", 6),
    "deep-in-thought-or-listening.mp4": ("Deep focus, narrowed eyes, very still, occasional slow blink.", 6),
    "thinking-listening.mp4": ("Attentive listening, slight head tilt, eyes tracking, patient nod.", 6),
}


KEY_VARS = ("GOOGLE_GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")


def load_key():
    k = next((os.environ[v] for v in KEY_VARS if os.environ.get(v)), None)
    if not k:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                line = line.strip()
                if any(line.startswith(v + "=") for v in KEY_VARS):
                    k = line.split("=", 1)[1].strip()
                    break
    if not k:
        sys.exit("No GOOGLE_API_KEY / GEMINI_API_KEY in env or .env")
    return k


def _post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def _get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read())


def padded_source(aspect, scale=0.82):
    """Build a Veo reference: the character scaled to `scale` of frame height,
    centered on a blurred fill of itself, at the target aspect. This both
    preserves scale (no Veo zoom-in) AND adds breathing room so the final
    square crop isn't too tight. Blur margin gets mostly cropped off."""
    W, H = (1024, 1820) if aspect == "9:16" else (1820, 1024)
    ch = int(H * scale)
    out = OUT / f".ref_{aspect.replace(':','x')}_{scale}.png"
    fc = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},boxblur=28:4[bg];"
          f"[0:v]scale=-1:{ch}[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[out]")
    subprocess.run(["ffmpeg", "-y", "-i", str(SRC), "-filter_complex", fc,
                    "-map", "[out]", str(out)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out


# Negative-prompt profiles. All ban camera moves; they differ on the mouth.
_NEG_ZOOM = "camera zoom, zoom in, push in, dolly, camera pan, camera movement, shaky camera"
_NEG_STILL = "talking, speaking, open mouth, moving lips, lip sync, mouth movement, " + _NEG_ZOOM   # neutral idles
_NEG_ACTION = "talking, speaking, conversation, lip sync, " + _NEG_ZOOM                              # vape/yawn/coffee/etc — allow the action's mouth

def neg_for(name):
    # Talking clips must keep their mouth moving — only forbid camera moves.
    if name.startswith(("chatting", "talking", "short-subtle", "saying-hello", "explaining")):
        return _NEG_ZOOM
    # Purposeful mouth/hand actions: forbid talking + camera, allow the action.
    if name in ("idle_1.mp4", "idle-sipping-coffee.mp4", "idle-smoking.mp4",
                "idle-rare-eats-a-burger.mp4", "idle-guy-fawkes-mask.mp4",
                "idle-deal-with-it.mp4", "idle-evil-laugh.mp4", "idle-finger-guns.mp4"):
        return _NEG_ACTION
    # Everything else (neutral idle / thinking / building): mouth stays shut.
    return _NEG_STILL


def generate(name, prompt, dur, key, model, aspect, ref):
    img_b64 = base64.b64encode(ref.read_bytes()).decode()
    payload = {
        "instances": [{"prompt": CHAR + prompt,
                       "image": {"bytesBase64Encoded": img_b64, "mimeType": "image/png"}}],
        "parameters": {"aspectRatio": aspect, "durationSeconds": int(dur),
                       "personGeneration": "allow_adult",
                       "negativePrompt": neg_for(name)},
    }
    print(f"[{name}] submitting ({dur}s, {aspect})...")
    op = _post(f"{API}/models/{model}:predictLongRunning?key={key}", payload)
    opname = op.get("name")
    if not opname:
        print("  unexpected submit response:", json.dumps(op)[:400]); return None
    # poll
    for i in range(60):
        time.sleep(10)
        st = _get(f"{API}/{opname}?key={key}")
        if st.get("done"):
            return _extract_video(st, key)
        print(f"  polling... {(i+1)*10}s")
    print("  timed out"); return None


def _extract_video(op, key):
    """Veo response shapes vary; dig out a base64 blob or a download URI."""
    blob = json.dumps(op)
    resp = op.get("response", {})
    # common nests
    samples = (resp.get("generateVideoResponse", {}).get("generatedSamples")
               or resp.get("generatedVideos") or resp.get("videos") or [])
    for s in samples:
        v = s.get("video", s)
        if v.get("bytesBase64Encoded"):
            return ("b64", v["bytesBase64Encoded"])
        uri = v.get("uri") or v.get("videoUri")
        if uri:
            return ("uri", uri if "key=" in uri else f"{uri}{'&' if '?' in uri else '?'}key={key}")
    if op.get("error"):
        print("  API error:", json.dumps(op["error"])[:400]); return None
    print("  could not locate video in response; raw:", blob[:600]); return None


def finalize(kind, data, name, dur):
    raw = OUT / f".raw_{name}"
    if kind == "b64":
        raw.write_bytes(base64.b64decode(data))
    else:
        with urllib.request.urlopen(data, timeout=300) as r:
            raw.write_bytes(r.read())
    # center-crop to square, scale 624x624, 24fps, h264, no audio, loop-length
    vf = "crop='min(iw,ih)':'min(iw,ih)',scale=624:624,fps=24,format=yuv420p"
    subprocess.run(["ffmpeg", "-y", "-i", str(raw), "-t", str(dur), "-vf", vf,
                    "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    str(OUT / name)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    raw.unlink(missing_ok=True)
    print(f"  -> wrote clawdassets/{name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="generate just this clip filename")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--model", default="veo-2.0-generate-001")
    ap.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"])
    ap.add_argument("--duration", type=int, help="override duration for all")
    args = ap.parse_args()
    if args.list:
        for n in CLIPS: print(n)
        return
    key = load_key()
    ref = padded_source(args.aspect)
    names = [args.only] if args.only else list(CLIPS)
    for name in names:
        if name not in CLIPS:
            print("unknown clip:", name); continue
        prompt, dur = CLIPS[name]
        if args.duration: dur = args.duration
        try:
            res = generate(name, prompt, dur, key, args.model, args.aspect, ref)
            if res:
                finalize(res[0], res[1], name, dur)
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code}: {e.read().decode('utf-8','replace')[:400]}")
        except Exception as e:
            print(f"  error: {e}")


if __name__ == "__main__":
    main()
