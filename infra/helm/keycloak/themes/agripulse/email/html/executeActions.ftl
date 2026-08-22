<#--
  "Set your AgriPulse password."

  One template, three product paths, all of which call
  PUT /users/{id}/execute-actions-email with ["UPDATE_PASSWORD"]:
    * invite a tenant user      (iam/users_service.invite_user)
    * invite a platform admin   (keycloak/client.invite_platform_admin)
    * resend an invite          (keycloak/client.resend_invite)

  So the copy has to work for someone who was expecting it and for
  someone who was not, without knowing which. It never says "welcome" —
  a resend to a person who has been waiting three days would read as a
  system that has lost track of them.
-->
<#import "template.ftl" as layout>
<@layout.emailLayout
    headline="Set your AgriPulse password"
    preheader="Your account is ready. The link works once and expires in ${linkExpirationFormatter(linkExpiration)}.">

  <@layout.para>Hello<#if user.firstName??> ${user.firstName}</#if>,</@layout.para>

  <@layout.para top=12>An AgriPulse account has been created for you. Choose a password and you are in. Nothing else is needed.</@layout.para>

  <@layout.action url=link label="Set my password" />

  <@layout.notice><strong>This link works once and expires in ${linkExpirationFormatter(linkExpiration)}.</strong> If it has run out, ask whoever invited you to send a new one from Settings &rsaquo; Users.</@layout.notice>

  <@layout.para top=22>If you were not expecting this email, you can ignore it. No account is active until a password is set.</@layout.para>

</@layout.emailLayout>
