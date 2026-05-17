<#--
  AgriPulse login template — the base wrapper every login-area FTL
  extends via `<@layout.registrationLayout … ; section>`. By replacing
  this we get the split-pane brand chrome on every flow (login,
  login-update-password, login-reset-password, login-verify-email,
  error, info) without forking each one.

  Hero pane (left): brand lockup + locked slogan + locked lead.
  Form pane (right): nested form content from the calling .ftl, plus
  Keycloak's alert messages above the form.
-->
<#macro registrationLayout displayInfo=false displayMessage=true displayRequiredFields=false displayWide=false showAnonymousReqdActions=false>
<!DOCTYPE html>
<html lang="${locale.currentLanguageTag}" dir="ltr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <meta name="robots" content="noindex, nofollow" />
  <title>${msg("loginTitle",(realm.displayName!''))}</title>

  <#-- Inherited theme.properties `styles=` is rendered here. -->
  <#if properties.stylesCommon?has_content>
    <#list properties.stylesCommon?split(' ') as style>
      <link href="${url.resourcesCommonPath}/${style}" rel="stylesheet" />
    </#list>
  </#if>
  <#if properties.styles?has_content>
    <#list properties.styles?split(' ') as style>
      <link href="${url.resourcesPath}/${style}" rel="stylesheet" />
    </#list>
  </#if>

  <link rel="icon" type="image/svg+xml" href="${url.resourcesPath}/img/mark.svg" />
