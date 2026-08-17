# Mira visual specification v0.1

Status: approved direction, based on the two August 16 reference boards.

## Design intent

Mira should feel like a capable colleague present in a calm workspace: warm,
observant, composed, and able to become sharply attentive without appearing
hostile. The visual relationship is professional and execution-oriented, never
romantic, flirtatious, possessive, or dependency-forming.

The target is slightly stylized realism rather than a literal photographic
replica. Preserve the references' character, silhouette, palette, and emotional
read; do not treat the generated face as an exact biometric identity target.

## Character anchor

- South Asian woman, visually around early thirties.
- Dark brown, shoulder-length wavy hair with a soft side part. Use a loose bun
  only as a later variation; the shoulder-length style is the v0.1 anchor.
- Warm brown eyes, expressive brows, natural skin detail, minimal makeup.
- Smart-casual uniform: earthy brown overshirt, black inner top, tailored dark
  trousers, neutral trainers.
- Accessories remain minimal: small studs, fine necklace, optional watch.
- No glamour posing, exaggerated body proportions, revealing styling, or
  attention-seeking animation.

## Camera and environment

- Default framing: seated medium close-up, chest to head, direct but relaxed eye
  line. Mira occupies the central 40–45% of a 16:9 desktop layout.
- Camera is stationary during conversation. Small reframing is allowed only
  when entering or leaving Focus Mode.
- Background: warm, softly blurred study/workspace with practical lighting,
  plants, wood, and restrained depth of field.
- Key light is warm-neutral and soft. Avoid beauty-light gloss, hard rim lights,
  or dramatic cinematic contrast.

## Expression and gesture contract

All facial changes should settle gently and remain asymmetrical enough to feel
alive. Intensity values below refer to the `MiraResponse` value from 0 to 1.

| Protocol cue | Visual behavior | Safe intensity |
| --- | --- | --- |
| `attentive` | relaxed mouth, focused eyes, slight brow engagement | 0.25–0.50 |
| `focused` | neutral mouth, steadier gaze, subtly narrowed attention | 0.35–0.60 |
| `soft_smile` | small closed-mouth smile, softened eyes | 0.25–0.55 |
| `raised_eyebrow` | one brow rises, mouth remains neutral | 0.30–0.60 |
| `small_nod` | one restrained acknowledgement nod | 0.20–0.45 |
| `subtle_head_tilt` | 3–6 degree tilt held briefly | 0.20–0.40 |

Rules:

- Blinks and breathing continue in every state.
- `CHALLENGING` means precision, stillness, and a raised eyebrow—not anger.
- `CELEBRATING` uses a soft smile and nod, never cheering or bouncing.
- `LISTENING` prioritizes steady gaze with occasional natural glance shifts.
- Silence is visible: Mira can hold an attentive expression for 0.5–1.5 seconds
  before speech without filling the pause with motion.

## UI system

The reference dashboard is the long-term visual north star. The v0.1 Unreal
screen should use fewer simultaneous panels so Mira remains the focal point.

### V0.1 layout

- Left rail: Home, Focus, Review, Settings.
- Centre: avatar, current speech/subtitle card, and voice/text input dock.
- Right rail: Next Up card and compact Today summary.
- Focus Mode: collapse both rails and show only avatar, active task, countdown,
  pause/complete controls, and interruption input.

Defer energy graphs, streaks, quotes, roadmap, workspace, notifications, and the
large bottom note strip until their underlying data is real and useful.

### Visual tokens

- Canvas: near-black `#090A0C`.
- Panels: charcoal `#141416` at 88–94% opacity.
- Panel border: warm gray `#403830` at low opacity.
- Primary text: warm off-white `#F1ECE5`.
- Secondary text: muted gray `#AAA6A2`.
- Warm identity accent: amber `#E6AD72`.
- Action accent: violet `#7658EA`.
- Success: restrained green `#62C978`.
- Corner radius: 12–16 px equivalent; borders 1 px; shadows soft and sparse.
- Typography: clean humanist sans for UI; the handwritten Mira wordmark is a
  brand accent only and should never be used for functional text.

## Unreal implementation order

1. Gray-box the layout in UMG using a placeholder portrait or basic character.
2. Wire `OnMiraThinking` and `OnMiraResponse` from the connection subsystem.
3. Map state, expression, gesture, subtitle, and UI actions without lip sync.
4. Build the MetaHuman-style character and the six required facial cues.
5. Add audio playback and viseme/lip-sync support.
6. Add mode-specific lighting and clothing variations only after the main loop
   is stable and performant.

## Acceptance test for the first visual slice

Given a progress report that completes one task and starts a Focus session, the
screen must show thinking feedback, deliver Mira's concise response, transition
to the focused expression with a small nod, update the task, and enter the
reduced Focus Mode layout. The face, voice, subtitle, and UI state must agree.
