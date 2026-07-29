/* Attach the CSRF token to every HTMX request header. Mirrors the cookie set
   by CsrfProtectionMiddleware, falling back to the <meta name="csrf-token">
   tag rendered in base.html head. */
document.addEventListener("htmx:configRequest", function (event) {
  var match = document.cookie.match(/(?:^|; )smeme_csrf=([^;]*)/);
  var token = match ? decodeURIComponent(match[1]) : "";
  if (!token) {
    var meta = document.querySelector('meta[name="csrf-token"]');
    token = meta ? meta.getAttribute("content") || "" : "";
  }
  if (token) event.detail.headers["X-CSRF-Token"] = token;
});
