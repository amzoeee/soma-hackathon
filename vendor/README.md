# Vendored dependencies / prototypes

Everything needed for the demo lives in this monorepo so judges / teammates
don't have to chase external clones mid-hackathon.

| Path | What it is |
|------|------------|
| `xreal-eye-grayscale/` | Aloim XREAL One Pro **Eye** grayscale TCP stream tools (Nebula beta + Spatial Anchor required). Upstream: https://github.com/Aloim/Grayscale-Feed-Xreal-One-Pro-Eye-Windows-Nebula-Beta-needed- |
| `armteleop-prototype/` | Early hand→arm prototype (`m0`/`m1`/`m2`) kept as a fallback reference. **Production path is `robot/`.** |

## Quick Eye stream smoke test

```bash
cd vendor/xreal-eye-grayscale
pip install -r requirements.txt   # skip netifaces if MSVC build fails — IP is hardcoded
cd src
python live_video_viewer.py
```

Spatial Anchor **must** be ON or the TCP port connects with no video.

## Production teleop

```bash
cd robot
python -m src.main --port COM5
```
