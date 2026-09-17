<#import "template.ftl" as layout>
<#--
  Set / change password — the screen an invited user lands on from the
  welcome email (execute-actions-email with UPDATE_PASSWORD).

  The parent keycloak.v2 file of this name renders PatternFly markup
  (pf-v5-c-form, pf-v5-c-input-group, …) which our login.css does not
  style, so the page looked nothing like login.ftl. This override uses
  the same element vocabulary as login.ftl — .form-label, .field,
  .btn-primary — so both screens render from one stylesheet.

  The eye button is driven by resources/js/passwordToggle.js, loaded by
  our template.ftl. It stays `hidden` until that script claims it.
-->
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('password','password-confirm'); section>

  <#if section = "header">
    ${msg("updatePasswordTitle")}
  </#if>

  <#if section = "subhead">
    <p class="sub">${msg("updatePasswordSubtitle")}</p>
  </#if>

  <#if section = "form">
    <form id="kc-passwd-update-form" action="${url.loginAction}" method="post" novalidate="novalidate">

      <label for="password-new" class="form-label">${msg("passwordNew")}</label>
      <div class="field field-password">
        <input id="password-new" name="password-new" type="password"
               autocomplete="new-password" autofocus
               placeholder="••••••••"
               aria-invalid="<#if messagesPerField.existsError('password')>true</#if>" />
        <button type="button" class="toggle-visibility" hidden
                data-password-toggle aria-controls="password-new"
                data-label-show="${msg('showPassword')}"
                data-label-hide="${msg('hidePassword')}">
          <span class="eye-open" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
              <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
          </span>
          <span class="eye-shut" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
              <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z"/>
              <circle cx="12" cy="12" r="3"/>
              <path d="M4 20 20 4"/>
            </svg>
          </span>
        </button>
      </div>
      <#if messagesPerField.existsError('password')>
        <span id="input-error-password" class="field-error" aria-live="polite">
          ${kcSanitize(messagesPerField.get('password'))?no_esc}
        </span>
      </#if>

      <label for="password-confirm" class="form-label">${msg("passwordConfirm")}</label>
      <div class="field field-password">
        <input id="password-confirm" name="password-confirm" type="password"
               autocomplete="new-password"
               placeholder="••••••••"
               aria-invalid="<#if messagesPerField.existsError('password-confirm')>true</#if>" />
        <button type="button" class="toggle-visibility" hidden
                data-password-toggle aria-controls="password-confirm"
                data-label-show="${msg('showPassword')}"
                data-label-hide="${msg('hidePassword')}">
          <span class="eye-open" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
              <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
          </span>
          <span class="eye-shut" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
              <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z"/>
              <circle cx="12" cy="12" r="3"/>
              <path d="M4 20 20 4"/>
            </svg>
          </span>
        </button>
      </div>
      <#if messagesPerField.existsError('password-confirm')>
        <span id="input-error-password-confirm" class="field-error" aria-live="polite">
          ${kcSanitize(messagesPerField.get('password-confirm'))?no_esc}
        </span>
      </#if>

      <div class="field-row">
        <label class="checkbox" for="logout-sessions">
          <input type="checkbox" id="logout-sessions" name="logout-sessions" value="on" checked />
          <span>${msg("logoutOtherSessions")}</span>
        </label>
      </div>

      <#-- App-initiated (opened from the account console) gets a
           Cancel; the invite-email path has nothing to go back to, so
           it gets a single full-width button. -->
      <button class="btn-primary" type="submit">${msg("doSubmit")}</button>
      <#if isAppInitiatedAction??>
        <button class="btn-secondary" type="submit" name="cancel-aia" value="true">${msg("doCancel")}</button>
      </#if>
    </form>
  </#if>

</@layout.registrationLayout>
