/* Clerk browser sync: dev URL-based session (__clerk_db_jwt) + prod callback
   cookie sync. Loaded only when partials/_clerk_browser_sync.html renders
   (request.state.clerk_browser_sync). The two Clerk vendor <script src>
   tags stay inline in that template — this file is the boot logic that used
   to run inline. Any per-page config is read from data-* attributes instead
   of being templated directly into JS (see clerk_callback_sync.html). */

// login.html / register.html buttons: <button data-clerk-action="sign-in|sign-up"
// data-clerk-fallback-url="..."> — opens the Clerk modal helper if it's ready
// (set below once Clerk.load() resolves), else falls back to the hosted URL.
// Registered immediately (not inside the "load" listener) so early clicks
// still work via the fallback URL.
document.body.addEventListener("click", function (event) {
  var target = event.target.closest("[data-clerk-action]");
  if (!target) return;
  event.preventDefault();
  var action = target.getAttribute("data-clerk-action");
  var fallbackUrl = target.getAttribute("data-clerk-fallback-url") || "";
  if (action === "sign-in") {
    if (window.__clerkOpenSignIn) window.__clerkOpenSignIn();
    else if (fallbackUrl) window.location.href = fallbackUrl;
  } else if (action === "sign-up") {
    if (window.__clerkOpenSignUp) window.__clerkOpenSignUp();
    else if (fallbackUrl) window.location.href = fallbackUrl;
  }
});

