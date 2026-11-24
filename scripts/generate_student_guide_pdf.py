#!/usr/bin/env python3
"""Generate a student-friendly PDF guide (age ~16) with diagrams and workflows."""

from __future__ import annotations

from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Rect, String, Polygon
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).resolve().parents[1] / "docs" / "Student_Project_Guide.pdf"

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#555555")
ACCENT = colors.HexColor("#0d47a1")
ACCENT2 = colors.HexColor("#1565c0")
BOX = colors.HexColor("#e3f2fd")
BOX_EDGE = colors.HexColor("#1976d2")
OK = colors.HexColor("#2e7d32")
WARN = colors.HexColor("#f9a825")
BAD = colors.HexColor("#c62828")
PANEL = colors.HexColor("#f5f5f5")


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "T",
            parent=base["Title"],
            fontSize=20,
            textColor=INK,
            spaceAfter=4,
        ),
        "sub": ParagraphStyle(
            "S",
            parent=base["Normal"],
            fontSize=10,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontSize=14,
            textColor=ACCENT,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontSize=11.5,
            textColor=ACCENT2,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "B",
            parent=base["Normal"],
            fontSize=9.8,
            leading=13.2,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
            textColor=INK,
        ),
        "bullet": ParagraphStyle(
            "Bu",
            parent=base["Normal"],
            fontSize=9.8,
            leading=12.5,
            textColor=INK,
        ),
        "caption": ParagraphStyle(
            "C",
            parent=base["Normal"],
            fontSize=8.5,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceBefore=2,
            spaceAfter=10,
        ),
        "mono": ParagraphStyle(
            "M",
            parent=base["Code"],
            fontName="Courier",
            fontSize=8.5,
            leading=11,
            backColor=PANEL,
            borderPadding=4,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "callout": ParagraphStyle(
            "Co",
            parent=base["Normal"],
            fontSize=9.5,
            leading=12.5,
            textColor=INK,
            backColor=colors.HexColor("#fff8e1"),
            borderPadding=6,
            spaceBefore=4,
            spaceAfter=8,
        ),
    }


def bullets(items: list[str], st) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(i, st["bullet"]), leftIndent=8, value="•") for i in items],
        bulletType="bullet",
        start="•",
        leftIndent=12,
        spaceBefore=2,
        spaceAfter=8,
    )


def _box(d: Drawing, x, y, w, h, text: str, fill=BOX, edge=BOX_EDGE, text_color=INK):
    d.add(Rect(x, y, w, h, fillColor=fill, strokeColor=edge, strokeWidth=1.2, rx=3, ry=3))
    # wrap roughly
    lines = []
    words = text.split()
    cur = ""
    for wword in words:
        trial = (cur + " " + wword).strip()
        if len(trial) > 18:
            if cur:
                lines.append(cur)
            cur = wword
        else:
            cur = trial
    if cur:
        lines.append(cur)
    if not lines:
        lines = [text]
    total_h = len(lines) * 10
    start_y = y + h / 2 + total_h / 2 - 8
    for i, line in enumerate(lines[:4]):
        d.add(
            String(
                x + w / 2,
                start_y - i * 10,
                line,
                fontSize=8,
                fillColor=text_color,
                textAnchor="middle",
                fontName="Helvetica-Bold",
            )
        )


def _arrow(d: Drawing, x1, y1, x2, y2, color=ACCENT2):
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.5))
    # simple arrow head toward (x2,y2)
    import math

    ang = math.atan2(y2 - y1, x2 - x1)
    size = 6
    ax = x2 - size * math.cos(ang - 0.4)
    ay = y2 - size * math.sin(ang - 0.4)
    bx = x2 - size * math.cos(ang + 0.4)
    by = y2 - size * math.sin(ang + 0.4)
    d.add(Polygon([x2, y2, ax, ay, bx, by], fillColor=color, strokeColor=color))


