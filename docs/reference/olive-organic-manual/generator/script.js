(function () {
  var views = document.querySelectorAll(".lang");
  var buttons = document.querySelectorAll(".switch button");
  function setLang(l) {
    views.forEach(function (v) { v.hidden = v.getAttribute("data-lang") !== l; });
    buttons.forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-l") === l)); });
    document.documentElement.lang = l;
    document.documentElement.dir = l === "ar" ? "rtl" : "ltr";
    try { localStorage.setItem("medjool-lang", l); } catch (e) {}
  }
  buttons.forEach(function (b) { b.addEventListener("click", function () { setLang(b.getAttribute("data-l")); }); });
  var start = "ar";
  var h = (location.hash || "").replace("#", "");
  if (h === "en" || h.indexOf("en-") === 0) start = "en";
  else if (h === "ar" || h.indexOf("ar-") === 0) start = "ar";
  else { try { start = localStorage.getItem("medjool-lang") || "ar"; } catch (e) {} }
  setLang(start);

  document.querySelectorAll(".filters").forEach(function (group) {
    var table = group.nextElementSibling.querySelector("tbody");
    group.addEventListener("click", function (ev) {
      var btn = ev.target.closest(".pf");
      if (!btn) return;
      group.querySelectorAll(".pf").forEach(function (b) { b.classList.toggle("on", b === btn); });
      var p = btn.getAttribute("data-p");
      table.querySelectorAll("tr").forEach(function (tr) { tr.hidden = p !== "all" && tr.getAttribute("data-p") !== p; });
    });
  });
  if (window.matchMedia && window.matchMedia("(max-width:900px)").matches) {
    document.querySelectorAll(".toc details").forEach(function (d) { d.open = false; });
  }
})();
