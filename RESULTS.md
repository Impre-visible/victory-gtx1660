# Results

All runs on one machine, first playable scene, console profile "Series S",
same sandbox and the same launcher settings (cool_fox's "pareto-residency"
profile, see `scripts/settings.env`) unless a row says otherwise.

## Machine

| | |
|---|---|
| GPU | GeForce GTX 1660, 6 GB |
| CPU | Core i7-13700KF |
| RAM | 62 GB |
| OS | Arch Linux, kernel 6.18 LTS |
| Driver | NVIDIA 620.73.04, open kernel modules rebuilt with NVIDIA PR #1542 (issue #1540: random kernel soft lockups) |
| Wine | GE-Proton11-6, vkd3d-proton from Proton Experimental, DXVK `dxgi.dll`, Microsoft `d3dcompiler_47.dll` |
| Build | `scripts/build.sh` defaults: release, `--features diagnostics` |

## Method

- **Frame time** comes from the fork's own frame statistics line
  (`… fps, … ms/frame (… preparing …)`, printed at `VICTORY_LOG=info`), read
  over the steady scene once the world is shown. The range given is the spread
  of those lines; the median is noted where it was computed. No external
  frame-time tool was used.
- **"Clean"** means: the title did not stop, no "no frame presented" pause
  warning, no GPU channel fault reported by the NVIDIA driver while the scene
  ran (driver messages at the title's shutdown are not counted).
- **Split** (where noted): CPU time preparing submissions, time on the card,
  time copying results back, as reported on the same line.
- Runs were made with the screens asleep (DPMS); see the known defects in the
  README.
- Cold caches = the runner's shader, pipeline and image caches empty at start;
  warm = filled by an earlier run of the same build.

## Configurations

### A. cool_fox `f4b48ad`, unmodified

Settings: cool_fox's launcher profile as shipped (including
`VICTORY_LEVELS_ON_DEMAND=1`, `VICTORY_CARD_BUFFERS_MIN_KB=64`).

| Runs | Length | Frame time | Faults | Notes |
|---|---|---|---|---|
| 1 | 900 s asked, 764 s of scene, cold caches | 360–410 ms (2.4–2.8 fps) | clean: 0 GPU faults, 0 pauses | split: preparing 27–31 ms, copying back 17–22 ms |

