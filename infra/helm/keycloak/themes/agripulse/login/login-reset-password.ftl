<#import "template.ftl" as layout>
<#--
  Forgot-password screen, reached from the "Forgot password?" link on
  login.ftl. Same reason for the override as login-update-password.ftl:
  the parent renders PatternFly markup our stylesheet does not cover.
-->
<@layout.registrationLayout displayInfo=false displayMessage=!messagesPerField.existsError('username'); section>

  <#if section = "header">
    ${msg("emailForgotTitle")}
  </#if>

  <#if section = "subhead">
    <p class="sub">
      <#if realm.duplicateEmailsAllowed>${msg("emailInstructionUsername")}<#else>${msg("emailInstruction")}</#if>
    </p>
  </#if>

  <#if section = "form">
    <form id="kc-reset-password-form" action="${url.loginAction}" method="post">
      <label for="username" class="form-label">
        <#if !realm.loginWithEmailAllowed>${msg("username")}
        <#elseif !realm.registrationEmailAsUsername>${msg("usernameOrEmail")}
        <#else>${msg("email")}
        </#if>
      </label>
      <div class="field">
        <input id="username" name="username" type="text" autofocus
               autocomplete="username"
               placeholder="you@farm.com"
               value="${(auth.attemptedUsername!'')}"
               aria-invalid="<#if messagesPerField.existsError('username')>true</#if>" />
      </div>
      <#if messagesPerField.existsError('username')>
        <span id="input-error-username" class="field-error" aria-live="polite">
          ${kcSanitize(messagesPerField.get('username'))?no_esc}
        </span>
      </#if>

      <button class="btn-primary" type="submit">${msg("doSendResetLink")}</button>
      <a class="btn-secondary btn-link" href="${url.loginUrl}">${kcSanitize(msg("backToLogin"))?no_esc}</a>
    </form>
  </#if>

</@layout.registrationLayout>
