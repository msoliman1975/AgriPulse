<#--
  AgriPulse email layout. Mirrors the product-email shell built in
  backend/migrations/public/versions/0070_email_html_templates.py, so an
  invite and an alert read as the same product.

  Same constraints as the product side: 600 px, tables, inline styles, no
  <style> block, no images. Outlook on Windows renders with Word, and a
  brand that disappears when a client blocks images is not a brand — the
  wordmark is letter-spaced text.

  The rail is brand green rather than a severity colour. Nothing about a
  password is graded info / warning / critical.

  Parameters:
    preheader  one line shown next to the subject in the inbox list
    headline   the <h1>
  The caller's nested content is the body.
-->
<#macro emailLayout preheader="" headline="">
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background-color:#eceae2;-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#eceae2;">${preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eceae2;">
<tr><td align="center" style="padding:24px 12px;">

<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;background-color:#ffffff;font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;color:#0f2a1f;">

  <tr><td style="height:5px;background-color:#0f6e56;line-height:5px;font-size:0;">&nbsp;</td></tr>

  <tr><td style="padding:26px 36px 0 36px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td style="font-size:14px;font-weight:700;letter-spacing:2.4px;color:#0f6e56;">AGRIPULSE</td>
      <td align="right" style="font-size:11px;letter-spacing:1.4px;color:#5e7669;text-transform:uppercase;">Account</td>
    </tr></table>
  </td></tr>

  <tr><td style="padding:30px 36px 0 36px;">
    <h1 style="margin:0;font-size:23px;line-height:1.3;font-weight:600;color:#0f2a1f;">${headline}</h1>
  </td></tr>

  <#nested>

  <tr><td style="padding:30px 36px 30px 36px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td style="border-top:1px solid #e3e0d6;padding-top:16px;">
        <p style="margin:0;font-size:11px;line-height:1.6;color:#8a9489;">AgriPulse &middot; admin@agripulse.tech<br>Sent by an automated system. Replies are not read.</p>
      </td>
    </tr></table>
  </td></tr>

</table>

</td></tr>
</table>
</body>
</html>
</#macro>

<#--
  A paragraph in the body column. Keeps the 36 px gutter in one place so
  a template never re-types it and drifts.
-->
<#macro para top=14>
<tr><td style="padding:${top}px 36px 0 36px;">
  <p style="margin:0;font-size:15px;line-height:1.62;color:#2e4a3d;"><#nested></p>
</td></tr>
</#macro>

<#--
  The button, plus the same URL in plain text underneath. Some clients
  strip a styled anchor; nobody should be stuck because of that.
  bgcolor on the cell (not a CSS background) is what makes Outlook paint it.
-->
<#macro action url label>
<tr><td style="padding:26px 36px 0 36px;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
    <td bgcolor="#0f6e56" style="border-radius:3px;">
      <a href="${url}" style="display:inline-block;padding:13px 28px;font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;font-size:15px;font-weight:600;color:#ffffff;text-decoration:none;">${label}</a>
    </td>
  </tr></table>
  <p style="margin:12px 0 0 0;font-size:12px;line-height:1.5;color:#5e7669;">Or paste this into your browser:<br><span style="color:#0f6e56;word-break:break-all;">${url}</span></p>
</td></tr>
</#macro>

<#-- The tinted block that carries the one fact a reader must not miss. -->
<#macro notice>
<tr><td style="padding:24px 36px 0 36px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f7f6f1;border-left:3px solid #0f6e56;">
    <tr><td style="padding:14px 18px;">
      <p style="margin:0;font-size:13.5px;line-height:1.6;color:#2e4a3d;"><#nested></p>
    </td></tr>
  </table>
</td></tr>
</#macro>
