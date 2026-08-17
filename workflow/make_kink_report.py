#!/usr/bin/env python3
"""Create the Korean 2022EE expected-limit kink diagnostic report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


FONT_PATH = Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf")
FONT_NAME = "AppleGothic"
ACCENT = colors.HexColor("#315B7D")
ACCENT_LIGHT = colors.HexColor("#EAF1F6")
RED = colors.HexColor("#A62A2A")
RED_LIGHT = colors.HexColor("#F8EAEA")
INK = colors.HexColor("#1C252C")
MUTED = colors.HexColor("#5D6870")
GRID = colors.HexColor("#CBD4DA")
LIGHT = colors.HexColor("#F5F7F8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/2022EE"),
        help="2022EE workflow output directory",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=Path("output/pdf/2022EE_limit_kink_analysis_ko.pdf"),
        help="Final PDF path",
    )
    return parser.parse_args()


def register_fonts() -> None:
    if not FONT_PATH.is_file():
        raise FileNotFoundError(f"Missing Korean font: {FONT_PATH}")
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "KoreanTitle",
            parent=base["Title"],
            fontName=FONT_NAME,
            fontSize=22,
            leading=29,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=4 * mm,
            wordWrap="CJK",
        ),
        "subtitle": ParagraphStyle(
            "KoreanSubtitle",
            parent=base["Normal"],
            fontName=FONT_NAME,
            fontSize=10.5,
            leading=16,
            textColor=MUTED,
            spaceAfter=5 * mm,
            wordWrap="CJK",
        ),
        "h1": ParagraphStyle(
            "KoreanH1",
            parent=base["Heading1"],
            fontName=FONT_NAME,
            fontSize=15,
            leading=21,
            textColor=ACCENT,
            spaceBefore=2 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
            wordWrap="CJK",
        ),
        "h2": ParagraphStyle(
            "KoreanH2",
            parent=base["Heading2"],
            fontName=FONT_NAME,
            fontSize=11.5,
            leading=16,
            textColor=INK,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
            wordWrap="CJK",
        ),
        "body": ParagraphStyle(
            "KoreanBody",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=9.3,
            leading=15,
            textColor=INK,
            spaceAfter=2.2 * mm,
            wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "KoreanSmall",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=7.7,
            leading=11,
            textColor=MUTED,
            wordWrap="CJK",
        ),
        "table": ParagraphStyle(
            "KoreanTable",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=7.4,
            leading=10,
            textColor=INK,
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "table_left": ParagraphStyle(
            "KoreanTableLeft",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=7.4,
            leading=10,
            textColor=INK,
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "callout": ParagraphStyle(
            "KoreanCallout",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=10,
            leading=16,
            textColor=INK,
            wordWrap="CJK",
        ),
        "caption": ParagraphStyle(
            "KoreanCaption",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=7.7,
            leading=11,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceBefore=1.5 * mm,
            wordWrap="CJK",
        ),
        "equation": ParagraphStyle(
            "Equation",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=10,
            leading=15,
            textColor=INK,
            alignment=TA_CENTER,
            spaceBefore=2 * mm,
            spaceAfter=3 * mm,
        ),
    }


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def styled_table(
    data: list[list[Any]],
    *,
    widths: list[float],
    header_rows: int = 1,
    align: str = "CENTER",
    font_size: float = 7.4,
) -> Table:
    table = Table(data, colWidths=widths, repeatRows=header_rows, hAlign=align)
    commands: list[tuple[Any, ...]] = [
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("LEADING", (0, 0), (-1, -1), font_size + 3),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for row in range(header_rows, len(data)):
        if (row - header_rows) % 2:
            commands.append(("BACKGROUND", (0, row), (-1, row), LIGHT))
    table.setStyle(TableStyle(commands))
    return table


def row_by_label(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    return next(row for row in rows if row["label"] == label)


def header_footer(canvas: Any, document: Any) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(GRID)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, height - 13 * mm, width - 18 * mm, height - 13 * mm)
    canvas.setFont(FONT_NAME, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, height - 10 * mm, "CMS Work in progress - 2022EE")
    canvas.drawRightString(
        width - 18 * mm,
        height - 10 * mm,
        "26.68 fb^-1 (13.6 TeV)",
    )
    canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
    canvas.drawString(18 * mm, 9 * mm, "Expected limit kink 원인 분석")
    canvas.drawRightString(width - 18 * mm, 9 * mm, f"{document.page}")
    canvas.restoreState()


def build_report(output: Path, pdf_path: Path) -> None:
    register_fonts()
    styles = make_styles()
    manifest = json.loads((output / "manifest.json").read_text())
    limits = json.loads((output / "limits" / "limits.json").read_text())
    validation = json.loads(
        (output / "validation" / "validation_report.json").read_text()
    )
    limit_plot = output / "interpolation" / "limit_interpolation.png"
    if not limit_plot.is_file():
        raise FileNotFoundError(limit_plot)

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=17 * mm,
        title="2022EE 모노탑 expected limit kink 원인 분석 보고서",
        author="Codex",
        subject="2022EE blinded expected limit interpolation diagnostic",
    )

    story: list[Any] = []
    story.append(p("2022EE 모노탑 expected limit<br/>kink 원인 분석 보고서", styles["title"]))
    story.append(
        p(
            "37개 simulated mass point에서 계산된 blinded expected limit의 "
            "보간 등고선이 꺾이는 원인을 입력 수율, Delaunay triangle 및 "
            "Combine 진단 결과로 분리해 검증하였다.",
            styles["subtitle"],
        )
    )

    metadata = [
        [
            p("항목", styles["table"]),
            p("내용", styles["table"]),
            p("항목", styles["table"]),
            p("내용", styles["table"]),
        ],
        [
            p("데이터 시대", styles["table"]),
            p(str(manifest["era"]), styles["table"]),
            p("적분 luminosity", styles["table"]),
            p(f"{float(manifest['luminosity_fb']):.2f} fb<super>-1</super>", styles["table"]),
        ],
        [
            p("limit 종류", styles["table"]),
            p("Blinded expected only", styles["table"]),
            p("신호 point", styles["table"]),
            p(str(len(limits)), styles["table"]),
        ],
        [
            p("보간 변수", styles["table"]),
            p("log<sub>10</sub>(r<sub>95</sub>)", styles["table"]),
            p("검증 상태", styles["table"]),
            p(str(validation["status"]), styles["table"]),
        ],
        [
            p("보고서 기준일", styles["table"]),
            p("2026-07-31", styles["table"]),
            p("입력 SHA-256", styles["table"]),
            p(str(manifest["input_sha256"])[:16] + "...", styles["table"]),
        ],
    ]
    story.append(styled_table(metadata, widths=[25 * mm, 58 * mm, 29 * mm, 62 * mm]))
    story.append(Spacer(1, 4 * mm))

    conclusion = Table(
        [
            [
                p(
                    "<b>결론</b><br/>kink는 Combine fit 실패가 아니다. "
                    "희소하고 불규칙한 mass grid 전체에 단일 Delaunay "
                    "triangulation을 적용하면서 on-shell과 off-shell point가 "
                    "같은 triangle에 연결되고, piecewise-linear gradient가 "
                    "triangle 경계에서 불연속이 되어 발생한다. "
                    "특히 (1750, 700) point의 expected r=0.99244가 contour를 "
                    "해당 point 근처에 고정해 뾰족한 apex를 만든다.",
                    styles["callout"],
                )
            ]
        ],
        colWidths=[174 * mm],
    )
    conclusion.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), RED_LIGHT),
                ("BOX", (0, 0), (-1, -1), 1.0, RED),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(conclusion)
    story.append(Spacer(1, 4 * mm))

    plot = Image(str(limit_plot))
    plot.drawWidth = 158 * mm
    plot.drawHeight = plot.drawWidth * 10.0 / 12.0
    plot.hAlign = "CENTER"
    story.append(plot)
    story.append(
        p(
            "그림 1. 2022EE blinded expected 95% CL limit. 검은 실선과 적색 "
            "1 sigma 경계의 각진 부분은 아래에서 분석한 triangulation 구조를 따른다.",
            styles["caption"],
        )
    )

    story.append(PageBreak())
    story.append(p("1. 분석 방법과 판정 기준", styles["h1"]))
    story.append(
        p(
            "현재 workflow는 각 simulated point의 expected limit를 읽어 "
            "z<sub>i</sub>=log<sub>10</sub>(r<sub>i</sub>)로 변환한 뒤, "
            "SciPy LinearNDInterpolator를 사용한다. 이 방법은 내부적으로 "
            "Delaunay triangulation을 만들고 각 triangle 안에서 z를 평면으로 "
            "보간한다.",
            styles["body"],
        )
    )
    story.append(
        p(
            "z(m<sub>V</sub>, m<sub>chi</sub>) = "
            "a m<sub>V</sub> + b m<sub>chi</sub> + c &nbsp;&nbsp; "
            "(각 triangle 내부)",
            styles["equation"],
        )
    )
    story.append(
        p(
            "값 자체는 공유 edge에서 연속이지만 계수 (a,b), 즉 gradient는 "
            "인접 triangle 사이에서 같을 필요가 없다. 따라서 r=1 contour는 "
            "triangle 경계에서 일반적으로 미분 연속이 아니며 kink가 허용된다. "
            "현재 구현은 on-shell과 off-shell을 별도 domain으로 분리하지 않는다.",
            styles["body"],
        )
    )

    counts = [
        [p("기하학적 항목", styles["table"]), p("개수", styles["table"]), p("해석", styles["table"])],
        [
            p("전체 Delaunay triangle", styles["table_left"]),
            p("64", styles["table"]),
            p("37개 입력 point에서 생성", styles["table_left"]),
        ],
        [
            p("m<sub>V</sub>=2m<sub>chi</sub> 횡단 triangle", styles["table_left"]),
            p("28", styles["table"]),
            p("on/off-shell point가 동일 triangle에 연결", styles["table_left"]),
        ],
        [
            p("median r=1 contour 횡단 triangle", styles["table_left"]),
            p("23", styles["table"]),
            p("검은 expected contour 구성", styles["table_left"]),
        ],
        [
            p("shell 경계와 r=1을 모두 횡단", styles["table_left"]),
            p("11", styles["table"]),
            p("주요 kink에 직접 관여", styles["table_left"]),
        ],
    ]
    story.append(
        styled_table(counts, widths=[60 * mm, 22 * mm, 92 * mm])
    )

    story.append(p("2. 검은 expected contour의 정확한 kink 위치", styles["h1"]))
    kink_rows = [
        [
            p("위치 [GeV]", styles["table"]),
            p("연결 segment", styles["table"]),
            p("직접 원인", styles["table"]),
        ],
        [
            p("(1497, 478)", styles["table"]),
            p("(1264,590) -> (1497,478)<br/>(1497,478) -> (1747,701)", styles["table"]),
            p(
                "공유 edge 양쪽 triangle의 세 번째 vertex가 각각 r&gt;1과 r&lt;1. "
                "gradient 방향이 edge에서 급변.",
                styles["table_left"],
            ),
        ],
        [
            p("(1747, 701)", styles["table"]),
            p("여러 짧은 segment가 (1750,700) 주변에서 결합", styles["table"]),
            p(
                "(1750,700)의 r=0.99244가 1에 매우 가까우며 주변 vertex는 모두 r&gt;1. "
                "contour가 해당 point에 고정되어 apex 형성.",
                styles["table_left"],
            ),
        ],
        [
            p("(1832, 264)", styles["table"]),
            p("(1755,696) -> (1832,264) -> (1837,150)", styles["table"]),
            p(
                "서로 다른 triangle의 선형 gradient와 저질량 convex-hull edge가 연결.",
                styles["table_left"],
            ),
        ],
    ]
    story.append(styled_table(kink_rows, widths=[29 * mm, 60 * mm, 85 * mm]))

    story.append(Spacer(1, 3 * mm))
    story.append(
        p(
            "<b>판정:</b> 25 GeV plotting grid를 거치기 전, exact triangle의 "
            "r=1 교차 segment 자체가 같은 위치에서 이미 꺾인다. 따라서 grid "
            "해상도는 계단 모양을 조금 추가할 뿐 근본 원인이 아니다.",
            styles["body"],
        )
    )

    story.append(PageBreak())
    story.append(p("3. kink 주변 입력 point와 signal acceptance", styles["h1"]))
    labels = [
        "mphi995_mchi500",
        "mphi1000_mchi150",
        "mphi1245_mchi625",
        "mphi1250_mchi150",
        "mphi1495_mchi750",
        "mphi1500_mchi150",
        "mphi1700_mchi800",
        "mphi1750_mchi150",
        "mphi1750_mchi700",
        "mphi1995_mchi1000",
        "mphi2000_mchi150",
        "mphi2000_mchi500",
    ]
    point_table: list[list[Any]] = [
        [
            p("(m<sub>V</sub>, m<sub>chi</sub>)", styles["table"]),
            p("영역", styles["table"]),
            p("-1 sigma", styles["table"]),
            p("Median", styles["table"]),
            p("+1 sigma", styles["table"]),
            p("SR signal yield", styles["table"]),
        ]
    ]
    for label in labels:
        row = row_by_label(limits, label)
        delta = int(row["mphi"]) - 2 * int(row["mchi"])
        shell = "on-shell" if delta > 0 else ("boundary" if delta == 0 else "off-shell")
        point_table.append(
            [
                p(f"({int(row['mphi'])}, {int(row['mchi'])})", styles["table"]),
                p(shell, styles["table"]),
                p(f"{float(row['expected_minus1']):.5g}", styles["table"]),
                p(f"{float(row['expected']):.5g}", styles["table"]),
                p(f"{float(row['expected_plus1']):.5g}", styles["table"]),
                p(f"{float(row['sr_signal_yield']):.3f}", styles["table"]),
            ]
        )
    story.append(
        styled_table(
            point_table,
            widths=[34 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm, 40 * mm],
            font_size=7.0,
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(
        p(
            "거의 동일한 mediator mass에서도 shell 위치에 따라 signal yield와 "
            "limit가 크게 다르다. 예를 들어 (1495,750)은 off-shell로 SR yield가 "
            "61.823이고 median r=2.0445인 반면, (1500,150)은 on-shell로 yield가 "
            "301.027이고 r=0.42203이다. Delaunay 알고리즘은 이러한 물리적 domain "
            "차이를 알지 못하고 두 point를 직접 edge로 연결한다.",
            styles["body"],
        )
    )
    story.append(
        p(
            "또한 2022EE 입력에는 pre-EE에 존재했던 m<sub>chi</sub>=10-50 GeV "
            "point 7개가 없다. lower convex hull에는 최대 약 1.7-2.2 TeV 길이의 "
            "triangle edge가 만들어지며, m<sub>chi</sub> 약 150 GeV에서 contour가 "
            "급격히 꺾이는 현상을 강화한다.",
            styles["body"],
        )
    )

    story.append(p("4. Combine 수치 안정성 점검", styles["h1"]))
    combine_checks = [
        [
            p("점검 항목", styles["table"]),
            p("결과", styles["table"]),
            p("판정", styles["table"]),
        ],
        [
            p("Expected quantile 단조성", styles["table_left"]),
            p("-2 sigma < -1 sigma < median < +1 sigma < +2 sigma", styles["table_left"]),
            p("정상", styles["table"]),
        ],
        [
            p("영향 point의 quantile 비율", styles["table_left"]),
            p("-1 sigma / median 약 0.716, +1 sigma / median 약 1.41", styles["table_left"]),
            p("point 간 일관", styles["table"]),
        ],
        [
            p("Limit 로그", styles["table_left"]),
            p("convergence failure, NaN, invalid covariance 경고 없음", styles["table_left"]),
            p("정상", styles["table"]),
        ],
        [
            p("Blinding", styles["table_left"]),
            p("--run blind, observed key 0개", styles["table_left"]),
            p("정상", styles["table"]),
        ],
    ]
    story.append(styled_table(combine_checks, widths=[49 * mm, 92 * mm, 33 * mm]))
    story.append(
        p(
            "따라서 특정 mass point의 minimizer 실패나 잘못된 quantile이 kink를 "
            "만들었다는 증거는 없다. 위치를 결정하는 것은 실제 discrete limit 값이며, "
            "날카로운 형태를 만드는 것은 그 값을 연결하는 전역 piecewise-linear "
            "interpolation이다.",
            styles["body"],
        )
    )

    story.append(PageBreak())
    story.append(p("5. 적색 1 sigma band가 더 날카로운 이유", styles["h1"]))
    story.append(
        p(
            "expected_minus1과 expected_plus1 surface는 median과 독립적으로 각각 "
            "보간된다. 그 후 아래 조건을 만족하는 grid cell을 적색 영역으로 채운다.",
            styles["body"],
        )
    )
    story.append(
        p(
            "expected_minus1 <= 1 <= expected_plus1",
            styles["equation"],
        )
    )
    story.append(
        p(
            "두 경계가 서로 다른 triangle에서 r=1을 통과하므로 각각 별도의 kink를 "
            "가진다. 마지막에 두 영역 사이를 채우면 검은 median contour보다 폭이 "
            "넓고 돌출된 polygon 형태가 나타난다. 이는 uncertainty 계산의 오류가 "
            "아니라 두 개의 kinked piecewise-linear contour를 채운 결과이다.",
            styles["body"],
        )
    )

    story.append(p("6. 원인별 영향도", styles["h1"]))
    assessment = [
        [
            p("요인", styles["table"]),
            p("영향도", styles["table"]),
            p("평가", styles["table"]),
        ],
        [
            p("전역 Delaunay piecewise-linear 보간", styles["table_left"]),
            p("매우 큼", styles["table"]),
            p("triangle 경계에서 gradient 불연속을 직접 생성", styles["table_left"]),
        ],
        [
            p("on/off-shell 미분리", styles["table_left"]),
            p("매우 큼", styles["table"]),
            p("급격히 다른 acceptance를 같은 triangle에 연결", styles["table_left"]),
        ],
        [
            p("희소하고 불규칙한 mass grid", styles["table_left"]),
            p("큼", styles["table"]),
            p("긴 edge와 넓은 triangle을 생성", styles["table_left"]),
        ],
        [
            p("(1750,700)의 r=0.99244", styles["table_left"]),
            p("국소적으로 큼", styles["table"]),
            p("r=1 contour apex 위치를 고정", styles["table_left"]),
        ],
        [
            p("25 GeV plotting grid", styles["table_left"]),
            p("작음", styles["table"]),
            p("시각적 계단 효과만 추가", styles["table_left"]),
        ],
        [
            p("Combine minimizer", styles["table_left"]),
            p("근거 없음", styles["table"]),
            p("로그 및 quantile 진단 정상", styles["table_left"]),
        ],
    ]
    story.append(styled_table(assessment, widths=[64 * mm, 29 * mm, 81 * mm]))

    story.append(p("7. 수정 시 필요한 분석 선택", styles["h1"]))
    options = [
        [
            p("선택지", styles["table"]),
            p("효과", styles["table"]),
            p("주의점", styles["table"]),
        ],
        [
            p("on/off-shell 별도 triangulation", styles["table_left"]),
            p("물리적 threshold를 횡단하는 triangle 제거", styles["table_left"]),
            p("경계에서 두 surface를 어떻게 접합할지 규칙 필요", styles["table_left"]),
        ],
        [
            p("shell 횡단 및 장거리 triangle mask", styles["table_left"]),
            p("지원되지 않는 넓은 영역의 contour 제거", styles["table_left"]),
            p("최대 edge 길이 기준을 분석적으로 결정해야 함", styles["table_left"]),
        ],
        [
            p("추가 simulation point 생산", styles["table_left"]),
            p("가장 직접적으로 grid 의존성 감소", styles["table_left"]),
            p("추가 MC 생산 비용 필요", styles["table_left"]),
        ],
        [
            p("단순 spline smoothing", styles["table_left"]),
            p("시각적으로 매끄럽게 보임", styles["table_left"]),
            p("threshold를 가로질러 임의의 exclusion을 만들 수 있어 비권장", styles["table_left"]),
        ],
    ]
    story.append(styled_table(options, widths=[52 * mm, 61 * mm, 61 * mm]))

    status = Table(
        [
            [
                p(
                    "<b>현재 상태</b><br/>본 보고서는 원인 진단만 수행하였다. "
                    "limit 값, interpolation surface 및 최종 플롯은 변경하지 않았다. "
                    "보간 수정은 shell domain 정의와 triangle mask 기준을 명시적으로 "
                    "결정한 뒤 수행해야 한다.",
                    styles["callout"],
                )
            ]
        ],
        colWidths=[174 * mm],
    )
    status.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), ACCENT_LIGHT),
                ("BOX", (0, 0), (-1, -1), 1.0, ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(status)

    story.append(p("검토 자료", styles["h2"]))
    sources = [
        "outputs/2022EE/limits/limits.json",
        "outputs/2022EE/interpolation/limit_interpolation.png",
        "outputs/2022EE/validation/validation_report.json",
        "workflow/interpolate_limits.py",
    ]
    for source in sources:
        story.append(p(source, styles["small"]))

    document.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


def main() -> None:
    args = parse_args()
    build_report(args.output.resolve(), args.pdf.resolve())
    print(args.pdf.resolve())


if __name__ == "__main__":
    main()