Picture and work: 7 of the 16 pipeline worker threads died of a stack overflow
(vkd3d-proton's DXIL-to-SPIR-V converter recursing without end), so some
work was never done (about 600 indirect dispatches lost per frame); many
textures were missing (some untextured surfaces, dark interiors).

### B. + patches 0001–0002, texture mip drop 2

Settings: A with `VICTORY_LEVELS_ON_DEMAND=0`, `VICTORY_TEXTURE_MIP_DROP=2`.

| Runs | Length | Frame time | Faults | Notes |
|---|---|---|---|---|
| 5 | 1 × 900 s (761 s of scene, cold caches) + 4 × 420 s (warm) | 271–291 ms (3.4–3.7 fps) over the five | 5 clean of 5; 0 stack overflows; 0 GPU hangs | split (first run): preparing 26–28 ms, on the card 251–255 ms, copying back 17–19 ms |

Picture: textures back; no worker thread lost. Heads still not drawn (also
the case in A).

### C. + memory placement (the ~10 fps configuration)

Settings: B with `VICTORY_CARD_BUFFERS_MB=1024`, `VICTORY_CARD_WINDOWS_MB=768`,
`VICTORY_TEXTURE_MIP_DROP=3` (this is `scripts/settings.env`). Build: patches
0001–0004 applied, the switches of 0003 and 0004 off, so the code that ran is
that of 0001–0002.

| Runs | Length | Frame time | Faults | Notes |
|---|---|---|---|---|
| 1 (first run) | 600 s asked, 504 s of scene (about 8 min), warm caches | 100–105 ms (9.5–9.9 fps); median of the last 60 lines 102.5 ms; fastest line 90 ms | clean | split: preparing 23–25 ms, on the card 69–75 ms, copying back 13 ms |

Picture: as B, textures one mip level softer (drop 3 instead of 2); heads still
not drawn. Four further runs of 420 s with the same settings were clean, with medians of 100.6, 104.3, 106.4 and 101.4 ms per frame (264 to 320 s of scene each). The only driver messages were logged at the moment each run was stopped.

One further run with `VICTORY_TEXTURE_MIP_DROP=2` (sharper textures) and the same memory settings gave 97–100 ms per frame, clean; with drop 1 it was 115 ms (6 GB no longer hold the copies). Drop 2 with these settings was then validated on five clean runs (92–106 ms).

## D. Current settings: C with `VICTORY_CARD_WINDOWS_MB=256` and `VICTORY_TEXTURE_MIP_DROP=1`

Five clean runs of 420 s: medians 98, 112.2, 101.9, 106 and 107.7 ms per frame (270–340 s of scene each). Sharper textures than C at the same speed.

Budget sweep, runs of 330 s (compare only runs of equal length: the scene gets heavier with time, 330 s runs read about 10 ms lower than 420 s runs), `MIP_DROP=2`:

| `CARD_BUFFERS_MB` | `CARD_WINDOWS_MB` | median ms per frame |
|---|---|---|
| 1024 | 768 | 92–98, 96.5 |
| 1024 | 256 | 91.2, 90.2, 93.5 |
| 1024 | 128 | 97.8 |
| 1024 | 0 | 93.6 |
| 1280 | 512 | 106.1 |
| 1536 | 256 | 103.7 |
| 768 | 1024 | 273.7 |
| 640 | 1152 | 274.6 |

So `CARD_BUFFERS_MB=1024` carries the gain: below it the frame time returns to about 275 ms. With the monitors awake or asleep the figures are the same within noise.



## What the gain from B to C is

About 180 ms per frame. Our reading (inferred from the driver's power and bus
figures during B, not measured pass by pass): in B the card waited more than it worked: shader-written
buffers and the title's vertex/index memory lived in the PC's memory, so the card
read them across PCIe and the CPU checked them after each frame. Raising the cap
of card-side buffer copies to 1024 MB and copying 768 MB of the title's memory
windows to the card moved that traffic onto the card; the extra texture mip drop
makes room for it in 6 GB. No rendering pass is skipped by these three settings.

## 27 November 2026: longer runs, and what they corrected

Same machine (GTX 1660 6 GB, i7-13700KF, Linux, Wine GE-Proton11-6, vkd3d-proton, Series S profile).
These runs used work that is **not in this repository's patches** (see the list at the end), so
they are a report, not something `scripts/build.sh` reproduces today.

### Measure for ten minutes, not five

The frame time keeps rising during the first minutes in the world and only then settles. Runs of
330 s read 10 to 20 ms lower than the plateau. Every figure below is the median over the last
100 s of a 600 s run, or over a scripted walk of several minutes.

### The card is short of memory, not of power

With the title running, the process holds about 5.2 GB of the 6 GB. `nvidia-smi dmon` then shows
the card "100 % busy" while drawing only 42 to 47 W (it draws about 120 W under a real load) and
2 to 4 GB per second crossing PCIe in each direction: the driver keeps moving memory between the
card and the PC. Consequences, all measured at the plateau, internal render 768x432:

| change | ms per frame |
|---|---|
| reference (`CARD_BUFFERS_MB=1024`, `CARD_WINDOWS_MB=256`, mip drop 2) | 59 to 64, drifting upward |
| mip drop 3 | 59, flat |
| mip drop 3, `CARD_BUFFERS_MB=640` | **56 to 57, flat** |
| mip drop 3, `CARD_WINDOWS_MB=1024` (more of the title's memory copied to the card) | 82, drifting |
| the title's constants heap copied instead of opened in place | 85, drifting |

So on a 6 GB card, copying more to the card makes it slower once the card is full, and the
single largest item is avatarmanz's "renderer port 1" (the title's constants heap opened in place
rather than copied): about 27 ms at the plateau here. A governor that only refuses new placements
above 80 or 85 % of the budget changed nothing (55.8 and 59.3 ms against 57.5): what fills the
card is already there by then.

Things that did not help at the plateau: skipping the shadow passes (and the picture goes flat),
a 1280x720 title output instead of 1920x1080 at the same internal size (slower, 68 ms),
keeping the card awake or not, early depth test for programs that ask for it (no speed change;
it does remove a dark patch around hair).

### Internal render size

Card time is roughly 37 ms fixed plus 50 ms per megapixel on this card. Sizes must come out as
whole numbers: a scale of 0.33 of 1080p gives 633.6x356.4 and misplaced rectangles; 0.4
(768x432), 1/3 written as 0.33333334 (640x360), 0.5 and 0.25 are clean; below 0.25 the title
faults in its own code.

| internal size | ms per frame |
|---|---|
| 1280x720 | 86 to 93 (first minutes; plateau not measured) |
| 960x540 | 63 to 69 (first minutes) |
| 768x432 | 56 to 57 (plateau) |

True 720p at 20 fps is out of reach of this card by these numbers.

### Wine on Linux: the server's view list

During loading `wineserver` used about 90 % of a core here, and 22 to 29 % in the world.
[TaynanGT/Vice-Tay](https://github.com/TaynanGT/Vice-Tay) ships
`linux/wineserver/view-tree.patch` (mapped views kept in a tree instead of a list; GE-Proton11-6
does not have it). Built from GE-Proton11-6's exact sources with that one patch and mounted over
the installed binary inside the sandbox only: the server falls to 0 to 1 % of a core, the world
is entered about 35 s earlier, and 960x540 read 62.9 ms against 68.4 to 68.6 (one run each side,
taken at different world times: treat the frame-time part as unconfirmed). Credit to its author.

### Real play is faster than the first scene

All earlier figures were taken with the character standing at the first scene's window. With
scripted input the character leaves that room, follows another character through corridors and a
crowded room into an office where a dialogue plays. At 768x432, over 5 to 8 minutes of that:

| run | median ms per frame | worst 5 s line |
|---|---|---|
| 1 | 52.9 (18.9 fps) | 164.6 (a scene change) |
| 2 | 50.2 (19.9 fps) | 72.9 |
| 3 | 56.0 (17.9 fps) | 130.0 |
| 4 | 60.7 (16.5 fps) | 87.2 |

against 59 to 66 ms standing at the window in the same runs. The schedule of key presses is
wall-clock based and two runs of four got stuck at a gate, so this is not yet a benchmark.

### Missing heads: not a code defect here

Characters' heads were missing in about 39 runs of 40 for a day, then present in every run
(more than 40 so far) after the cache folder's pipeline lists and translated shaders were rebuilt
from scratch; the old and the new executable both draw them. Translation is deterministic
(the whole shader library translated three times, identical bytes), so the suspect is the saved
pipeline lists (which pipelines are made during loading), not the translator. If heads are
missing for you, move the cache folder's `pipelines` aside once and let a run rebuild it.

### What these runs used beyond this repository

- avatarmanz's renderer port 1 (constants heap in place), behind its switch;
- a render-scale switch and the title's own upscaler, from trustno1's fork (title-specific, not
  published here);
- skipping ray-tracing-only passes, from edsuuu's VI-BR-PORT;
- the wineserver patch above;
- a sharpening pass at present (ours), and a shader cache key that covers the translator's build
  features (ours).

Other trees measured on this machine the same day, built from source, their documented fastest
settings: rorodev6's megafork 77.7 ms at 960x540 (first minutes); Vice-Tay 272 to 279 ms at
640x360 with a dark picture (it lacks the texture mip drop a 6 GB card needs, among other things).

### Later the same day: steering from the picture, and the open world

A wall-clock key schedule was not reliable (two runs of four stuck at a gate). Two small additions
to our local tree fixed that: a key file the input layer re-reads while running (keys to hold now,
each with an optional duration) and the presented picture written to one file every 30 frames.
Deciding each move from the latest picture, one 25-minute run went from the first room through the
whole opening, a playable flashback with aiming and interaction prompts, into the open world:
driving a boat on a bay, with the minimap and objectives on screen. No device loss, no crash. The
title's own autosave works: restoring it puts a run back on the boat after about 330 s, which gives
a repeatable outdoor measurement.

At 768x432, same settings as the plateau table above:

| where | ms per frame |
|---|---|
| interiors (rooms, corridors, a crowded hall, dialogues) | 46 to 65 |
| the boat standing or on open water | 67 to 78 (three runs at 67 to 68 standing) |
| near a wooded shore | 93 to 120 |

The early depth test changes nothing outdoors either (67.1 standing, 99 to 119 at the shore).
Known picture defects outdoors: the water close to the boat is black; in one flashback scene a
character's clothing is blown out to white.