</head>
<body class="agripulse">

  <div class="stage">

    <#-- ============================================================
         HERO PANE
         ============================================================ -->
    <section class="hero" aria-hidden="true">
      <div class="brand">
        <#-- CSP-safe brand mark: zigzag polygon points pre-computed so
             no inline <script> is needed (KC 26 default CSP rejects
             inline JS). The SVG file at resources/img/mark.svg has the
             same content; we inline here so the hero never flashes
             without the mark while the external file fetches. -->
        <svg class="brand-mark" viewBox="0 0 200 200" aria-hidden="true" focusable="false">
          <defs>
            <linearGradient id="ap-leaf-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stop-color="#a7d2b9"/>
              <stop offset="55%"  stop-color="#3FB58A"/>
              <stop offset="100%" stop-color="#0F6E56"/>
            </linearGradient>
            <radialGradient id="ap-ring-fill" cx="50%" cy="40%" r="55%">
              <stop offset="0%"   stop-color="rgba(255,255,255,0.55)"/>
              <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
            </radialGradient>
            <filter id="ap-pulse-glow" x="-20%" y="-50%" width="140%" height="200%">
              <feGaussianBlur stdDeviation="1.3"/>
            </filter>
            <filter id="ap-leaf-shadow" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#04342C" flood-opacity=".25"/>
            </filter>
          </defs>

          <circle cx="100" cy="100" r="92" fill="url(#ap-ring-fill)"/>

          <#-- 24-tooth zigzag rim — 48 points, alternating ro=96 / ri=86 around (100,100). -->
          <polygon
            points="100.00,4.00 111.23,14.74 124.85,7.27 132.91,20.55 148.00,16.86 152.35,31.77 167.88,32.12 168.23,47.65 183.14,52.00 179.45,67.09 192.73,75.15 185.26,88.77 196.00,100.00 185.26,111.23 192.73,124.85 179.45,132.91 183.14,148.00 168.23,152.35 167.88,167.88 152.35,168.23 148.00,183.14 132.91,179.45 124.85,192.73 111.23,185.26 100.00,196.00 88.77,185.26 75.15,192.73 67.09,179.45 52.00,183.14 47.65,168.23 32.12,167.88 31.77,152.35 16.86,148.00 20.55,132.91 7.27,124.85 14.74,111.23 4.00,100.00 14.74,88.77 7.27,75.15 20.55,67.09 16.86,52.00 31.77,47.65 32.12,32.12 47.65,31.77 52.00,16.86 67.09,20.55 75.15,7.27 88.77,14.74"
            fill="none" stroke="#1D9E75" stroke-width="1.8" stroke-linejoin="round"/>

          <#-- ECG pulse — glow halo + crisp stroke on top. Only red in
               the whole brand is here. -->
          <path filter="url(#ap-pulse-glow)" opacity=".55"
                d="M22 102 L62 102 L72 86 L82 116 L100 76 L118 112 L126 96 L140 102 L178 100"
                fill="none" stroke="#E24B4A" stroke-width="5"
                stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M22 102 L62 102 L72 86 L82 116 L100 76 L118 112 L126 96 L140 102 L178 100"
                fill="none" stroke="#E24B4A" stroke-width="2.8"
                stroke-linecap="round" stroke-linejoin="round"/>

          <#-- Mango leaf with drop-shadow + vein detail. -->
          <g filter="url(#ap-leaf-shadow)">
            <path d="M100 22 Q122 42 132 64 Q142 86 140 108 Q137 128 126 144 Q115 156 100 164 Q85 156 74 144 Q63 128 60 108 Q58 86 68 64 Q78 42 100 22Z"
                  fill="url(#ap-leaf-grad)" stroke="#04342C" stroke-width="1.2" stroke-opacity=".5"/>
            <path d="M100 28 L100 158" stroke="#04342C" stroke-width="1.1" opacity=".35"/>
            <path d="M100 46 Q92 51 84 60 M100 46 Q108 51 116 60
                     M100 66 Q90 72 80 84 M100 66 Q110 72 120 84
                     M100 86 Q88 93 76 106 M100 86 Q112 93 124 106
                     M100 106 Q90 111 80 122 M100 106 Q110 111 120 122"
                  stroke="#04342C" stroke-width=".9" opacity=".28" fill="none"/>
          </g>
        </svg>
        <div class="brand-name">Agri<span class="pulse-word">Pulse</span></div>
      </div>

      <div class="hero-body">
        <h1>Plan the season. Grow the harvest. <span class="accent">Predict the yield.</span></h1>
        <p class="lead">AgriPulse is the planning, growth and prediction layer for orchard and row-crop teams — daily imagery, hyperlocal weather and agronomy signals reconciled into one workspace.</p>
      </div>

      <div class="hero-foot">
        <span>&copy; 2026 AgriPulse</span>
        <span>Powered by Keycloak</span>
      </div>
    </section>

    <#-- ============================================================
         FORM PANE
         ============================================================ -->
    <section class="form-side">
      <div class="form-wrap">
        <div class="form-card">

          <#-- Page heading: section "header" from the calling .ftl. -->
          <#if section??>
            <#if section = "header">
              <h2>${kcSanitize(msg("loginAccountTitle"))?no_esc}</h2>
              <#if realm.displayName?has_content>
                <p class="sub">${msg("doLogIn")} to ${realm.displayName}.</p>
              <#else>
                <p class="sub">${msg("doLogIn")} to AgriPulse.</p>
              </#if>
            </#if>
          </#if>

          <#-- Keycloak's standard message banner (errors, info). -->
          <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
            <div class="alert alert-${message.type}">
              <span class="kc-feedback-text">${kcSanitize(message.summary)?no_esc}</span>
            </div>
          </#if>

          <#-- The form / body content of the calling .ftl. -->
          <#nested "form">

          <#-- Footer info area, e.g. "Forgot Password?" + "Sign in". -->
          <#if displayInfo>
            <div class="form-info">
              <#nested "info">
            </div>
          </#if>

          <#-- Always-visible help line: invitation-only copy. The
               default Keycloak self-registration link is intentionally
               not rendered — we run invitation-only. -->
          <#if section?? && section = "form" && (realm.registrationAllowed!false) == false && (realm.password!false)>
            <div class="divider">${msg("noAccount")}</div>
            <p class="help">${msg("inviteOnly")}</p>
          </#if>

          <p class="footnote">v2026.05 &middot; powered by Keycloak</p>
        </div>
      </div>
    </section>

  </div>
</body>
</html>
</#macro>
