"""Final ODS email branding loaded last in runtime.

Keeps the client email body clean, uses the new Metra Consultation website,
and shows the Metra logo in the HTML signature.
"""
import html
import os

import app as ods

PUBLIC_URL = os.environ.get('PUBLIC_URL', '').strip().rstrip('/')
if not PUBLIC_URL:
    railway_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '').strip()
    PUBLIC_URL = f'https://{railway_domain}' if railway_domain else 'https://web-production-c7adbe.up.railway.app'
LOGO_URL = f'{PUBLIC_URL}/assets/metra-logo.png'


def email_logo_final():
    return ods.send_file(ods.LOGOS['metra'], mimetype='image/png', max_age=86400)

if 'email_logo_final' not in ods.app.view_functions:
    ods.app.add_url_rule('/assets/metra-logo.png', 'email_logo_final', email_logo_final, methods=['GET'])


def email_body_html(body):
    intro = str(body or '').rsplit('Cordialement,', 1)[0].strip()
    blocks = []
    for part in intro.split('\n\n'):
        part = part.strip()
        if part:
            blocks.append(
                '<p style="margin:0 0 14px 0;font-family:Arial,sans-serif;font-size:15px;line-height:1.55;color:#1f2937;">'
                + html.escape(part).replace('\n', '<br>')
                + '</p>'
            )

    signature = f'''
    <div style="margin-top:18px;font-family:Arial,sans-serif;color:#1f2937;">
      <p style="margin:0 0 14px 0;font-size:15px;">Cordialement,</p>
      <table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
        <tr>
          <td style="vertical-align:middle;padding-right:16px;">
            <img src="{LOGO_URL}" alt="Metra Consultation" width="150" style="display:block;width:150px;max-width:150px;height:auto;border:0;">
          </td>
          <td style="vertical-align:top;border-left:4px solid #f5a623;padding-left:14px;">
            <div style="font-size:18px;font-weight:700;color:#12324a;line-height:1.25;">Arash Rohani, ing., P.Eng.</div>
            <div style="font-size:15px;margin-top:3px;">Président – Ingénieur en structure</div>
            <div style="font-size:16px;font-weight:700;margin-top:5px;">Metra Consultation Inc.</div>
            <div style="font-size:14px;margin-top:6px;">
              <a href="mailto:a.rohani@metraconsultation.ca" style="color:#1155cc;text-decoration:none;">a.rohani@metraconsultation.ca</a>
              &nbsp;|&nbsp;
              <a href="tel:+14388674131" style="color:#1155cc;text-decoration:none;">(438) 867-4131</a>
            </div>
            <div style="font-size:14px;margin-top:3px;">
              <a href="https://metraconsultation.ca" style="color:#1155cc;text-decoration:none;">metraconsultation.ca</a>
            </div>
          </td>
        </tr>
      </table>
    </div>
    '''
    return '<div style="font-family:Arial,sans-serif;">' + ''.join(blocks) + signature + '</div>'


ods.email_body_html = email_body_html
ods.logger.warning('FINAL ODS EMAIL BRANDING ACTIVE: logo + metraconsultation.ca')
