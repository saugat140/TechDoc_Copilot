"""Generate a small industrial-manual-style PDF for ingestion smoke tests.

Writes backend/data/raw/sample_drive_manual.pdf (gitignored).

Pages:
  1. Native prose (safety + overvoltage symptom)
  2. Fault-code table (tab-separated so chunker keeps it intact)
  3. Native prose procedure
  4. Diagram page with an embedded image
  5. Image-only "scanned" page (text drawn into a PNG, no PDF text)
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont

BACKEND_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = BACKEND_ROOT / "data" / "raw" / "sample_drive_manual.pdf"

FAULT_ROWS = [
    ("Code", "Name", "Typical cause", "First check"),
    ("3210", "DC overvoltage", "Decel too fast / resistor open", "Ramp, brake resistor"),
    ("3220", "DC undervoltage", "Supply dip or loose input", "Mains, fuses, wiring"),
    ("2310", "Overcurrent", "Short, mechanical jam", "Motor cables, load"),
    ("4210", "IGBT overtemperature", "Blocked airflow or high ambient", "Fan, heatsink, cabinet"),
    ("5090", "STO active", "STO inputs open", "STO wiring, safety relay"),
    ("7510", "Communication timeout", "Fieldbus cable or terminator", "Bus, node ID, baud"),
]

INTRO = """ACS880 Drive Troubleshooting Guide (sample excerpt)

This excerpt is for pipeline testing only. It mimics the structure of an
industrial drive manual: safety notes, a fault-code table, and a wiring
diagram placeholder.

Safety
Disconnect mains and wait five minutes for DC bus capacitors to discharge
before measuring terminals. Use a meter rated for the drive voltage class.
Do not defeat the Safe Torque Off circuit while diagnosing a trip.

Symptom: drive trips on overvoltage during deceleration
1. Confirm the fault code on the control panel is 3210 DC overvoltage.
2. Check deceleration time. Increase ramp-down if the load is high inertia.
3. Inspect the brake resistor and chopper if a braking option is installed.
4. Measure DC bus voltage while stopping. Compare to the trip threshold
   in the hardware manual for this frame size.
5. If the resistor is open, replace it and retest with a reduced speed
   reference before returning the machine to production.
"""

PROCEDURE = """Detailed procedure for fault 3210 DC overvoltage

Context
The DC bus rises when the motor regenerates into the drive faster than the
bus can absorb. High-inertia loads and short deceleration times are the
usual combination. A failed brake resistor looks the same on the keypad.

Checks in order
Measure input voltage on L1 L2 L3 under load. If the supply is already high,
fix that first. Then lengthen parameter 22.02 deceleration time by 50 percent
and repeat the stop. If the trip remains, inspect the brake chopper and
resistor with power isolated. An open resistor reads infinite ohms at the
chopper terminals.

If the trip only happens on emergency stop, the ramp is being bypassed.
Confirm that emergency-stop handling is coast-to-stop or uses a dedicated
braking path, not a faster ramp into an already high bus.
"""


def _add_text_page(doc: fitz.Document, title: str, body: str) -> None:
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), title, fontsize=14, fontname="helv")
    page.insert_textbox(
        fitz.Rect(50, 80, 545, 800),
        body,
        fontsize=10,
        fontname="helv",
        align=fitz.TEXT_ALIGN_LEFT,
    )


def _add_table_page(doc: fitz.Document) -> None:
    """Tab-separated rows in Courier so extracted text still looks tabular."""
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "Fault codes", fontsize=14, fontname="helv")
    page.insert_text((50, 80), "Fault code reference", fontsize=11, fontname="helv")
    y = 110
    for row in FAULT_ROWS:
        page.insert_text((50, y), "\t".join(row), fontsize=9, fontname="cour")
        y += 16
    page.insert_textbox(
        fitz.Rect(50, y + 16, 545, 280),
        "Notes\n"
        "Codes 3210 and 3220 are DC bus events. Always verify supply quality "
        "before replacing the drive. Code 5090 is not a power-circuit failure.",
        fontsize=10,
        fontname="helv",
    )


def _add_diagram_page(doc: fitz.Document) -> None:
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "Figure 4-2  Brake chopper connections", fontsize=14)
    page.insert_textbox(
        fitz.Rect(50, 80, 545, 140),
        "Typical R+ / R- brake resistor terminals on the power unit. "
        "Keep leads short and twisted. Do not share this cable with STO wiring.",
        fontsize=10,
        fontname="helv",
    )
    # Embedded PNG so loader.extract_page_images has something to list.
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 320, 160), False)
    pix.clear_with(230)
    page.insert_image(fitz.Rect(50, 160, 370, 320), pixmap=pix)
    page.insert_text((50, 340), "R+  resistor  R-     (frame R4 shown)", fontsize=10)


def _add_scanned_page(doc: fitz.Document) -> None:
    """Rasterized-only page: little/no native text so loader flags OCR."""
    img = Image.new("RGB", (1000, 400), (245, 245, 245))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((40, 40), "FIELD SERVICE NOTE  (scanned)", fill=(20, 20, 20), font=font)
    draw.text(
        (40, 100),
        "Brake resistor measured 12.4 ohm. Replace if greater than 15 ohm.",
        fill=(20, 20, 20),
        font=font,
    )
    draw.text(
        (40, 140),
        "STO jumpers intact. Fan intake blocked with dust — cleaned.",
        fill=(20, 20, 20),
        font=font,
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(50, 80, 545, 280), stream=buf.getvalue())
    # No PDF text operators — native extract should be empty / below the OCR threshold.


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    _add_text_page(doc, "ACS880 Drive Troubleshooting Guide", INTRO)
    _add_table_page(doc)
    _add_text_page(doc, "Fault 3210 procedure", PROCEDURE)
    _add_diagram_page(doc)
    _add_scanned_page(doc)

    tmp_path = OUT_PATH.with_name(OUT_PATH.stem + ".tmp.pdf")
    doc.save(tmp_path)
    doc.close()
    try:
        tmp_path.replace(OUT_PATH)
        written = OUT_PATH
    except PermissionError:
        fallback = OUT_PATH.with_name("sample_drive_manual_new.pdf")
        try:
            tmp_path.replace(fallback)
            written = fallback
        except PermissionError:
            written = tmp_path
        print(
            "Could not overwrite sample_drive_manual.pdf "
            "(it is open in a viewer, Explorer preview, or uvicorn)."
        )
        print("Close that file, or upload this copy instead:")
        print(f"wrote {written}")
        return
    print(f"wrote {written}")


if __name__ == "__main__":
    sys.exit(main() or 0)
