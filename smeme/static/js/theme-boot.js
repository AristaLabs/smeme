/* Early FOUC theme boot. Must load first, synchronously (no defer), before any
   paint — sets html[data-theme-pref] / .dark before CSS applies. See theme-toggle.js
   for the click-to-cycle behavior wired up after the DOM is ready. */
(function () {
  var root = document.documentElement;
  if (root.getAttribute("data-theme-pin") === "light") {
    root.classList.remove("dark");
    root.setAttribute("data-theme-pref", "light");
    return;
  }
  var match = document.cookie.match(/(?:^|; )smeme_theme=([^;]*)/);
  var pref = match ? decodeURIComponent(match[1]).trim().toLowerCase() : "system";
  if (pref !== "light" && pref !== "dark" && pref !== "system") pref = "system";
  root.setAttribute("data-theme-pref", pref);
  var dark =
    pref === "dark" ||
    (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.classList.toggle("dark", dark);
})();
