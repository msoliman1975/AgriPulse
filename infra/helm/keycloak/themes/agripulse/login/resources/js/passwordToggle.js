/*
 * AgriPulse — password visibility toggle.
 *
 * The parent keycloak.v2 template.ftl loads its own
 * `js/passwordVisibility.js`; our template.ftl replaces that file
 * wholesale, so the eye buttons rendered by the inherited
 * `field.ftl` macros had no listener and did nothing. This is the
 * replacement, wired to the same contract the parent macros emit:
 *
 *   <button data-password-toggle aria-controls="<input id>"
 *           data-label-show="…" data-label-hide="…">
 *
 * so it drives both our own templates and any inherited page
 * (register, update-password) without forking those files.
 *
 * Loaded as `type="module"`, so it runs after the DOM is parsed and
 * needs no inline script (KC 26 CSP rejects inline JS).
 */
const buttons = document.querySelectorAll("[data-password-toggle]");

for (const button of buttons) {
  const input = document.getElementById(button.getAttribute("aria-controls"));
  if (!input) continue;

  const labelShow = button.dataset.labelShow || "Show password";
  const labelHide = button.dataset.labelHide || "Hide password";

  // Only reveal the control once we know it works — a dead eye button
  // is worse than no eye button.
  button.hidden = false;
  button.setAttribute("aria-pressed", "false");
  button.setAttribute("aria-label", labelShow);

  button.addEventListener("click", () => {
    const revealing = input.type === "password";
    input.type = revealing ? "text" : "password";
    button.setAttribute("aria-pressed", revealing ? "true" : "false");
    button.setAttribute("aria-label", revealing ? labelHide : labelShow);
    button.classList.toggle("is-revealed", revealing);
    // Keep the caret where the user left it.
    input.focus();
  });
}
