<#--
  "Reset your AgriPulse password."

  Reached from "Forgot password?" on the sign-in page
  (realm resetPasswordAllowed = true). Unlike executeActions this one is
  always self-started, so it can name the account and it must answer the
  question a security-aware reader asks first: what happens if this
  was not me.
-->
<#import "template.ftl" as layout>
<@layout.emailLayout
    headline="Reset your AgriPulse password"
    preheader="Someone asked to reset the password for this account. The link expires in ${linkExpirationFormatter(linkExpiration)}.">

  <@layout.para>Someone asked to reset the password for the AgriPulse account <strong style="color:#0f2a1f;">${user.email!''}</strong>.</@layout.para>

  <@layout.action url=link label="Choose a new password" />

  <@layout.notice><strong>The link expires in ${linkExpirationFormatter(linkExpiration)}</strong> and can be used once.</@layout.notice>

  <@layout.para top=22>If this was not you, ignore this email. Your password stays as it is, and nobody can reset it without this link.</@layout.para>

</@layout.emailLayout>