def diagram_system_overview() -> Drawing:
    d = Drawing(480, 200)
    # Camera / Pi / RP2040 / Car / Phone
    _box(d, 20, 120, 90, 50, "CSI Camera", fill=colors.HexColor("#e8f5e9"), edge=OK)
    _box(d, 140, 110, 110, 70, "Raspberry Pi 4 brain + Wi-Fi + dashboard", fill=BOX, edge=BOX_EDGE)
    _box(d, 290, 120, 100, 50, "RP2040 motor brain", fill=colors.HexColor("#fff3e0"), edge=WARN)
    _box(d, 420, 120, 50, 50, "RC car", fill=colors.HexColor("#fce4ec"), edge=BAD)
    _box(d, 150, 20, 100, 45, "Phone / laptop browser", fill=colors.HexColor("#ede7f6"), edge=colors.HexColor("#5e35b1"))
    _box(d, 290, 20, 100, 45, "3× HC-SR04 sonars", fill=colors.HexColor("#e0f7fa"), edge=colors.HexColor("#00838f"))
    _box(d, 20, 20, 90, 45, "LEDs G/Y/R", fill=colors.HexColor("#fffde7"), edge=WARN)

    _arrow(d, 110, 145, 140, 145)
    _arrow(d, 250, 145, 290, 145)
    _arrow(d, 390, 145, 420, 145)
    _arrow(d, 200, 110, 200, 65)
    _arrow(d, 340, 120, 340, 65)
    _arrow(d, 140, 42, 110, 42)
    d.add(String(240, 185, "System overview — who talks to whom", fontSize=9, fillColor=MUTED, textAnchor="middle"))
    return d


def diagram_boot_wifi() -> Drawing:
    d = Drawing(480, 210)
    _box(d, 180, 170, 120, 32, "Pi powers on")
    _box(d, 180, 120, 120, 32, "Wi-Fi chooser")
    _box(d, 20, 60, 120, 40, "Hotspot seen? Connect (priority)", fill=colors.HexColor("#e8f5e9"), edge=OK)
    _box(d, 180, 60, 120, 40, "Else home Wi-Fi (dev)", fill=BOX, edge=BOX_EDGE)
    _box(d, 340, 60, 120, 40, "Else blink RED forever", fill=colors.HexColor("#ffebee"), edge=BAD)
    _box(d, 180, 10, 120, 32, "Start dashboard :8088", fill=colors.HexColor("#e8f5e9"), edge=OK)

    _arrow(d, 240, 170, 240, 152)
    _arrow(d, 240, 120, 240, 100)
    _arrow(d, 180, 80, 140, 80)
    _arrow(d, 300, 80, 340, 80)
    _arrow(d, 80, 60, 80, 26)
    d.add(Line(80, 26, 180, 26, strokeColor=ACCENT2, strokeWidth=1.5))
    _arrow(d, 180, 26, 180, 42)
    _arrow(d, 240, 60, 240, 42)
    d.add(String(240, 200, "Boot workflow — which Wi-Fi?", fontSize=9, fillColor=MUTED, textAnchor="middle"))
    return d


def diagram_detection_pullover() -> Drawing:
    d = Drawing(480, 230)
    y = 190
    steps = [
        (20, "Arm detection (yellow LED)"),
        (140, "Camera + TFLite each N frames"),
        (280, "Count consecutive WRONG"),
        (400, "N reached?"),
    ]
    for x, t in steps:
        _box(d, x, y, 110, 36, t)
    _arrow(d, 130, 208, 140, 208)
    _arrow(d, 250, 208, 280, 208)
    _arrow(d, 390, 208, 400, 208)

    _box(d, 400, 120, 70, 36, "No → keep watching", fill=PANEL, edge=MUTED)
    _box(d, 250, 120, 120, 36, "Yes → PULLOVER side", fill=colors.HexColor("#ffebee"), edge=BAD)
    _box(d, 250, 55, 120, 36, "Creep + steer to wall", fill=colors.HexColor("#fff3e0"), edge=WARN)
    _box(d, 250, 5, 120, 36, "Side in band → DONE", fill=colors.HexColor("#e8f5e9"), edge=OK)

    _arrow(d, 435, 190, 435, 156)
    _arrow(d, 400, 138, 370, 138)
    _arrow(d, 310, 120, 310, 91)
    _arrow(d, 310, 55, 310, 41)
    # loop back hint
    d.add(Line(435, 120, 435, 100, strokeColor=MUTED, strokeWidth=1))
    d.add(Line(435, 100, 195, 100, strokeColor=MUTED, strokeWidth=1))
    _arrow(d, 195, 100, 195, 190)
    d.add(String(240, 220, "Detection → auto pull-over workflow", fontSize=9, fillColor=MUTED, textAnchor="middle"))
    return d


