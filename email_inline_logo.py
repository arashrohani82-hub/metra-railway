"""Embed the company signature logo using a Microsoft Graph inline attachment."""
import base64
from pathlib import Path

LOGO_CONTENT_ID = 'metra-logo@metraconsultation.ca'
LOGO_SOURCE = 'cid:' + LOGO_CONTENT_ID


def inline_logo_attachment(path):
    return {
        '@odata.type': '#microsoft.graph.fileAttachment',
        'name': 'metra-logo.png',
        'contentType': 'image/png',
        'isInline': True,
        'contentId': LOGO_CONTENT_ID,
        'contentBytes': base64.b64encode(Path(path).read_bytes()).decode('ascii'),
    }
