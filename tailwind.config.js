/**
 * Tailwind v3 config for the pre-built, purged production stylesheet.
 *
 * This replaces the Play CDN (cdn.tailwindcss.com), which shipped a large JS
 * runtime and compiled CSS in the browser (hurting LCP/CLS). The theme below is
 * the exact `tailwind.config` that previously lived inline in layouts/base.html.
 *
 * Build:  scripts/build_css.sh  ->  smeme/static/css/app.css   (also `make css`)
 * Content scanning reads raw template text, so classes written as complete string
 * literals in inline JS (e.g. classList.add("bg-amber-50")) are picked up. The
 * `safelist` below is belt-and-suspenders for the handful toggled dynamically.
 */
module.exports = {
  content: ["./smeme/templates/**/*.html"],
  darkMode: "class",
  safelist: [
    // Toggled at runtime by inline JS (plugin update strip, generation counters,
    // expert tabs) — kept explicit so a scanner miss can never drop them.
    "hidden",
    "font-semibold",
    "-mb-px",
    "border-b-2",
    "border-brand-600",
    "text-brand-600",
    "text-ui-ink",
    "text-ui-ink-muted",
    "text-red-600",
    "text-yellow-600",
    "bg-ui-surface",
    "bg-amber-50",
    "text-amber-950",
    "ring-2",
    "ring-inset",
    "hover:bg-ui-surface-hover",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
      },
      colors: {
        brand: {
          50: "#eff4fc",
          100: "#d9e4f5",
          200: "#b3caea",
          300: "#7d9fd4",
          400: "#4a76b0",
          500: "#2d5a94",
          600: "#002868",
          700: "#001f50",
          800: "#00163d",
          900: "#000d26",
        },
        success: {
          50: "#f0fdf4",
          100: "#dcfce7",
          200: "#bbf7d0",
          300: "#86efac",
          400: "#4ade80",
          500: "#22c55e",
          600: "#16a34a",
          700: "#15803d",
          800: "#166534",
          900: "#14532d",
          950: "#052e16",
        },
        warning: {
          50: "#fffbeb",
          100: "#fef3c7",
          200: "#fde68a",
          300: "#fcd34d",
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
          800: "#92400e",
          900: "#78350f",
          950: "#451a03",
        },
        danger: {
          50: "#fef2f2",
          100: "#fee2e2",
          200: "#fecaca",
          300: "#fca5a5",
          400: "#f87171",
          500: "#ef4444",
          600: "#dc2626",
          700: "#b91c1c",
          800: "#991b1b",
          900: "#7f1d1d",
          950: "#450a0a",
        },
        info: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",
          900: "#1e3a8a",
          950: "#172554",
        },
        ui: {
          canvas: "var(--ui-canvas)",
          ink: {
            DEFAULT: "var(--ui-ink)",
            secondary: "var(--ui-ink-secondary)",
            muted: "var(--ui-ink-muted)",
            subtle: "var(--ui-ink-subtle)",
          },
          surface: {
            DEFAULT: "var(--ui-surface)",
            muted: "var(--ui-surface-muted)",
            hover: "var(--ui-surface-hover)",
          },
          line: {
            DEFAULT: "var(--ui-line)",
            strong: "var(--ui-line-strong)",
          },
        },
      },
      boxShadow: {
        card: "0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)",
        "card-hover":
          "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
      },
    },
  },
};
