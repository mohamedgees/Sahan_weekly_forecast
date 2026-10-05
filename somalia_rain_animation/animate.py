"""Assemble PNG frames into a GIF and an MP4."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

FRAME_S = 1.5
LAST_S = 5.0    # final frame (weekly total) stays longer


def make_gif(frames: list[Path], out: Path, width: int = 1600):
    rgb = []
    for f in frames:
        im = Image.open(f).convert("RGB")
        rgb.append(im.resize((width, round(im.height * width / im.width)), Image.LANCZOS))
    # One palette shared by every frame, so the legend and fixed parts never shift colour.
    # The rainfall class colours are reserved in it exactly; the rest comes from all frames.
    from . import config
    from matplotlib.colors import to_rgb
    classes = [tuple(round(v * 255) for v in to_rgb(c)) for c in dict.fromkeys(config.CLASS_COLOURS)]
    strip = Image.new("RGB", (width, sum(i.height for i in rgb) // 4))
    y = 0
    for im in rgb:
        small = im.resize((width, im.height // 4))
        strip.paste(small, (0, y)); y += small.height
    base = strip.quantize(colors=256 - len(classes), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = [v for c in classes for v in c] + base.getpalette()[: 3 * (256 - len(classes))]
    pimg = Image.new("P", (1, 1)); pimg.putpalette(pal)
    imgs = [im.quantize(palette=pimg, dither=Image.Dither.NONE) for im in rgb]
    durations = [int(FRAME_S * 1000)] * (len(imgs) - 1) + [int(LAST_S * 1000)]
    imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=durations, loop=0, optimize=True)
    print(f"  GIF: {out}")


PLAYER_HTML = """<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
         background: #0B2545; font-family: system-ui, sans-serif; }}
  figure {{ margin: 0; padding: 16px; width: min(100%, 900px); box-sizing: border-box; }}
  video {{ width: 100%; height: auto; display: block; border-radius: 6px; background: #000; cursor: pointer; }}
  .bar {{ display: flex; justify-content: center; margin-top: 12px; }}
  button {{ border: 0; border-radius: 999px; padding: 10px 22px; font-size: 15px; font-weight: 600;
           color: #0B2545; background: #fff; cursor: pointer; }}
  button:focus-visible {{ outline: 3px solid #E08B5F; outline-offset: 2px; }}
</style>
</head>
<body>
<figure>
  <video id="v" src="{video}" autoplay muted loop playsinline preload="auto" controls></video>
  <div class="bar"><button id="b" type="button" aria-controls="v">Pause</button></div>
</figure>
<script>
  const v = document.getElementById("v"), b = document.getElementById("b");
  const sync = () => {{ b.textContent = v.paused ? "Play" : "Pause"; }};
  const toggle = () => {{ v.paused ? v.play() : v.pause(); }};
  b.addEventListener("click", toggle);
  v.addEventListener("click", e => {{ e.preventDefault(); toggle(); }});
  v.addEventListener("play", sync); v.addEventListener("pause", sync);
  v.play().catch(sync); sync();
</script>
</body>
</html>
"""


def make_player(video: Path, title: str):
    """Small web page: the MP4 autoplays (muted, as browsers require), loops,
    and can be paused and resumed with the button, a click or the controls."""
    out = video.with_suffix(".html")
    out.write_text(PLAYER_HTML.format(title=title, video=video.name), encoding="utf-8")
    print(f"  Player: {out}")
    return out


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    for cand in (Path(sys.prefix) / "Library" / "bin" / "ffmpeg.exe", Path(sys.prefix) / "bin" / "ffmpeg"):
        if cand.exists():
            return str(cand)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def make_mp4(frames: list[Path], out: Path):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("  MP4 skipped: ffmpeg not found (install it, see README).")
        return
    lst = out.with_suffix(".txt")
    lines = []
    for i, f in enumerate(frames):
        lines += [f"file '{f.resolve().as_posix()}'", f"duration {LAST_S if i == len(frames) - 1 else FRAME_S}"]
    lines.append(f"file '{frames[-1].resolve().as_posix()}'")  # concat demuxer needs the last file repeated
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
           "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p", "-r", "30",
           "-c:v", "libx264", "-preset", "slow", "-tune", "stillimage", "-crf", "14",
           "-profile:v", "high", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    lst.unlink()
    print(f"  MP4: {out}")