def diagram_dashboard_tabs() -> Drawing:
    d = Drawing(480, 120)
    tabs = [
        (15, "Sonar", "Distances F/L/R"),
        (110, "Pullover", "Manual + params"),
        (205, "Detection", "Arm + preview"),
        (300, "Drive", "Joystick + caps"),
        (395, "Log", "Events"),
    ]
    for x, title, sub in tabs:
        _box(d, x, 45, 85, 50, f"{title}: {sub}")
    _box(d, 15, 5, 465, 28, "Always visible: status strip + Quick actions + STOP / Power off", fill=PANEL, edge=MUTED)
    d.add(String(240, 105, "Dashboard layout (browser on port 8088)", fontSize=9, fillColor=MUTED, textAnchor="middle"))
    return d


def diagram_connect_school() -> Drawing:
    d = Drawing(480, 160)
    _box(d, 20, 100, 100, 40, "1. Phone hotspot ON")
    _box(d, 140, 100, 100, 40, "2. Power the Pi")
    _box(d, 260, 100, 100, 40, "3. Join hotspot on laptop")
    _box(d, 380, 100, 90, 40, "4. Open browser")
    _arrow(d, 120, 120, 140, 120)
    _arrow(d, 240, 120, 260, 120)
    _arrow(d, 360, 120, 380, 120)
    _box(
        d,
        100,
        20,
        280,
        50,
        "URL: http://172.31.42.139:8088/  Green LED = ready",
        fill=colors.HexColor("#e8f5e9"),
        edge=OK,
    )
    _arrow(d, 425, 100, 425, 45)
    d.add(Line(425, 45, 380, 45, strokeColor=ACCENT2, strokeWidth=1.5))
    d.add(String(240, 150, "School / demo connection procedure", fontSize=9, fillColor=MUTED, textAnchor="middle"))
    return d


def diagram_leds() -> Drawing:
    d = Drawing(480, 90)
    _box(d, 40, 25, 120, 45, "GREEN ready UART + UI up", fill=colors.HexColor("#c8e6c9"), edge=OK)
    _box(d, 180, 25, 120, 45, "YELLOW armed detection on", fill=colors.HexColor("#fff9c4"), edge=WARN)
    _box(d, 320, 25, 120, 45, "RED wrong / pullover / no Wi-Fi blink", fill=colors.HexColor("#ffcdd2"), edge=BAD)
    d.add(String(240, 78, "LED meanings (GPIO 21 / 16 / 20)", fontSize=9, fillColor=MUTED, textAnchor="middle"))
    return d


def table(data, col_widths):
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bdbdbd")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
            ]
        )
    )
    return t


