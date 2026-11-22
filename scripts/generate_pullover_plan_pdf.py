#!/usr/bin/env python3
"""Generate PDF: RP2040 pull-over plan + manoeuvre description."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).resolve().parents[1] / "docs" / "RP2040_PullOver_Plan.pdf"


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleCustom",
            parent=base["Title"],
            fontSize=18,
            spaceAfter=6,
            textColor=colors.HexColor("#1a1a1a"),
        ),
        "sub": ParagraphStyle(
            "Sub",
            parent=base["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#555555"),
            alignment=TA_CENTER,
            spaceAfter=16,
        ),
        "h1": ParagraphStyle(
            "H1c",
            parent=base["Heading1"],
            fontSize=13,
            spaceBefore=14,
            spaceAfter=6,
            textColor=colors.HexColor("#0d47a1"),
        ),
        "h2": ParagraphStyle(
            "H2c",
            parent=base["Heading2"],
            fontSize=11,
            spaceBefore=10,
            spaceAfter=4,
            textColor=colors.HexColor("#1565c0"),
        ),
        "body": ParagraphStyle(
            "Bodyc",
            parent=base["Normal"],
            fontSize=9.5,
            leading=13,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "Bulletc",
            parent=base["Normal"],
            fontSize=9.5,
            leading=12,
            leftIndent=0,
        ),
        "mono": ParagraphStyle(
            "Monoc",
            parent=base["Code"],
            fontSize=8.5,
            leading=11,
            backColor=colors.HexColor("#f5f5f5"),
            spaceBefore=2,
            spaceAfter=2,
        ),
        "note": ParagraphStyle(
            "Notec",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#444444"),
            spaceAfter=4,
        ),
    }


def bullets(items, st):
    return ListFlowable(
        [ListItem(Paragraph(i, st["bullet"]), leftIndent=12, bulletColor=colors.HexColor("#1565c0")) for i in items],
        bulletType="bullet",
        start="•",
        leftIndent=15,
        spaceAfter=8,
    )


def table(data, col_widths):
    t = Table(data, colWidths=col_widths)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1565c0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#eef5ff")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#90caf9")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        title="RP2040 Pull-Over Plan",
        author="KevinsProject",
    )
    s = styles()
    story = []

    story.append(Paragraph("RP2040 Pull-Over with HC-SR04", s["title"]))
    story.append(
        Paragraph(
            "Engineering plan &amp; manoeuvre description · KevinsProject · 22 November 2026",
            s["sub"],
        )
    )

    story.append(Paragraph("1. Overview", s["h1"]))
    story.append(
        Paragraph(
            "The Raspberry Pi requests a roadside pull-over with a single UART command. "
            "The <b>RP2040 runs the full closed-loop procedure</b> using ultrasonic sensors. "
            "Sonar is enabled only during the manoeuvre so normal RC / AUTO control timing is unaffected. "
            "The Pi can abort at any time; a front obstacle triggers an emergency stop.",
            s["body"],
        )
    )

    story.append(Paragraph("2. Locked design decisions", s["h1"]))
    story.append(
        bullets(
            [
                "<b>Closed loop on RP2040</b> after one Pi command — Pi does not step steer/throttle.",
                "<b>Sonar ON only during pull-over</b>; OFF otherwise.",
                "<b>Firmware base:</b> extend BT_project_v4 into new sketch <b>BT_project_v5</b> (keep v4 as backup).",
                "<b>Abort:</b> STOP, ESTOP, and PULLOVER,ABORT always handled during the manoeuvre.",
                "<b>Front obstacle:</b> range below threshold → immediate neutral + latched emergency stop.",
            ],
            s,
        )
    )

    story.append(Paragraph("3. Pull-over manoeuvre (behaviour)", s["h1"]))
    story.append(
        Paragraph(
            "Pi sends <b>PULLOVER,LEFT</b> or <b>PULLOVER,RIGHT</b>. The RP2040 enables the "
            "<b>front</b> HC-SR04 plus the <b>chosen side</b> sensor only, creeps forward, steers gently "
            "toward the wall, holds about <b>10 cm</b> from the wall, then stops and returns control.",
            s["body"],
        )
    )

    story.append(Paragraph("3.1 Sequence", s["h2"]))
    story.append(
        bullets(
            [
                "<b>Enter:</b> require armed + receiver OK; cancel any active drive; enable front + active side sonar only.",
                "<b>Approach:</b> low forward creep; gentle steer toward the wall while side distance is outside the target band. "
                "If front &lt; stop distance → emergency stop.",
                "<b>Align:</b> when side distance is in the ~8–12 cm band, straighten / micro-adjust; stay stable for ~300–500 ms.",
                "<b>Finish:</b> throttle and steer neutral; sonar OFF; send DONE,PULLOVER; return to MANUAL (disarmed — TX must re-arm).",
            ],
            s,
        )
    )

    story.append(Paragraph("3.2 Abort &amp; safety during manoeuvre", s["h2"]))
    story.append(
        bullets(
            [
                "Front obstacle → neutral + stop latch + sonar OFF + ERR,PULLOVER,FRONT.",
                "Pi PULLOVER,ABORT / STOP / ESTOP → cancel, neutral, sonar OFF.",
                "Overall timeout (e.g. 15 s) → abort to neutral + error.",
            ],
            s,
        )
    )

    story.append(Paragraph("3.3 Tunable constants (initial)", s["h2"]))
    story.append(
        table(
            [
                ["Parameter", "Initial value"],
                ["Side target", "10 cm (band ~8–12 cm)"],
                ["Front emergency stop", "25 cm"],
                ["Creep throttle", "~10–15% forward cap"],
                ["Gentle steer limit", "max ~25–30%"],
                ["Manoeuvre timeout", "15 seconds"],
            ],
            [7 * cm, 9 * cm],
        )
    )
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("3.4 Flow summary", s["h2"]))
    story.append(
        Paragraph(
            "Pi command → Enter (sonar ON) → Approach (creep + steer) → "
            "Front clear? → Side near 10 cm? → Align/hold → Finish (sonar OFF, DONE) · "
            "Any abort/ESTOP path → Neutral + sonar OFF.",
            s["body"],
        )
    )

    story.append(Paragraph("4. Wiring (proposed — not yet connected)", s["h1"]))
    story.append(
        Paragraph(
            "Already used on the RP2040: GP2/3 (RC in), GP4/5 (servo/ESC), GP12/13 (UART to Pi). "
            "Assigned free pins for three HC-SR04 modules:",
            s["body"],
        )
    )
    story.append(
        table(
            [
                ["Sensor", "TRIG", "ECHO (via divider)"],
                ["Front", "GP6", "GP7"],
                ["Left", "GP8", "GP9"],
                ["Right", "GP10", "GP11"],
            ],
            [5 * cm, 5 * cm, 6 * cm],
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(
        bullets(
            [
                "HC-SR04 VCC = <b>5 V</b>; common GND with RP2040.",
                "TRIG driven at 3.3 V from RP2040 (sensor accepts this).",
                "ECHO is 5 V → use <b>10 kΩ series + 16 kΩ to GND</b> into each ECHO GPIO (same idea as RC inputs). "
                "Never feed 5 V into RP2040 pins.",
            ],
            s,
        )
    )

    story.append(Paragraph("5. UART protocol", s["h1"]))
    story.append(Paragraph("Pi → RP2040", s["h2"]))
    story.append(
        bullets(
            [
                "<font face='Courier'>PULLOVER,LEFT</font> — front + left sonar; pull left",
                "<font face='Courier'>PULLOVER,RIGHT</font> — front + right sonar; pull right",
                "<font face='Courier'>PULLOVER,ABORT</font> — cancel; sonar off; neutral",
                "<font face='Courier'>STOP</font> / <font face='Courier'>ESTOP</font> — hard stop + latch; sonar off",
            ],
            s,
        )
    )
    story.append(Paragraph("RP2040 → Pi", s["h2"]))
    story.append(
        bullets(
            [
                "<font face='Courier'>OK,PULLOVER,LEFT</font> / <font face='Courier'>OK,PULLOVER,RIGHT</font>",
                "<font face='Courier'>DONE,PULLOVER</font> — parked successfully",
                "<font face='Courier'>ERR,PULLOVER,...</font> — reject / fault",
                "<font face='Courier'>ERR,PULLOVER,FRONT</font> — front obstacle stop",
                "<font face='Courier'>ERR,PULLOVER,ABORT</font> — aborted by Pi",
                "<font face='Courier'>RANGE,frontCm,sideCm</font> — optional ~200 ms telemetry while active",
            ],
            s,
        )
    )

    story.append(Paragraph("6. Implementation work", s["h1"]))
    story.append(
        bullets(
            [
                "<b>Firmware BT_project_v5:</b> non-blocking HC-SR04 driver, enable/disable, PULLOVER state machine, abort/front ESTOP, RANGE lines.",
                "<b>Docs:</b> wiring map for GP6–11 with echo dividers.",
                "<b>Pi (KevinsProject):</b> extend rp2040_uart.py; add test_pullover.py; update COMMANDS.md.",
            ],
            s,
        )
    )

    story.append(Paragraph("7. Out of scope (this drop)", s["h1"]))
    story.append(
        bullets(
            [
                "Flashing the RP2040 (done in Arduino IDE by the team).",
                "Auto-calling pull-over from TFLite arrow detection (later).",
                "Physical soldering (wiring is documented only until hardware is fitted).",
            ],
            s,
        )
    )

    story.append(Paragraph("8. Validation checklist", s["h1"]))
    story.append(
        bullets(
            [
                "MANUAL/AUTO with sonar disabled: control feel and heartbeat unchanged.",
                "PULLOVER,RIGHT near a wall: front+right only; creeps; settles ~10 cm; DONE,PULLOVER.",
                "Block front mid-manoeuvre → immediate stop + ERR,PULLOVER,FRONT.",
                "Pi PULLOVER,ABORT or STOP mid-manoeuvre → sonar off, neutral.",
                "Verify all three ECHO voltage dividers before first power-up.",
            ],
            s,
        )
    )

    story.append(Spacer(1, 8 * mm))
    story.append(
        Paragraph(
            "Document generated from the RP2040 Pull-Over Sonar plan. "
            "Status: design proposed — firmware and hardware not yet implemented.",
            s["note"],
        )
    )

    doc.build(story)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
