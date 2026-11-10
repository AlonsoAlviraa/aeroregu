import re
from pathlib import Path

root = Path(__file__).resolve().parent
html = (root / "frames.html").read_text(encoding="utf-8")
start = html.find("<section")
end = html.rfind("</section>") + len("</section>")
head, tail = html[:start], html[end:]
for match in re.finditer(r'<section class="frame" id="([^"]+)">.*?</section>', html, re.S):
    (root / f"{match.group(1)}.html").write_text(head + match.group(0) + tail, encoding="utf-8")
    print(match.group(1))