window.addEventListener("load", async function () {
  if (typeof Clerk === "undefined") return;
  try {
    // The callback always returns to this Core instance.
    await Clerk.load({
      ui: { ClerkUI: window.__internal_ClerkUICtor },
      allowedRedirectOrigins: [
        window.location.origin,
        "http://localhost:8000",
        "http://localhost:3000",
      ],
    });
  } catch (e) {
    console.error("Clerk.load failed", e);
    return;
  }
  var u = new URL(window.location.href);
  var callbackUrl = window.location.origin + "/auth/clerk-callback";

  // Defined early — needed by both the Google OAuth landing check and the modal helpers.
  function showSigningInOverlay() {
    var overlay = document.createElement("div");
    overlay.id = "clerk-signing-in-overlay";
    overlay.style.cssText = [
      "position:fixed",
      "inset:0",
      "z-index:9999",
      "background:rgba(255,255,255,0.85)",
      "display:flex",
      "align-items:center",
      "justify-content:center",
      "flex-direction:column",
      "gap:0.75rem",
    ].join(";");
    overlay.innerHTML =
      '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#002868" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="animation:clerk-spin 0.8s linear infinite"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>' +
      '<p style="margin:0;font-size:0.95rem;font-weight:500;color:#00163d">Signing you in\u2026</p>' +
      "<style>@keyframes clerk-spin{to{transform:rotate(360deg)}}</style>";
    document.body.appendChild(overlay);
  }

  // Logout: server cleared cookies and redirected here with smeme_clerk_logout=1.
  // We must also call Clerk.signOut() client-side so Clerk's own storage (IndexedDB /
  // localStorage) is invalidated — otherwise clerk-js re-hydrates the session on the
  // next page load and the user appears still signed in.
  if (u.searchParams.get("smeme_clerk_logout") === "1") {
    try {
      if (typeof Clerk.signOut === "function") {
        await Clerk.signOut({ redirectUrl: u.origin + "/auth/login" });
      }
    } catch (e2) {
      console.error("Clerk.signOut after server logout failed", e2);
    }
    u.searchParams.delete("smeme_clerk_logout");
    var qs0 = u.searchParams.toString();
    window.history.replaceState({}, "", u.pathname + (qs0 ? "?" + qs0 : "") + u.hash);
  }

  // Google / social OAuth landing: a full-page OAuth redirect tears down the JS
  // context, so withSigningInOverlay's addListener never fires.  Clerk may also
  // ignore forceRedirectUrl and send the user back to /auth/login instead of
  // /auth/clerk-callback (depends on Dashboard "After Sign-In URL" config).
  // After Clerk.load() above, Clerk.session is populated if the session is live.
  // Detect that here and fast-redirect to the callback, showing the overlay to mask
  // the login-page flash, rather than waiting for the server pre-check (~2 s).
  if (
    window.location.pathname === "/auth/login" &&
    !u.searchParams.get("smeme_clerk_logout") &&
    !u.searchParams.get("clerk_sync_failed") &&
    Clerk.session
  ) {
    showSigningInOverlay();
    window.location.assign(callbackUrl);
    return;
  }

  // Callback sync: client-side Clerk.session can exist before the __session cookie
  // is readable by the server (common with custom FAPI domains on production).
  // Only the dedicated sync page opts in via [data-clerk-callback-needs-cookie-sync].
  // Running this on clerk_provision_blocked (or any other callback HTML) would
  // overwrite the clear gate error with /auth/login?clerk_sync_failed=1.
  var needsCookieSync = !!document.querySelector("[data-clerk-callback-needs-cookie-sync]");
  if (window.location.pathname === "/auth/clerk-callback" && needsCookieSync) {
    if (!Clerk.session) {
      window.location.assign("/auth/login");
      return;
    }
    var syncKey = "clerk_callback_sync_attempted";
    if (!sessionStorage.getItem(syncKey)) {
      sessionStorage.setItem(syncKey, "1");
      showSigningInOverlay();
      try {
        await Clerk.session.getToken();
      } catch (syncErr) {
        console.error("Clerk callback cookie sync failed", syncErr);
      }
      window.location.replace(callbackUrl);
      return;
    }
    sessionStorage.removeItem(syncKey);
    window.location.assign("/auth/login?clerk_sync_failed=1");
    return;
  }

  // Modal helpers: used by login.html / register.html buttons so sign-in stays
  // on the SMEme page (no Account Portal cross-domain redirect_url issues).
  function withSigningInOverlay(openFn) {
    var unsubscribe = Clerk.addListener(function (resources) {
      if (resources.session) {
        unsubscribe();
        showSigningInOverlay();
      }
    });
    openFn();
  }

  window.__clerkOpenSignIn = function () {
    if (typeof Clerk !== "undefined" && Clerk.openSignIn) {
      withSigningInOverlay(function () {
        Clerk.openSignIn({
          forceRedirectUrl: callbackUrl,
          afterSignInUrl: callbackUrl,
          afterSignUpUrl: callbackUrl,
        });
      });
    } else {
      window.location.href = callbackUrl;
    }
  };
  window.__clerkOpenSignUp = function () {
    if (typeof Clerk !== "undefined" && Clerk.openSignUp) {
      withSigningInOverlay(function () {
        Clerk.openSignUp({
          forceRedirectUrl: callbackUrl,
          afterSignInUrl: callbackUrl,
          afterSignUpUrl: callbackUrl,
        });
      });
    } else {
      window.location.href = callbackUrl;
    }
  };

  // Fallback: if Clerk.load() didn't synchronously set Clerk.session from
  // __clerk_db_jwt (some clerk-js builds), the session check above is skipped.
  // Clean up __clerk_* params and reload so the next load catches the session.
  var after = u.searchParams.get("clerk_after");
  var keys = Array.from(u.searchParams.keys());
  var hadClerkQuery = keys.some(function (k) {
    return k.startsWith("__clerk");
  });
  keys.forEach(function (k) {
    if (k.startsWith("__clerk")) {
      u.searchParams.delete(k);
    }
  });
  u.searchParams.delete("clerk_after");
  if (hadClerkQuery || after) {
    if (after && after.startsWith("/") && !after.startsWith("//") && after.length < 2048) {
      window.location.assign(after);
    } else {
      var qs = u.searchParams.toString();
      window.history.replaceState({}, "", u.pathname + (qs ? "?" + qs : "") + u.hash);
      window.location.reload();
    }
  }
});
