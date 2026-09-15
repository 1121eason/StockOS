"""PDF narrative extraction. Transcript V1 retains only identified NVIDIA management turns."""

import io
import re

from pypdf import PdfReader

MANAGEMENT = re.compile(
    r"^(?:Colette(?: M\.)? Kress|Jen Hsun Huang|Jensen Huang|Toshiya Hari|Simona Jankowski)\s*$",
    re.I,
)
RULE = re.compile(r"^\.{6,}|^_{6,}|^-{6,}")


def paragraphs(content, transcript=False):
    pages = PdfReader(io.BytesIO(content)).pages
    active = not transcript
    speaker = None
    started = not transcript
    output = []
    for page_no, page in enumerate(pages, 1):
        text = page.extract_text() or ""
        lines = text.splitlines()
        buffer: list[str] = []

        def flush(active, speaker, buffer=buffer, page_no=page_no):
            value = " ".join(buffer).strip()
            if active and len(value) > 35:
                output.append({"section": f"PDF page {page_no}", "text": value, "speaker": speaker})
            buffer.clear()

        for i, line in enumerate(lines):
            line = " ".join(line.split())
            if "MANAGEMENT DISCUSSION SECTION" in line or "QUESTION AND ANSWER SECTION" in line:
                started = True
                continue
            if not started:
                continue
            if not line or RULE.match(line):
                flush(active, speaker)
                continue
            if MANAGEMENT.match(line):
                flush(active, speaker)
                role = " ".join(lines[i + 1 : i + 3])
                active = not transcript or bool(
                    re.search(r"NVIDIA|Chief|President|Investor", role, re.I)
                )
                speaker = line if active else None
                continue
            if transcript and (
                re.search(r"\bAnalyst\b|^Operator:", line)
                or re.search(r"\bAnalyst\b", " ".join(lines[i + 1 : i + 2]))
            ):
                flush(active, speaker)
                active = False
                speaker = None
                continue
            if re.search(
                r"Corrected Transcript|Copyright|FactSet|callstreet.com|^Total Pages|^NVIDIA Corp\.|^Q[1-4] .*Earnings Call",
                line,
                re.I,
            ):
                continue
            if (
                line.isdigit()
                or "NVIDIA Corp." in line
                and ("Officer" in line or "President" in line)
            ):
                continue
            buffer.append(line)
        flush(active, speaker)
    return output
