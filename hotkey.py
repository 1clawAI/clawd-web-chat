#!/usr/bin/env python3
"""
Global hotkey daemon for clawd-web.
Ctrl+Option+Cmd+. (or numpad .) anywhere in the OS toggles mic recording.
Ctrl+Option+Cmd+0 (or numpad 0) toggles the Clawd view (same as clicking the MP4).
Ctrl+Option+Cmd+h reveals chat history for 30s before it fades again.

Install dep once:
    pip install pynput --break-system-packages

Then run alongside server.py:
    python3 hotkey.py
"""
import urllib.request
import urllib.error

PORT = 7800

def post(endpoint, label):
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"http://127.0.0.1:{PORT}{endpoint}",
                method="POST",
                data=b"",
            ),
            timeout=2,
        )
        print(f"[hotkey] {label}")
    except urllib.error.URLError as e:
        print(f"[hotkey] server not reachable: {e}")

try:
    from pynput import keyboard
except ImportError:
    print("pynput not installed — run: pip install pynput --break-system-packages")
    raise SystemExit(1)

_pressed = set()

def is_ctrl(k): return k in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r)
def is_alt(k):  return k in (keyboard.Key.alt,  keyboard.Key.alt_l,  keyboard.Key.alt_r, keyboard.Key.alt_gr)
def is_cmd(k):  return k in (keyboard.Key.cmd,  keyboard.Key.cmd_l,  keyboard.Key.cmd_r)
def is_period(k): return (hasattr(k, 'char') and k.char == '.') or k == keyboard.Key.delete
def is_zero(k):   return (hasattr(k, 'char') and k.char == '0') or (hasattr(k, 'vk') and k.vk == 82)
def is_h(k):      return hasattr(k, 'char') and k.char == 'h'

def on_press(key, *_):
    _pressed.add(key)
    mods = (
        any(is_ctrl(k) for k in _pressed) and
        any(is_alt(k)  for k in _pressed) and
        any(is_cmd(k)  for k in _pressed)
    )
    if not mods:
        return
    if is_period(key):
        post("/trigger-mic", "toggled mic")
    elif is_zero(key):
        post("/trigger-toggle-view", "toggled view")
    elif is_h(key):
        post("/trigger-reveal-history", "revealed history")

def on_release(key, *_):
    _pressed.discard(key)

print(f"🎤 clawd hotkey ready — Ctrl+Option+Cmd+. toggles mic, +0 toggles view, +h reveals history (server on port {PORT})")

with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
    l.join()
