#!/usr/bin/env python3
"""
Global hotkey daemon for clawd-web.
Ctrl+Option+Cmd+. (or numpad .) anywhere in the OS toggles mic recording.
Ctrl+Option+Cmd+0 (or numpad 0) toggles the Clawd view (same as clicking the MP4).
Ctrl+Option+Cmd++ (numpad +) starts a fresh chat tab.
Ctrl+Option+Cmd+h reveals chat history for 30s before it fades again.
Ctrl+Option+Cmd+- toggles speech mode (full-black 16:9 stage with subtitles).
Ctrl+Option+Cmd+Delete (Backspace) immediately STOPS clawd from talking (panic mute).

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
def is_period(k): return (hasattr(k, 'char') and k.char == '.') or (hasattr(k, 'vk') and k.vk in (47, 65))  # 47 = main '.', 65 = numpad '.'; char goes None under Ctrl+Alt+Cmd, so vk is the reliable path
def is_zero(k):   return (hasattr(k, 'char') and k.char == '0') or (hasattr(k, 'vk') and k.vk == 82)
def is_h(k):      return hasattr(k, 'char') and k.char == 'h'
def is_plus(k):   return (hasattr(k, 'char') and k.char == '+') or (hasattr(k, 'vk') and k.vk == 69)  # vk 69 = numpad +
def is_minus(k):  return (hasattr(k, 'char') and k.char == '-') or (hasattr(k, 'vk') and k.vk in (27, 78))  # 27 = main -, 78 = numpad -
def is_stop(k):  # the big ⌫ key — pynput calls it backspace OR delete depending on the Mac/keyboard; match all of them
    return (k == keyboard.Key.backspace or k == keyboard.Key.delete
            or (hasattr(k, 'vk') and k.vk in (51, 117)))  # 51 = ⌫ backspace, 117 = ⌦ forward-delete

def on_press(key, *_):
    _pressed.add(key)
    mods = (
        any(is_ctrl(k) for k in _pressed) and
        any(is_alt(k)  for k in _pressed) and
        any(is_cmd(k)  for k in _pressed)
    )
    if not mods:
        return
    # TEMP DEBUG: show exactly what each modified keypress is, so we can bind the
    # right one. Remove once the stop key is confirmed.
    print(f"[hotkey debug] modified key -> {key!r}  vk={getattr(key, 'vk', None)}  char={getattr(key, 'char', None)!r}", flush=True)
    if is_period(key):
        post("/trigger-mic", "toggled mic")
    elif is_zero(key):
        post("/trigger-toggle-view", "toggled view")
    elif is_h(key):
        post("/trigger-reveal-history", "revealed history")
    elif is_plus(key):
        post("/trigger-new-tab", "new tab")
    elif is_minus(key):
        post("/trigger-speech-mode", "toggled speech mode")
    elif is_stop(key):
        post("/trigger-stop-talking", "stop talking")

def on_release(key, *_):
    _pressed.discard(key)

print(f"🎤 clawd hotkey ready — Ctrl+Option+Cmd+. toggles mic, +0 toggles view, ++ new tab, +- toggles speech, +h reveals history, +Delete STOPS talking (server on port {PORT})")

with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
    l.join()
