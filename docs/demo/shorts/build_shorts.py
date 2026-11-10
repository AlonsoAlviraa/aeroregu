"""Screenshot frames.html and encode one 9:16 short per beat group."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
GROUPS = {
    "01-asiste.mp4": ("d1", "d2", "d3"),
    "02-metodo.mp4": ("m1", "m2", "m3"),
    "03-rejilla.mp4": ("g1", "g2", "g3"),
    "04-unit-scale.mp4": ("u1", "u2", "u3"),
    "05-firma.mp4": ("s1", "s2", "s3"),
}


def split() -> None:
    html = (ROOT / "frames.html").read_text(encoding="utf-8")
    start = html.find("<section")
    end = html.rfind("</section>") + len("</section>")
    head, tail = html[:start], html[end:]
    for match in re.finditer(r'<section class="frame" id="([^"]+)">.*?</section>', html, re.S):
        (ROOT / f"{match.group(1)}.html").write_text(
            head + match.group(0) + tail, encoding="utf-8"
        )


def shoot(frame_id: str) -> None:
    page = ROOT / f"{frame_id}.html"
    png = ROOT / f"{frame_id}.png"
    url = page.as_uri()
    subprocess.run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--window-size=1080,1920",
            f"--screenshot={png}",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def encode(name: str, frames: tuple[str, ...]) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg is not on PATH")
    cmd = [ffmpeg, "-y"]
    for frame_id in frames:
        cmd.extend(["-loop", "1", "-t", "2.7", "-i", str(ROOT / f"{frame_id}.png")])
    filt = ";".join(
        f"[{i}:v]scale=1080:1920,setsar=1,fps=30[v{i}]" for i in range(len(frames))
    )
    filt += ";" + "".join(f"[v{i}]" for i in range(len(frames)))
    filt += f"concat=n={len(frames)}:v=1:a=0[v]"
    cmd.extend(
        [
            "-filter_complex",
            filt,
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(ROOT / name),
        ]
    )
    subprocess.run(cmd, check=True)


def main() -> None:
    split()
    for frames in GROUPS.values():
        for frame_id in frames:
            shoot(frame_id)
    for name, frames in GROUPS.items():
        encode(name, frames)
        print(name)


if __name__ == "__main__":
    main()
