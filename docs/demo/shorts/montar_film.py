"""Loop the 3D clips under the Spanish narration and burn the captions."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VOZ = ROOT / "voz"
FILM = ROOT / "film"
CLIPS = Path(
    r"C:\Users\Mariano\.grok\sessions\C%3A%5CUsers%5CMariano%5CDocuments%5CALONSOO%5CAIRBUS\01a1c1cd-d096-7cb3-ad2e-ae3427ba8c99\videos"
)
FONT = "segoeuib.ttf"
ORDER = {
    "01": CLIPS / "4.mp4",
    "02": CLIPS / "2.mp4",
    "03": CLIPS / "1.mp4",
    "04": CLIPS / "5.mp4",
    "05": CLIPS / "6.mp4",
    "06": CLIPS / "3.mp4",
    "07": CLIPS / "4.mp4",
}


def duration(path: Path) -> str:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        text=True,
    ).strip()
    return out


def chapter(key: str, clip: Path) -> None:
    wav = VOZ / f"{key}.wav"
    cap = VOZ / f"cap{key}.txt"
    dest = FILM / f"chapter-{key}.mp4"
    dur = duration(wav)
    draw = (
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,"
        f"drawtext=fontfile={FONT}:textfile={cap.name}:fontsize=78:"
        "fontcolor=white:x=(w-text_w)/2:y=150:line_spacing=12,"
        f"drawtext=fontfile={FONT}:textfile=pie.txt:fontsize=32:"
        "fontcolor=0xD6FF3F:x=(w-text_w)/2:y=h-160"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(clip),
            "-i",
            str(wav),
            "-t",
            dur,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            draw,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-shortest",
            str(dest),
        ],
        check=True,
        cwd=VOZ,
    )
    print(key, dur)


def main() -> None:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg missing")
    FILM.mkdir(exist_ok=True)
    for key, clip in ORDER.items():
        chapter(key, clip)
    listing = FILM / "list.txt"
    listing.write_text(
        "".join(f"file '{(FILM / f'chapter-{key}.mp4').as_posix()}'\n" for key in ORDER),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(ROOT / "demo-5min.mp4"),
        ],
        check=True,
    )
    print(duration(ROOT / "demo-5min.mp4"))


if __name__ == "__main__":
    main()
