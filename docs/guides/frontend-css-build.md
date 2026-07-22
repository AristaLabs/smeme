# Frontend CSS Build (Tailwind, pre-built)

How SMEme's CSS is produced and served. The app uses **Tailwind CSS pre-built to a static,
purged stylesheet** — not the Play CDN. Rationale and alternatives:
pre-built Tailwind over the Play CDN.

> **TL;DR** — After you add or change Tailwind classes in a template, run **`make css`**.
> Production rebuilds automatically in the Docker build. No npm or Node is involved.

---

## Why pre-built (not the CDN)

The Play CDN (`cdn.tailwindcss.com`) ships a large JS runtime and compiles CSS in the browser on
every page load — it is explicitly not for production and hurts LCP/CLS (a Core Web Vitals ranking
and conversion signal). We compile ahead of time to a small purged stylesheet instead.

| | Before (Play CDN) | After (pre-built) |
|---|---|---|
| Payload | ~400 KB+ JS, runtime compile | `app.css` ~13 KB gzipped |
| Render | JS must run → FOUC/CLS risk | one render-blocking `<link>` |
| Config | inline in `base.html` | `tailwind.config.js` |
| Node/npm | none | none (standalone binary) |

---

## Files

| Path | Role |
|---|---|
| `tailwind.config.js` | Theme (brand/ui colors, fonts, shadows), `content` globs, `darkMode: "class"`, `safelist`. |
| `tailwind.input.css` | `@tailwind` directives + `--ui-*` design tokens + custom base/component CSS. |
| `scripts/build_css.sh` | Downloads the pinned standalone Tailwind CLI and compiles the stylesheet. |
| `smeme/static/css/app.css` | **Generated + committed** output, served at `/static/css/app.css`. |
| `smeme/templates/layouts/base.html` | Links the stylesheet: `<link rel="stylesheet" href="/static/css/app.css">`. |
| `.cache/tailwind/` | Cached CLI binary (git-ignored). |

---

## Build commands

```bash
make css          # one-off build  → smeme/static/css/app.css (minified)
make css-watch    # rebuild on change during local dev
bash scripts/build_css.sh          # same as `make css`
TAILWIND_VERSION=v3.4.17 make css  # override the pinned CLI version
```

`build_css.sh` downloads the correct standalone binary for your OS/arch
(`linux`/`macos`, `x64`/`arm64`) into `.cache/tailwind/` on first run, then reuses it.

---

## When to rebuild

Rebuild whenever the set of Tailwind classes used in templates changes:

- Added/removed a utility class in any `smeme/templates/**/*.html`.
- Added a new template or macro variant.
- Changed the theme in `tailwind.config.js` or anything in `tailwind.input.css`.

The committed `app.css` exists so local dev, tests, and non-Docker runs work without a build; it
can drift from the templates until you run `make css`. **Production is always fresh** — the Docker
builder stage runs the build and copies the result into the runtime image.

---

## How it ships (Docker)

`Dockerfile` builder stage:

```dockerfile
COPY tailwind.config.js tailwind.input.css ./
COPY smeme/templates ./smeme/templates
COPY scripts/build_css.sh ./scripts/
RUN bash scripts/build_css.sh
```

Runtime stage (authoritative over any committed copy):

```dockerfile
COPY --from=builder --chown=appuser:appuser /app/smeme/static/css/app.css ./smeme/static/css/app.css
```

The build needs network access (to fetch the CLI binary) — available during Docker build and in CI.

---

## Gotchas

- **Purge safety.** Tailwind scans raw template text, so classes must appear as **complete string
  literals** (including in inline JS: `classList.add("bg-amber-50")` is fine). Never build class
  names by concatenation (`"bg-" + color`) — those won't be detected. Classes toggled only in JS
  are also listed in `safelist` in `tailwind.config.js` as a backstop; add to it if you introduce
  new JS-only toggles.
- **`--ui-*` opacity modifiers don't work.** `ui.*` colors are `var(--ui-*)` values, so modifiers
  like `bg-ui-surface/10` can't inject alpha (same limitation as under the CDN). Use an explicit
  color or set the value in `tailwind.input.css`.
- **Tailwind v3.** Config uses the v3 `tailwind.config.js` + `theme.extend` format. A v4 upgrade
  (CSS-first config) is a separate migration.
- **Dark mode** is class-based (`html.dark`), toggled by the inline theme script in `base.html`
  (kept as-is — it must run before paint to avoid a flash).

---

## Related

- This guide — pre-built Tailwind over the Play CDN
- Templates under `smeme/templates/` — `--ui-*` tokens and macros
