"""Install the shared embedded-logo signature at the final runtime layer.

Reuse the same renderer and CID as send_ods_email instead of restoring a
second, remote-image signature after the earlier branding patch.
"""
import app as ods
from email_branding_patch import email_body_html

ods.email_body_html = email_body_html
ods.logger.warning('FINAL ODS EMAIL BRANDING ACTIVE: embedded company logo')
