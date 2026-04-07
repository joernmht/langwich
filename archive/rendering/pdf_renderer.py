"""Cupertino-style PDF worksheet renderer.

Assembles a complete worksheet PDF from a list of exercise flowables,
adding headers, footers, page numbers, and the "langwich" branding.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Flowable,
)

from langwich.config import PDFConfig, settings
from langwich.db.models import CEFRLevel
from langwich.paths.template import TaskSize
from langwich.rendering.components import (
    A4_USABLE_HEIGHT,
    PageFillerFlowable,
    section_divider,
    target_height_for_size,
)
from langwich.rendering.styles import (
    BRAND_DARK,
    BRAND_GREY,
    SPACE_LG,
    footer_style,
    header_style,
    title_style,
)

logger = logging.getLogger(__name__)


class PDFRenderer:
    """Renders a complete worksheet PDF with Cupertino-style design.

    Parameters
    ----------
    config : PDFConfig | None
        PDF rendering configuration; uses global settings if *None*.
    """

    def __init__(self, config: PDFConfig | None = None) -> None:
        self.cfg = config or settings.pdf

    # ── Public API ───────────────────────────────────────────────────

    def render(
        self,
        exercise_flowables: list[list[Flowable]],
        output_path: Path | str,
        title: str = "Worksheet",
        domain: str = "",
        level: CEFRLevel = CEFRLevel.B1,
        worksheet_date: date | None = None,
        exercise_sizes: list[TaskSize | None] | None = None,
    ) -> Path:
        """Build and save the PDF worksheet.

        Parameters
        ----------
        exercise_flowables : list[list[Flowable]]
            Each inner list is the flowables for one exercise section.
        output_path : Path | str
            Where to write the PDF file.
        title : str
            Worksheet title (rendered in the page header).
        domain : str
            Knowledge domain label.
        level : CEFRLevel
            Target CEFR level for the header badge.
        worksheet_date : date | None
            Date to print; defaults to today.
        exercise_sizes : list[TaskSize | None] | None
            Parallel list of sizes for each exercise section.  Entries
            that are *None* (or if the whole list is *None*) get the old
            free-flow behaviour.  When sizes are given the renderer pads
            each exercise to the target height and inserts page breaks so
            that half-page pairs share a page, full tasks get one page,
            and double tasks get two pages.

        Returns
        -------
        Path
            The path to the written PDF.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ws_date = worksheet_date or date.today()

        doc = BaseDocTemplate(
            str(output_path),
            pagesize=A4,
            leftMargin=self.cfg.margin,
            rightMargin=self.cfg.margin,
            topMargin=self.cfg.margin + 20,
            bottomMargin=self.cfg.margin + 20,
        )

        frame = Frame(
            doc.leftMargin,
            doc.bottomMargin,
            doc.width,
            doc.height,
            id="main",
        )

        def _header_footer(canvas: Any, doc: Any) -> None:
            """Draw header and footer on every page."""
            canvas.saveState()

            # Header
            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(BRAND_GREY)
            canvas.drawString(
                self.cfg.margin,
                A4[1] - self.cfg.margin + 4,
                f"{self.cfg.brand_name}  |  {domain}  |  {level.value}",
            )
            canvas.drawRightString(
                A4[0] - self.cfg.margin,
                A4[1] - self.cfg.margin + 4,
                ws_date.strftime("%d %B %Y"),
            )

            # Header rule
            canvas.setStrokeColor(BRAND_GREY)
            canvas.setLineWidth(0.5)
            y_rule = A4[1] - self.cfg.margin - 2
            canvas.line(self.cfg.margin, y_rule, A4[0] - self.cfg.margin, y_rule)

            # Footer
            canvas.setFont("Helvetica", 8)
            canvas.drawCentredString(
                A4[0] / 2,
                self.cfg.margin - 12,
                f"{self.cfg.brand_name}  —  Page {doc.page}",
            )

            canvas.restoreState()

        template = PageTemplate(id="worksheet", frames=[frame], onPage=_header_footer)
        doc.addPageTemplates([template])

        # Build the story
        story: list[Flowable] = []

        # Title
        story.append(Paragraph(title, title_style()))
        story.append(Spacer(1, SPACE_LG))

        # Normalise the sizes list so it is always parallel with flowables.
        sizes: list[TaskSize | None] = list(exercise_sizes) if exercise_sizes else []
        while len(sizes) < len(exercise_flowables):
            sizes.append(None)

        self._build_sized_story(story, exercise_flowables, sizes)

        doc.build(story)
        logger.info("PDF written to %s", output_path)
        return output_path

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    def _build_sized_story(
        story: list[Flowable],
        sections: list[list[Flowable]],
        sizes: list[TaskSize | None],
    ) -> None:
        """Append exercise sections to *story* respecting size constraints.

        Half-page tasks are consumed in pairs and placed on the same page
        separated by a divider.  Full and double tasks each start on a
        fresh page.

        Free-flow (None-sized) sections flow naturally.  A ``CondPageBreak``
        is used instead of a hard ``PageBreak`` so that transitions from
        short free-flow sections (e.g. a grammar reference) into sized
        exercises do not leave blank pages.
        """
        half_height = target_height_for_size(TaskSize.HALF.value)
        full_height = target_height_for_size(TaskSize.FULL.value)
        idx = 0
        is_first_exercise = True
        had_sized_section = False

        while idx < len(sections):
            size = sizes[idx]
            flowables = sections[idx]

            if size is None:
                # Free-flow section (grammar page, vocab reference, AI tip).
                if had_sized_section:
                    # After a sized exercise finished, start a new page.
                    story.append(PageBreak())
                    had_sized_section = False
                elif not is_first_exercise:
                    story.extend(section_divider())
                story.extend(flowables)
                idx += 1

            elif size == TaskSize.HALF:
                # Consume the next section as the pair partner.
                if had_sized_section:
                    story.append(PageBreak())
                elif not is_first_exercise:
                    # After free-flow content, only break if there isn't
                    # enough room for the full half-pair.
                    story.append(CondPageBreak(half_height * 2))
                partner_flowables = sections[idx + 1] if idx + 1 < len(sections) else []

                # First half
                story.append(
                    PageFillerFlowable(list(flowables), half_height)
                )
                # Divider between the two halves
                story.extend(section_divider())
                # Second half
                if partner_flowables:
                    story.append(
                        PageFillerFlowable(list(partner_flowables), half_height)
                    )
                idx += 2
                had_sized_section = True

            elif size == TaskSize.FULL:
                if had_sized_section:
                    story.append(PageBreak())
                elif not is_first_exercise:
                    story.append(CondPageBreak(full_height))
                target_h = full_height
                story.append(PageFillerFlowable(list(flowables), target_h))
                idx += 1
                had_sized_section = True

            elif size == TaskSize.DOUBLE:
                if not is_first_exercise:
                    story.append(PageBreak())
                target_h = target_height_for_size(TaskSize.DOUBLE.value)
                story.append(PageFillerFlowable(list(flowables), target_h))
                idx += 1
                had_sized_section = True

            else:
                # Unknown size — fall through to free-flow
                if had_sized_section:
                    story.append(PageBreak())
                    had_sized_section = False
                elif not is_first_exercise:
                    story.extend(section_divider())
                story.extend(flowables)
                idx += 1

            is_first_exercise = False
