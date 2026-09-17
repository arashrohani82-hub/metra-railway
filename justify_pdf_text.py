"""Force left-aligned ODS paragraph text to full justification.

Centered/right-aligned headings and numeric cells keep their existing alignment.
This affects the PDF body for all STR/CIV/GEO offers without changing canvas
header/footer drawing.
"""
import copy

from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY

import department_ods_patch as dept


_ORIGINAL_PARAGRAPH = dept._original_paragraph


def justified_paragraph(text, *args, **kwargs):
    # ReportLab Paragraph(text, style, ...) normally receives the style as the
    # first positional argument. Clone it so we never mutate a shared stylesheet.
    if args:
        style = args[0]
        if getattr(style, 'alignment', TA_LEFT) == TA_LEFT:
            style = copy.copy(style)
            style.alignment = TA_JUSTIFY
            args = (style,) + tuple(args[1:])
    elif 'style' in kwargs:
        style = kwargs.get('style')
        if style is not None and getattr(style, 'alignment', TA_LEFT) == TA_LEFT:
            style = copy.copy(style)
            style.alignment = TA_JUSTIFY
            kwargs['style'] = style
    return _ORIGINAL_PARAGRAPH(text, *args, **kwargs)


# department_ods_patch.generate_pdf() resolves this global each time it builds
# a Paragraph, so replacing it here applies justification to every department.
dept._original_paragraph = justified_paragraph

dept.legacy.logger.warning(
    'ODS PDF JUSTIFICATION ACTIVE: left-aligned Paragraph text -> TA_JUSTIFY'
)
