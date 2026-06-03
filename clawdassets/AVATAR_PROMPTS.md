# Avatar clip prompts (image-to-video)

The 23 `.mp4`s here are currently **ffmpeg stopgaps** — `darkclaw.png` with subtle
motion (breathe / bob / pulse / drift). They make the new character show up, but
they aren't truly animated (no mouth, hands, or actions).

To replace them with real animation, run each prompt below through an
**image-to-video** model with **`darkclaw.png` as the first/reference frame**:
Runway Gen-4, Kling 2.x, Luma Dream Machine, Hailuo/MiniMax, Pika, or Sora.

**Global settings for every clip**
- First frame / reference image: `darkclaw.png`
- Aspect: **1:1 square**, export **624×624**, **24fps**, **h.264 .mp4**, no audio
- Length: ~3–6s (see per-clip), **seamless loop** if the tool supports it
- Keep the camera locked/static; keep the character centered; preserve the red
  triangular crystal head, black hoodie with cyan neon drawstrings, claw hands,
  and the neon HSM/vault cyberpunk backdrop
- Style: keep it subtle and characterful — confident, sly, "encrypts for sport"

**Character description (paste into prompts that need it)**
> A red triangular crystalline Pepe-like character ("darkclaw") with heavy-lidded
> sly eyes and a smug half-smirk, wearing a black hoodie with glowing cyan
> drawstrings, neon cyberpunk lighting, a bank vault and a glowing "HSM" server
> rack behind him. Cool, deadpan hacker energy.

---

## Idle (loop, calm)
| File | Prompt | ~sec |
|---|---|---|
| `idle.mp4` | Subtle idle: slow breathing, faint blink, neon glow shimmering on the hoodie, eyes drifting lazily. Almost still. | 5 |
| `idle_1.mp4` | Relaxed idle, one slow blink and a tiny smirk twitch; ambient neon flicker behind. | 5 |
| `idle_2.mp4` | Idle with a slow, confident head tilt and settle back to center. | 5 |
| `idle_lookaround.mp4` | Eyes glance left, then right, scanning, then back to camera with a smirk. | 5 |
| `idle-smoking.mp4` | Takes a slow drag from a thin vape/cigarette, exhales a curl of neon-lit smoke, unbothered. | 6 |
| `idle-rare-eats-a-burger.mp4` | Casually takes a bite of a cheeseburger held in a claw, chews, satisfied nod. | 6 |

## Talking
| File | Prompt | ~sec |
|---|---|---|
| `chatting_1.mp4` | Talking to camera, natural mouth movement, relaxed gestures, occasional smirk. | 6 |
| `short-subtle-talking.mp4` | Brief, low-key talking — small mouth movements, minimal motion. | 3 |
| `talking-saying-hello.mp4` | Says hello, gives a small claw wave, friendly smirk. | 4 |
| `saying-hello-for-the-first-time.mp4` | Warm first greeting — looks up, brightens slightly, raises a claw in greeting. | 4 |
| `talking-explaining-with-his-hands.mp4` | Animated explaining, both claws gesturing, leaning in slightly, expressive. | 6 |
| `explaining.mp4` | Calm explaining to camera, measured hand gestures, confident. | 6 |
| `talking-satisfied-just-finished-something-good.mp4` | Leans back satisfied, smug grin, slow approving nod, maybe a claw fist-bump to self. | 5 |
| `talking-lil-drunk.mp4` | Loose, woozy talking, slight sway, droopy smirk, playful. | 5 |

## Building / tool use (energetic, terminal glow)
| File | Prompt | ~sec |
|---|---|---|
| `quick-command-line-tool-use.mp4` | Quick burst of typing on a neon keyboard, screen-glow flickering on his face, fast. | 3 |
| `medium-cli-or-tool-use.mp4` | Focused typing at a terminal, code reflections in his eyes, steady rhythm. | 5 |
| `longer-cli-command-line-tool-use.mp4` | Extended hacking session, rapid typing, scrolling code glow, in the zone. | 8 |
| `building.mp4` | Tinkering/assembling something techy with his claws, sparks of neon, focused. | 5 |
| `hammering-tool-use-building-medium.mp4` | Swinging a small glowing hammer, building, rhythmic impacts, determined. | 5 |
| `longer-hammering-tool-use.mp4` | Longer building montage, repeated hammering, sweat-drop effort, satisfied pauses. | 8 |

## Thinking / listening (slow, minimal)
| File | Prompt | ~sec |
|---|---|---|
| `thinking-idle-light-thinking.mp4` | Light thinking — eyes up and to the side, a claw to the chin, slow ponder. | 6 |
| `deep-in-thought-or-listening.mp4` | Deep focus, narrowed eyes, very still, occasional slow blink, processing. | 6 |
| `thinking-listening.mp4` | Attentive listening, slight head tilt, eyes tracking, patient nod. | 6 |

---

### Wiring them back in
Just drop the rendered files into this folder with the **same filenames** — the
UI (`clawdVid` in `index.html`) picks them up automatically; no code changes.
Note `clawdassets/*.mp4` is gitignored except the few committed ones, so add any
you want version-controlled with `git add -f clawdassets/<file>.mp4`.