def build():
    st = styles()
    story = []

    story.append(Paragraph("Wrong-Way Arrow + Smart Pull-Over Car", st["title"]))
    story.append(
        Paragraph(
            "Student project guide (age ~16) · Raspberry Pi 4 · RP2040 · Flask dashboard · School demo Wi‑Fi",
            st["sub"],
        )
    )

    story.append(Paragraph("1. What is this project?", st["h1"]))
    story.append(
        Paragraph(
            "This project is a small <b>radio-control (RC) car</b> that can think with two computers: "
            "a <b>Raspberry Pi 4</b> (camera, Wi‑Fi, web dashboard, AI) and an <b>RP2040 microcontroller</b> "
            "(motors, steering, ultrasonic sensors). Together they can detect a road arrow that points the "
            "<b>wrong way</b> and gently <b>pull over</b> toward a wall using distance sensors — like a "
            "simplified parking / safety manoeuvre.",
            st["body"],
        )
    )
    story.append(
        Paragraph(
            "<b>Safety first:</b> keep wheels lifted or clear space for first tests. Always know where the "
            "<b>STOP</b> button is. Never aim sensors or the car at people’s faces.",
            st["callout"],
        )
    )

    story.append(Paragraph("2. Big picture — the parts", st["h1"]))
    story.append(diagram_system_overview())
    story.append(Paragraph("Figure 1. Main components and how they connect.", st["caption"]))

    story.append(Paragraph("2.1 Hardware components", st["h2"]))
    story.append(
        table(
            [
                [Paragraph("<b>Part</b>", st["bullet"]), Paragraph("<b>What it does (simple words)</b>", st["bullet"])],
                ["Raspberry Pi 4", "The ‘laptop brain’: Wi‑Fi, camera AI, web page for control."],
                ["CSI camera", "Looks at arrows on the road / paper signs."],
                ["RP2040 board", "The ‘motor brain’: drives ESC + steering servo, reads sonars."],
                ["HC-SR04 ×3", "Ultrasonic ‘tape measures’: front, left, right distances in cm."],
                ["Dual 10 kΩ dividers", "Protect Pi/RP2040 inputs from 5 V echo pulses (drop to ~3.3 V)."],
                ["LEDs (G/Y/R)", "Status lights so you can see ready / armed / alert without a screen."],
                ["RC transmitter", "Must be on with a live receiver; Pi can take over without stick centering."],
            ],
            [3.2 * cm, 13.5 * cm],
        )
    )
    story.append(Spacer(1, 6))

    story.append(Paragraph("2.2 Software components", st["h2"]))
    story.append(
        bullets(
            [
                "<b>BT_project_v5 firmware</b> on the RP2040 — UART commands: DRIVE, PULLOVER, SONAR, CAP, STOP…",
                "<b>Flask RC test console</b> (<font face='Courier'>sonar_debug_server.py</font>) on port <b>8088</b> — the dashboard.",
                "<b>Teachable Machine TFLite model</b> — classes mapped to correct / wrong / none (quantized for speed).",
                "<b>wifi-chooser</b> on boot — prefers school hotspot, else home Wi‑Fi; blinks red if offline.",
                "<b>systemd</b> services — start automatically after power-on.",
            ],
            st,
        )
    )

    story.append(Paragraph("3. How the brains talk (UART)", st["h1"]))
    story.append(
        Paragraph(
            "The Pi and RP2040 speak a simple text language over a serial wire (UART) at <b>115200 baud</b>. "
            "Each command is one line ending with Enter. Examples: <font face='Courier'>PULLOVER,RIGHT</font>, "
            "<font face='Courier'>SONAR,ON</font>, <font face='Courier'>STATUS?</font>. "
            "The dashboard turns button clicks into these messages so you do not need a terminal for demos.",
            st["body"],
        )
    )
    story.append(
        Paragraph(
            "Pi GPIO14 TX → RP2040 GP13 RX · RP2040 GP12 TX → Pi GPIO15 RX · common GND",
            st["mono"],
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("4. Connecting for a school demo (hotspot)", st["h1"]))
    story.append(
        Paragraph(
            "At school you usually cannot use the home Wi‑Fi. We use a <b>phone hotspot</b>. "
            "The Pi already knows SSID <b>Galaxy A20eFF3F</b> and prefers it on boot. "
            "Its fixed hotspot address is <b>172.31.42.139</b>.",
            st["body"],
        )
    )
    story.append(diagram_connect_school())
    story.append(Paragraph("Figure 2. Connection steps for a classroom demo.", st["caption"]))

    story.append(Paragraph("Step-by-step checklist", st["h2"]))
    story.append(
        bullets(
            [
                "Turn on the phone hotspot <b>before</b> powering the Pi.",
                "Power the Pi (USB‑C). Wait ~30–60 s. Green LED should light when the console + UART are ready.",
                "On the presenter laptop/phone: join the <b>same</b> hotspot.",
                "Open a browser to <font face='Courier'>http://172.31.42.139:8088/</font>",
                "If the page does not load: check red LED (blinking = no Wi‑Fi). Confirm hotspot password and that the Pi appears in the phone’s client list.",
                "When finished: use <b>Power off Pi</b> in the header (confirm dialog) — safer than yanking power.",
            ],
            st,
        )
    )

    story.append(Paragraph("Home / development network", st["h2"]))
    story.append(
        Paragraph(
            "At home the Pi may use Wi‑Fi <font face='Courier'>eir63498627_2GEXT</font> / "
            "<font face='Courier'>5GEXT</font> with address <b>192.168.1.152</b>. "
            "Dashboard: <font face='Courier'>http://192.168.1.152:8088/</font>. "
            "Boot chooser: hotspot first if visible, otherwise home.",
            st["body"],
        )
    )

    story.append(Paragraph("5. LED meanings", st["h1"]))
    story.append(diagram_leds())
    story.append(Paragraph("Figure 3. Status LEDs on the Pi.", st["caption"]))
    story.append(
        bullets(
            [
                "<b>Green (GPIO21)</b> — system ready: Flask dashboard up and UART to RP2040 healthy.",
                "<b>Yellow (GPIO16)</b> — detection armed: camera + AI loop running.",
                "<b>Red (GPIO20)</b> — wrong-way streak / pull-over active; or <b>blinking</b> at boot if no Wi‑Fi.",
            ],
            st,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("6. The web dashboard (port 8088)", st["h1"]))
    story.append(
        Paragraph(
            "The dashboard is a website served by the Pi. Anyone on the same Wi‑Fi can open it. "
            "It is split into <b>tabs</b> so it stays tidy. A <b>status strip</b> and <b>Quick actions</b> "
            "stay visible at the top.",
            st["body"],
        )
    )
    story.append(diagram_dashboard_tabs())
    story.append(Paragraph("Figure 4. Dashboard tabs.", st["caption"]))

    story.append(Paragraph("6.1 Header buttons (always available)", st["h2"]))
    story.append(
        table(
            [
                ["Button", "Meaning"],
                ["Refresh STATUS", "Ask the RP2040 for a fresh status line."],
                ["STOP", "Emergency stop — latches until RESET. Use if anything unexpected happens."],
                ["RESET", "Clear a latched STOP when it is safe."],
                ["MANUAL", "Return motor control toward normal RC / manual mode."],
                ["Power off Pi", "Shuts down the Raspberry Pi cleanly (asks for confirmation)."],
            ],
            [4 * cm, 12.7 * cm],
        )
    )
    story.append(Spacer(1, 6))

    story.append(Paragraph("6.2 Quick actions (right of status)", st["h2"]))
    story.append(
        bullets(
            [
                "<b>PULLOVER LEFT / RIGHT</b> — start the ultrasonic manoeuvre immediately.",
                "<b>ABORT</b> — cancel an active pull-over.",
                "<b>Arm / Disarm detection</b> — start or stop the camera AI loop.",
            ],
            st,
        )
    )

    story.append(Paragraph("6.3 Tab: Sonar", st["h2"]))
    story.append(
        Paragraph(
            "Shows live distances from Front / Left / Right HC-SR04 sensors (cm). "
            "Use <b>Sonar ON</b> for continuous readings without driving. "
            "Useful to check wiring and reflections before a pull-over.",
            st["body"],
        )
    )

    story.append(Paragraph("6.4 Tab: Pullover", st["h2"]))
    story.append(
        Paragraph(
            "Manual pull-over controls plus <b>tunable parameters</b> (side target distance, band, front stop, "
            "creep speed, steer strength, stable hold time, timeout). Defaults are stored on the RP2040 and can "
            "be changed from the UI without rewriting firmware every time.",
            st["body"],
        )
    )
    story.append(
        table(
            [
                ["Parameter", "Default idea", "Student meaning"],
                ["Side target", "10 cm", "How close to the wall is ‘parked’."],
                ["Band", "±2 cm", "Acceptable window around the target."],
                ["Front stop", "25 cm", "Abort if something is too close ahead."],
                ["Creep", "~10%", "Slow forward throttle during the manoeuvre."],
                ["Steer max", "~28%", "How hard it steers toward/away from the wall."],
                ["Stable", "400 ms", "How long it must stay in-band before DONE."],
                ["Timeout", "15 s", "Give up if it never settles."],
            ],
            [3.2 * cm, 3.2 * cm, 10.3 * cm],
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("6.5 Tab: Detection", st["h2"]))
    story.append(
        Paragraph(
            "Arms the camera model. When enabled, an <b>MJPEG preview</b> can appear (only while armed — "
            "keeps the Pi cooler). You can set how many consecutive <b>wrong</b> frames are required before "
            "an automatic pull-over, confidence threshold, cooldown, and which side to pull over.",
            st["body"],
        )
    )
    story.append(
        Paragraph(
            "Model labels on this build: <font face='Courier'>frwrd</font> → correct, "
            "<font face='Courier'>rvrs</font> → wrong, <font face='Courier'>Contrl</font> → none.",
            st["body"],
        )
    )

    story.append(Paragraph("6.6 Tab: Drive", st["h2"]))
    story.append(
        Paragraph(
            "Virtual joystick for Wi‑Fi testing. Turn <b>Pi control ON</b> first (AUTO mode + heartbeat). "
            "Throttle caps default to <b>25%</b> so first tests are gentle; you can raise them. "
            "Release the stick to coast to a stop.",
            st["body"],
        )
    )

    story.append(Paragraph("6.7 Tab: Log", st["h2"]))
    story.append(
        Paragraph(
            "Scrolling list of events from the RP2040 and Pi (<font face='Courier'>OK,PULLOVER</font>, "
            "<font face='Courier'>DONE,PULLOVER</font>, errors, detection triggers). Great for debugging demos.",
            st["body"],
        )
    )

    story.append(Paragraph("7. Detection → pull-over workflow", st["h1"]))
    story.append(diagram_detection_pullover())
    story.append(Paragraph("Figure 5. From ‘wrong arrow’ to parked beside the wall.", st["caption"]))
    story.append(
        bullets(
            [
                "Arm detection → yellow LED on; camera frames are classified.",
                "Each accepted <b>wrong</b> increases a streak counter (configurable N, default 5).",
                "<b>correct</b> or <b>none</b> can reset the streak (configurable).",
                "When streak ≥ N and cooldown allows → send <font face='Courier'>PULLOVER,LEFT|RIGHT</font>.",
                "RP2040 creeps forward, steers using the side sonar until distance is in the target band, then finishes.",
                "Front sonar too close → <font face='Courier'>ERR,PULLOVER,FRONT</font> emergency stop path.",
            ],
            st,
        )
    )

    story.append(Paragraph("8. Boot Wi‑Fi workflow", st["h1"]))
    story.append(diagram_boot_wifi())
    story.append(Paragraph("Figure 6. What happens when you power the Pi.", st["caption"]))

    story.append(PageBreak())
    story.append(Paragraph("9. Sonar wiring (why dividers matter)", st["h1"]))
    story.append(
        Paragraph(
            "HC-SR04 modules run at <b>5 V</b>. Their ECHO pin can output 5 V pulses. The RP2040 GPIO is "
            "<b>3.3 V</b> only. We use a <b>dual 10 kΩ resistor divider</b> on each ECHO line so the "
            "microcontroller sees a safe voltage. TRIG can be driven directly from 3.3 V GPIO.",
            st["body"],
        )
    )
    story.append(
        table(
            [
                ["Sensor", "TRIG", "ECHO (via divider)"],
                ["Front", "GP14", "GP15"],
                ["Left", "GP8", "GP9"],
                ["Right", "GP16", "GP17"],
            ],
            [4 * cm, 5 * cm, 7.7 * cm],
        )
    )
    story.append(Spacer(1, 8))

    story.append(Paragraph("10. Suggested classroom demo script", st["h1"]))
    story.append(
        bullets(
            [
                "Show the car + Pi + sensors (30 s).",
                "Open the dashboard on the projector (hotspot URL).",
                "Sonar tab: wave a hand — distances change live.",
                "Detection tab: show preview; hold a ‘wrong’ arrow until red / pull-over triggers (wheels safe).",
                "Explain LEDs and STOP button.",
                "Power off cleanly from the header.",
            ],
            st,
        )
    )

    story.append(Paragraph("11. Troubleshooting for students", st["h1"]))
    story.append(
        table(
            [
                ["Symptom", "Try this"],
                ["Red LED blinking, no page", "Hotspot on? Same SSID? Wait 1 min after boot; check phone client list."],
                ["Page loads, green off", "UART cable / RP2040 power; Refresh STATUS; check firmware."],
                ["Sonar stuck at — or −1", "Wiring, 5 V supply, divider, sensor facing a flat surface."],
                ["Detection won’t arm", "Camera ribbon seated; model files present; read Log / error strip."],
                ["Pull-over hits wall", "Increase side target; check sensor angle; lower creep; longer stable time."],
                ["Joystick does nothing", "Pi control ON; caps &gt; 0; transmitter on / rcOK = 1."],
            ],
            [5.5 * cm, 11.2 * cm],
        )
    )

    story.append(Spacer(1, 10))
    story.append(Paragraph("12. Glossary", st["h1"]))
    story.append(
        bullets(
            [
                "<b>UART</b> — serial text link between Pi and RP2040.",
                "<b>GPIO</b> — general-purpose input/output pin on a microcontroller / Pi.",
                "<b>TFLite</b> — tiny neural-network format that runs on the Pi.",
                "<b>DHCP / static IP</b> — automatic vs fixed address on Wi‑Fi.",
                "<b>Hotspot</b> — phone shares its mobile data / local Wi‑Fi for the demo.",
                "<b>Pull-over</b> — slow steer-and-creep manoeuvre using side distance.",
            ],
            st,
        )
    )

    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "Project files live in <font face='Courier'>KevinsProject</font> on the Pi "
            "(<font face='Courier'>/home/pi/KevinsProject</font>). "
            "This guide matches the Flask console on port 8088, RP2040 firmware BT_project_v5, "
            "and boot service <font face='Courier'>wifi-chooser</font>.",
            st["caption"],
        )
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title="Student Project Guide — Wrong-Way Arrow + Pull-Over Car",
        author="KevinsProject",
    )
    doc.build(story)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
