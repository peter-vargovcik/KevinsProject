#!/usr/bin/env python3
"""Generate student project guide as .docx (with flowchart diagram images)."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "Student_Project_Guide.docx"
IMG_DIR = ROOT / "docs" / "_guide_diagrams"


def _font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def _box(draw, xy, text, fill, outline, font):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=8, fill=fill, outline=outline, width=2)
    lines = _wrap(draw, text, font, x1 - x0 - 16)
    total = sum(font.getbbox(ln)[3] - font.getbbox(ln)[1] + 2 for ln in lines)
    y = y0 + (y1 - y0 - total) / 2
    for ln in lines:
        tw = draw.textlength(ln, font=font)
        draw.text((x0 + (x1 - x0 - tw) / 2, y), ln, fill=(30, 30, 30), font=font)
        y += font.getbbox(ln)[3] - font.getbbox(ln)[1] + 2


def _arrow(draw, a, b, color=(21, 101, 192)):
    draw.line([a, b], fill=color, width=3)
    import math

    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    size = 10
    p1 = (b[0] - size * math.cos(ang - 0.4), b[1] - size * math.sin(ang - 0.4))
    p2 = (b[0] - size * math.cos(ang + 0.4), b[1] - size * math.sin(ang + 0.4))
    draw.polygon([b, p1, p2], fill=color)


def save_diagrams() -> dict[str, Path]:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    font = _font(15, bold=True)
    font_sm = _font(13, bold=True)
    caption_f = _font(14)
    paths: dict[str, Path] = {}

    # --- system overview ---
    im = Image.new("RGB", (1000, 420), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((300, 12), "System overview — who talks to whom", fill=(90, 90, 90), font=caption_f)
    _box(d, (40, 80, 220, 180), "CSI Camera", (232, 245, 233), (46, 125, 50), font)
    _box(d, (280, 70, 520, 200), "Raspberry Pi 4 brain + Wi-Fi + dashboard", (227, 242, 253), (25, 118, 210), font)
    _box(d, (560, 80, 780, 180), "RP2040 motor brain", (255, 243, 224), (249, 168, 37), font)
    _box(d, (820, 80, 960, 180), "RC car", (252, 228, 236), (198, 40, 40), font)
    _box(d, (40, 280, 220, 380), "LEDs G / Y / R", (255, 253, 231), (249, 168, 37), font)
    _box(d, (280, 280, 520, 380), "Phone / laptop browser", (237, 231, 246), (94, 53, 177), font)
    _box(d, (560, 280, 780, 380), "3× HC-SR04 sonars", (224, 247, 250), (0, 131, 143), font)
    _arrow(d, (220, 130), (280, 130))
    _arrow(d, (520, 130), (560, 130))
    _arrow(d, (780, 130), (820, 130))
    _arrow(d, (400, 200), (400, 280))
    _arrow(d, (670, 180), (670, 280))
    _arrow(d, (280, 330), (220, 330))
    p = IMG_DIR / "01_system_overview.png"
    im.save(p)
    paths["system"] = p

    # --- connect school ---
    im = Image.new("RGB", (1000, 340), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((280, 10), "School / demo connection procedure", fill=(90, 90, 90), font=caption_f)
    steps = [
        (30, "1. Phone hotspot ON"),
        (270, "2. Power the Pi"),
        (510, "3. Join hotspot on laptop"),
        (750, "4. Open browser"),
    ]
    for x, t in steps:
        _box(d, (x, 60, x + 200, 150), t, (227, 242, 253), (25, 118, 210), font_sm)
    for x in (230, 470, 710):
        _arrow(d, (x, 105), (x + 40, 105))
    _box(
        d,
        (180, 200, 820, 300),
        "URL: http://172.31.42.139:8088/   ·   Green LED = ready",
        (232, 245, 233),
        (46, 125, 50),
        font,
    )
    _arrow(d, (850, 150), (850, 250))
    p = IMG_DIR / "02_connect_school.png"
    im.save(p)
    paths["connect"] = p

    # --- LEDs ---
    im = Image.new("RGB", (1000, 220), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((320, 12), "LED meanings (GPIO 21 / 16 / 20)", fill=(90, 90, 90), font=caption_f)
    _box(d, (40, 60, 320, 180), "GREEN ready UART + UI up", (200, 230, 201), (46, 125, 50), font)
    _box(d, (360, 60, 640, 180), "YELLOW armed detection on", (255, 249, 196), (249, 168, 37), font)
    _box(d, (680, 60, 960, 180), "RED wrong / pullover / no Wi-Fi blink", (255, 205, 210), (198, 40, 40), font)
    p = IMG_DIR / "03_leds.png"
    im.save(p)
    paths["leds"] = p

    # --- dashboard tabs ---
    im = Image.new("RGB", (1000, 260), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((300, 10), "Dashboard layout (browser port 8088)", fill=(90, 90, 90), font=caption_f)
    tabs = [
        (20, "Sonar: distances F/L/R"),
        (210, "Pullover: manual + params"),
        (400, "Detection: arm + preview"),
        (590, "Drive: joystick + caps"),
        (780, "Log: events"),
    ]
    for x, t in tabs:
        _box(d, (x, 50, x + 180, 150), t, (227, 242, 253), (25, 118, 210), font_sm)
    _box(
        d,
        (20, 180, 980, 240),
        "Always visible: status strip + Quick actions + STOP / Power off",
        (245, 245, 245),
        (120, 120, 120),
        font_sm,
    )
    p = IMG_DIR / "04_dashboard.png"
    im.save(p)
    paths["dashboard"] = p

    # --- detection workflow ---
    im = Image.new("RGB", (1000, 480), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((300, 8), "Detection → auto pull-over workflow", fill=(90, 90, 90), font=caption_f)
    top = [
        (20, "Arm detection (yellow LED)"),
        (250, "Camera + TFLite each N frames"),
        (500, "Count consecutive WRONG"),
        (750, "N reached?"),
    ]
    for x, t in top:
        _box(d, (x, 40, x + 210, 120), t, (227, 242, 253), (25, 118, 210), font_sm)
    for x in (230, 460, 710):
        _arrow(d, (x, 80), (x + 20, 80))
    _box(d, (750, 160, 960, 240), "No → keep watching", (245, 245, 245), (120, 120, 120), font_sm)
    _box(d, (480, 160, 720, 240), "Yes → PULLOVER side", (255, 235, 238), (198, 40, 40), font_sm)
    _box(d, (480, 280, 720, 360), "Creep + steer to wall", (255, 243, 224), (249, 168, 37), font_sm)
    _box(d, (480, 380, 720, 460), "Side in band → DONE", (232, 245, 233), (46, 125, 50), font_sm)
    _arrow(d, (855, 120), (855, 160))
    _arrow(d, (750, 200), (720, 200))
    _arrow(d, (600, 240), (600, 280))
    _arrow(d, (600, 360), (600, 380))
    # loop line
    d.line([(855, 240), (855, 260), (140, 260), (140, 80)], fill=(120, 120, 120), width=2)
    _arrow(d, (140, 260), (140, 120))
    p = IMG_DIR / "05_detection_pullover.png"
    im.save(p)
    paths["detect"] = p

    # --- boot wifi ---
    im = Image.new("RGB", (1000, 420), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((360, 8), "Boot workflow — which Wi-Fi?", fill=(90, 90, 90), font=caption_f)
    _box(d, (390, 40, 610, 100), "Pi powers on", (227, 242, 253), (25, 118, 210), font)
    _box(d, (390, 130, 610, 190), "Wi-Fi chooser", (227, 242, 253), (25, 118, 210), font)
    _arrow(d, (500, 100), (500, 130))
    _box(d, (40, 230, 300, 320), "Hotspot seen? Connect (priority)", (232, 245, 233), (46, 125, 50), font_sm)
    _box(d, (360, 230, 640, 320), "Else home Wi-Fi (dev)", (227, 242, 253), (25, 118, 210), font_sm)
    _box(d, (700, 230, 960, 320), "Else blink RED forever", (255, 235, 238), (198, 40, 40), font_sm)
    _box(d, (360, 350, 640, 410), "Start dashboard :8088", (232, 245, 233), (46, 125, 50), font)
    _arrow(d, (500, 190), (500, 230))
    _arrow(d, (390, 275), (300, 275))
    _arrow(d, (610, 275), (700, 275))
    _arrow(d, (500, 320), (500, 350))
    d.line([(170, 320), (170, 380), (360, 380)], fill=(21, 101, 192), width=3)
    _arrow(d, (360, 380), (360, 380))
    p = IMG_DIR / "06_boot_wifi.png"
    im.save(p)
    paths["boot"] = p

    return paths


def set_run_font(run, size=11, bold=False, color=None, italic=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.italic = italic
    run.font.name = "Calibri"
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:eastAsia"), "Calibri")
    if color:
        run.font.color.rgb = RGBColor(*color)


def add_h(doc: Document, text: str, level: int = 1):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        set_run_font(run, 16 if level == 1 else 13, bold=True, color=(13, 71, 161))


def add_p(doc: Document, text: str, *, italic: bool = False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    set_run_font(run, 11)
    run.italic = italic
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.space_before = Pt(0)
    return p


def add_bullets(doc: Document, items: list[str]):
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        run = p.add_run(item)
        set_run_font(run, 11)
        p.paragraph_format.space_after = Pt(2)


def add_table(doc: Document, headers: list[str], rows: list[list[str]]):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        run = hdr[i].paragraphs[0].add_run(h)
        set_run_font(run, 10, bold=True, color=(255, 255, 255))
        from docx.oxml import OxmlElement

        tc = hdr[i]._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), "0D47A1")
        shd.set(qn("w:val"), "clear")
        tcPr.append(shd)
    for r_i, row in enumerate(rows):
        for c_i, val in enumerate(row):
            cell = table.rows[r_i + 1].cells[c_i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(val)
            set_run_font(run, 10)
    doc.add_paragraph()


def add_fig(doc: Document, path: Path, caption: str):
    doc.add_picture(str(path), width=Cm(16.5))
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(caption)
    set_run_font(run, 9, italic=True, color=(90, 90, 90))
    p.paragraph_format.space_after = Pt(12)


def build():
    diagrams = save_diagrams()
    doc = Document()

    # narrow margins a bit
    for section in doc.sections:
        section.top_margin = Cm(1.6)
        section.bottom_margin = Cm(1.6)
        section.left_margin = Cm(1.8)
        section.right_margin = Cm(1.8)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("Wrong-Way Arrow + Smart Pull-Over Car")
    set_run_font(run, 22, bold=True, color=(26, 26, 26))

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run(
        "Student project guide (age ~16) · Raspberry Pi 4 · RP2040 · Flask dashboard · School demo Wi‑Fi"
    )
    set_run_font(run, 10, color=(85, 85, 85))

    add_h(doc, "1. What is this project?")
    add_p(
        doc,
        "This project is a small radio-control (RC) car that can think with two computers: a Raspberry Pi 4 "
        "(camera, Wi‑Fi, web dashboard, AI) and an RP2040 microcontroller (motors, steering, ultrasonic sensors). "
        "Together they can detect a road arrow that points the wrong way and gently pull over toward a wall using "
        "distance sensors — like a simplified parking / safety manoeuvre.",
    )
    note = doc.add_paragraph()
    run = note.add_run(
        "Safety first: keep wheels lifted or clear space for first tests. Always know where the STOP button is. "
        "Never aim sensors or the car at people’s faces."
    )
    set_run_font(run, 11, bold=True, color=(120, 80, 0))

    add_h(doc, "2. Big picture — the parts")
    add_fig(doc, diagrams["system"], "Figure 1. Main components and how they connect.")

    add_h(doc, "2.1 Hardware components", level=2)
    add_table(
        doc,
        ["Part", "What it does (simple words)"],
        [
            ["Raspberry Pi 4", "The ‘laptop brain’: Wi‑Fi, camera AI, web page for control."],
            ["CSI camera", "Looks at arrows on the road / paper signs."],
            ["RP2040 board", "The ‘motor brain’: drives ESC + steering servo, reads sonars."],
            ["HC-SR04 ×3", "Ultrasonic ‘tape measures’: front, left, right distances in cm."],
            ["Dual 10 kΩ dividers", "Protect inputs from 5 V echo pulses (drop to ~3.3 V)."],
            ["LEDs (G/Y/R)", "Status lights: ready / armed / alert without a screen."],
            ["RC transmitter", "Must be on with a live receiver; Pi can take over without stick centering."],
        ],
    )

    add_h(doc, "2.2 Software components", level=2)
    add_bullets(
        doc,
        [
            "BT_project_v5 firmware on the RP2040 — UART commands: DRIVE, PULLOVER, SONAR, CAP, STOP…",
            "Flask RC test console (sonar_debug_server.py) on port 8088 — the dashboard.",
            "Teachable Machine TFLite model — classes mapped to correct / wrong / none (quantized for speed).",
            "wifi-chooser on boot — prefers school hotspot, else home Wi‑Fi; blinks red if offline.",
            "systemd services — start automatically after power-on.",
        ],
    )

    add_h(doc, "3. How the brains talk (UART)")
    add_p(
        doc,
        "The Pi and RP2040 speak a simple text language over a serial wire (UART) at 115200 baud. "
        "Each command is one line. Examples: PULLOVER,RIGHT · SONAR,ON · STATUS?. "
        "The dashboard turns button clicks into these messages so you do not need a terminal for demos.",
    )
    add_p(
        doc,
        "Pi GPIO14 TX → RP2040 GP13 RX · RP2040 GP12 TX → Pi GPIO15 RX · common GND",
        italic=True,
    )

    add_h(doc, "4. Connecting for a school demo (hotspot)")
    add_p(
        doc,
        "At school you usually cannot use the home Wi‑Fi. We use a phone hotspot. "
        "The Pi already knows SSID Galaxy A20eFF3F and prefers it on boot. "
        "Its fixed hotspot address is 172.31.42.139.",
    )
    add_fig(doc, diagrams["connect"], "Figure 2. Connection steps for a classroom demo.")

    add_h(doc, "Step-by-step checklist", level=2)
    add_bullets(
        doc,
        [
            "Turn on the phone hotspot before powering the Pi.",
            "Power the Pi (USB‑C). Wait ~30–60 s. Green LED should light when console + UART are ready.",
            "On the presenter laptop/phone: join the same hotspot.",
            "Open a browser to http://172.31.42.139:8088/",
            "If the page does not load: check red LED (blinking = no Wi‑Fi). Confirm hotspot password and that the Pi appears in the phone’s client list.",
            "When finished: use Power off Pi in the header (confirm dialog) — safer than yanking power.",
        ],
    )

    add_h(doc, "Home / development network", level=2)
    add_p(
        doc,
        "At home the Pi may use Wi‑Fi eir63498627_2GEXT / 5GEXT with address 192.168.1.152. "
        "Dashboard: http://192.168.1.152:8088/. Boot chooser: hotspot first if visible, otherwise home.",
    )

    add_h(doc, "5. LED meanings")
    add_fig(doc, diagrams["leds"], "Figure 3. Status LEDs on the Pi.")
    add_bullets(
        doc,
        [
            "Green (GPIO21) — system ready: Flask dashboard up and UART to RP2040 healthy.",
            "Yellow (GPIO16) — detection armed: camera + AI loop running.",
            "Red (GPIO20) — wrong-way streak / pull-over active; or blinking at boot if no Wi‑Fi.",
        ],
    )

    add_h(doc, "6. The web dashboard (port 8088)")
    add_p(
        doc,
        "The dashboard is a website served by the Pi. Anyone on the same Wi‑Fi can open it. "
        "It is split into tabs so it stays tidy. A status strip and Quick actions stay visible at the top.",
    )
    add_fig(doc, diagrams["dashboard"], "Figure 4. Dashboard tabs.")

    add_h(doc, "6.1 Header buttons (always available)", level=2)
    add_table(
        doc,
        ["Button", "Meaning"],
        [
            ["Refresh STATUS", "Ask the RP2040 for a fresh status line."],
            ["STOP", "Emergency stop — latches until RESET."],
            ["RESET", "Clear a latched STOP when it is safe."],
            ["MANUAL", "Return toward normal RC / manual mode."],
            ["Power off Pi", "Shuts down the Raspberry Pi cleanly (asks for confirmation)."],
        ],
    )

    add_h(doc, "6.2 Quick actions", level=2)
    add_bullets(
        doc,
        [
            "PULLOVER LEFT / RIGHT — start the ultrasonic manoeuvre immediately.",
            "ABORT — cancel an active pull-over.",
            "Arm / Disarm detection — start or stop the camera AI loop.",
        ],
    )

    add_h(doc, "6.3 Tab: Sonar", level=2)
    add_p(
        doc,
        "Shows live distances from Front / Left / Right HC-SR04 sensors (cm). "
        "Use Sonar ON for continuous readings without driving.",
    )

    add_h(doc, "6.4 Tab: Pullover", level=2)
    add_p(
        doc,
        "Manual pull-over controls plus tunable parameters (side target, band, front stop, creep, steer, stable, timeout).",
    )
    add_table(
        doc,
        ["Parameter", "Default idea", "Student meaning"],
        [
            ["Side target", "10 cm", "How close to the wall is ‘parked’."],
            ["Band", "±2 cm", "Acceptable window around the target."],
            ["Front stop", "25 cm", "Abort if something is too close ahead."],
            ["Creep", "~10%", "Slow forward throttle during the manoeuvre."],
            ["Steer max", "~28%", "How hard it steers toward/away from the wall."],
            ["Stable", "400 ms", "How long it must stay in-band before DONE."],
            ["Timeout", "15 s", "Give up if it never settles."],
        ],
    )

    add_h(doc, "6.5 Tab: Detection", level=2)
    add_p(
        doc,
        "Arms the camera model. When enabled, an MJPEG preview can appear (only while armed). "
        "You can set how many consecutive wrong frames are required before an automatic pull-over. "
        "Model labels: frwrd → correct, rvrs → wrong, Contrl → none.",
    )

    add_h(doc, "6.6 Tab: Drive", level=2)
    add_p(
        doc,
        "Virtual joystick for Wi‑Fi testing. Turn Pi control ON first. "
        "Throttle caps default to 25% so first tests are gentle.",
    )

    add_h(doc, "6.7 Tab: Log", level=2)
    add_p(doc, "Scrolling list of events from the RP2040 and Pi — great for debugging demos.")

    add_h(doc, "7. Detection → pull-over workflow")
    add_fig(doc, diagrams["detect"], "Figure 5. From ‘wrong arrow’ to parked beside the wall.")
    add_bullets(
        doc,
        [
            "Arm detection → yellow LED on; camera frames are classified.",
            "Each accepted wrong increases a streak counter (configurable N, default 5).",
            "correct or none can reset the streak (configurable).",
            "When streak ≥ N and cooldown allows → send PULLOVER,LEFT|RIGHT.",
            "RP2040 creeps forward, steers using the side sonar until distance is in the target band, then finishes.",
            "Front sonar too close → ERR,PULLOVER,FRONT emergency stop path.",
        ],
    )

    add_h(doc, "8. Boot Wi‑Fi workflow")
    add_fig(doc, diagrams["boot"], "Figure 6. What happens when you power the Pi.")

    add_h(doc, "9. Sonar wiring (why dividers matter)")
    add_p(
        doc,
        "HC-SR04 modules run at 5 V. Their ECHO pin can output 5 V pulses. The RP2040 GPIO is 3.3 V only. "
        "We use a dual 10 kΩ resistor divider on each ECHO line so the microcontroller sees a safe voltage.",
    )
    add_table(
        doc,
        ["Sensor", "TRIG", "ECHO (via divider)"],
        [
            ["Front", "GP14", "GP15"],
            ["Left", "GP8", "GP9"],
            ["Right", "GP16", "GP17"],
        ],
    )

    add_h(doc, "10. Suggested classroom demo script")
    add_bullets(
        doc,
        [
            "Show the car + Pi + sensors (30 s).",
            "Open the dashboard on the projector (hotspot URL).",
            "Sonar tab: wave a hand — distances change live.",
            "Detection tab: show preview; hold a ‘wrong’ arrow until red / pull-over triggers (wheels safe).",
            "Explain LEDs and STOP button.",
            "Power off cleanly from the header.",
        ],
    )

    add_h(doc, "11. Troubleshooting for students")
    add_table(
        doc,
        ["Symptom", "Try this"],
        [
            ["Red LED blinking, no page", "Hotspot on? Same SSID? Wait 1 min; check phone client list."],
            ["Page loads, green off", "UART cable / RP2040 power; Refresh STATUS; check firmware."],
            ["Sonar stuck at — or −1", "Wiring, 5 V supply, divider, flat target surface."],
            ["Detection won’t arm", "Camera ribbon seated; model files present; read Log / error strip."],
            ["Pull-over hits wall", "Increase side target; check sensor angle; lower creep."],
            ["Joystick does nothing", "Pi control ON; caps > 0; transmitter on / rcOK = 1."],
        ],
    )

    add_h(doc, "12. Glossary")
    add_bullets(
        doc,
        [
            "UART — serial text link between Pi and RP2040.",
            "GPIO — general-purpose input/output pin.",
            "TFLite — tiny neural-network format that runs on the Pi.",
            "DHCP / static IP — automatic vs fixed address on Wi‑Fi.",
            "Hotspot — phone shares a local Wi‑Fi for the demo.",
            "Pull-over — slow steer-and-creep manoeuvre using side distance.",
        ],
    )

    foot = doc.add_paragraph()
    run = foot.add_run(
        "Project files: /home/pi/KevinsProject on the Pi. Matches Flask console :8088, firmware BT_project_v5, "
        "and wifi-chooser. Companion PDF: docs/Student_Project_Guide.pdf"
    )
    set_run_font(run, 9, italic=True, color=(90, 90, 90))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
