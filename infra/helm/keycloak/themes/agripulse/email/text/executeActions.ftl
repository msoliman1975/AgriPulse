<#ftl output_format="plainText">
<#-- Plain-text part. Keycloak sends both; some clients show only this one. -->
Hello<#if user.firstName??> ${user.firstName}</#if>,

An AgriPulse account has been created for you. Set a password here:

${link}

This link works once and expires in ${linkExpirationFormatter(linkExpiration)}.
If it has run out, ask whoever invited you to send a new one from
Settings > Users.

If you were not expecting this email, you can ignore it. No account is
active until a password is set.

--
AgriPulse - admin@agripulse.tech. Replies are not read.
