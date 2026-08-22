<#ftl output_format="plainText">
<#-- Plain-text part. Keycloak sends both; some clients show only this one. -->
Someone asked to reset the password for the AgriPulse account
${user.email!''}.

Choose a new password here:

${link}

The link expires in ${linkExpirationFormatter(linkExpiration)} and can be
used once.

If this was not you, ignore this email. Your password stays as it is, and
nobody can reset it without this link.

--
AgriPulse - admin@agripulse.tech. Replies are not read.
