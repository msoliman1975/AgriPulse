<#import "template.ftl" as layout>
<#--
  Welcome-back login form. The split-pane chrome is inherited from
  template.ftl; this file only fills:
    - section "header": ${msg("loginAccountTitle")} -> "Welcome back."
    - section "form"  : the actual email + password form
    - section "info"  : the "Forgot password?" link

  This same rendering surfaces for login-update-password,
  login-reset-password, login-verify-email — those .ftl files in the
  parent keycloak.v2 theme each render their own section "form" but
  still go through OUR template.ftl, so they inherit the brand chrome
  for free.
-->
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('username','password') displayInfo=(realm.password && realm.resetPasswordAllowed && !usernameHidden??); section>

  <#if section = "form">
    <div id="kc-form">
      <#if realm.password>
        <form id="kc-form-login" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post">
          <#if !usernameHidden??>
            <label for="username" class="form-label">
              <#if !realm.loginWithEmailAllowed>${msg("username")}
              <#elseif !realm.registrationEmailAsUsername>${msg("usernameOrEmail")}
              <#else>${msg("email")}
              </#if>
            </label>
            <div class="field">
              <input tabindex="1" id="username" name="username"
                     value="${(login.username!'')}" type="text"
                     autofocus
                     autocomplete="username"
                     placeholder="you@farm.com"
                     aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
              />
            </div>
            <#if messagesPerField.existsError('username','password')>
              <span id="input-error" class="field-error" aria-live="polite">
                ${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}
              </span>
            </#if>
          </#if>

          <label for="password" class="form-label">${msg("password")}</label>
          <div class="field">
            <input tabindex="2" id="password" name="password"
                   type="password"
                   autocomplete="current-password"
                   placeholder="••••••••"
                   aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
            />
          </div>
          <#if usernameHidden?? && messagesPerField.existsError('username','password')>
            <span id="input-error-pwd" class="field-error" aria-live="polite">
              ${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}
            </span>
          </#if>

          <div class="field-row">
            <#if realm.rememberMe && !usernameHidden??>
              <label class="checkbox">
                <#if login.rememberMe??>
                  <input tabindex="3" id="rememberMe" name="rememberMe" type="checkbox" checked />
                <#else>
                  <input tabindex="3" id="rememberMe" name="rememberMe" type="checkbox" />
                </#if>
                <span>${msg("rememberMe")}</span>
              </label>
            <#else>
              <span></span>
            </#if>

            <#if realm.resetPasswordAllowed>
              <a tabindex="5" href="${url.loginResetCredentialsUrl}">${msg("doForgotPassword")}</a>
            </#if>
          </div>

          <input type="hidden" id="id-hidden-input" name="credentialId"
                 <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>
          <button tabindex="4" class="btn-primary" name="login" id="kc-login" type="submit">
            ${kcSanitize(msg("doLogIn"))?no_esc}
          </button>
        </form>
      </#if>
    </div>
  </#if>

  <#if section = "info">
    <#-- Social providers, registration links etc. The default v2
         theme renders a registration "noAccount + doRegister" link
         here; we ALWAYS show our invitation-only line via
         template.ftl, so we let realm.password+!realm.registrationAllowed
         hide the default. -->
    <#if realm.password && social.providers??>
      <div id="kc-social-providers" class="social-providers">
        <hr/>
        <h4>${msg("identity-provider-login-label")}</h4>
        <ul>
          <#list social.providers as p>
            <li>
              <a class="social-link" id="social-${p.alias}" href="${p.loginUrl}">
                <span>${p.displayName!''}</span>
              </a>
            </li>
          </#list>
        </ul>
      </div>
    </#if>
  </#if>

</@layout.registrationLayout>
