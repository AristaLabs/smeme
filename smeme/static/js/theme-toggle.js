/* Theme toggle button (#theme-toggle): cycles light -> dark -> system, persists
   to the smeme_theme cookie, and keeps the SSR-rendered icon/label in sync.
   Complements the pre-paint boot in theme-boot.js. */
(function () {
  var toggle = document.getElementById("theme-toggle");
  if (!toggle) return;

  var cookieName = "smeme_theme";
  var maxAge = 365 * 24 * 3600;
  var cycle = ["light", "dark", "system"];
  var labels = {
    light: "Theme: light. Click for dark.",
    dark: "Theme: dark. Click for system.",
    system: "Theme: system (follows device). Click for light.",
  };
  var titles = {
    light: "Theme: light",
    dark: "Theme: dark",
    system: "Theme: system",
  };

  function readPreference() {
    var match = document.cookie.match(new RegExp("(?:^|; )" + cookieName + "=([^;]*)"));
    var pref = match ? decodeURIComponent(match[1]).trim().toLowerCase() : "system";
    if (pref !== "light" && pref !== "dark" && pref !== "system") pref = "system";
    return pref;
  }

  function systemPrefersDark() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function applyPreference(pref) {
    document.documentElement.setAttribute("data-theme-pref", pref);
    var dark = pref === "dark" || (pref === "system" && systemPrefersDark());
    document.documentElement.classList.toggle("dark", dark);
    toggle.setAttribute("aria-label", labels[pref]);
    toggle.setAttribute("title", titles[pref]);
  }

  function writePreference(pref) {
    document.cookie =
      cookieName + "=" + encodeURIComponent(pref) + "; path=/; max-age=" + maxAge + "; samesite=lax";
    applyPreference(pref);
  }

  function nextPreference(current) {
    var idx = cycle.indexOf(current);
    if (idx === -1) idx = cycle.indexOf("system");
    return cycle[(idx + 1) % cycle.length];
  }

  applyPreference(readPreference());

  toggle.addEventListener("click", function () {
    writePreference(nextPreference(readPreference()));
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
    if (readPreference() === "system") applyPreference("system");
  });
})();
