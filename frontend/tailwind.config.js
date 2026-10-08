/** @type {import('tailwindcss').Config} */
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class", // set by public/theme-init.js and the theme switcher (light / dark / system)
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        subtle: token("subtle"),
        line: token("line"),
        ink: token("ink"),
        muted: token("muted"),
        accent: token("accent"),
        link: token("link"),
      },
    },
  },
  plugins: [],
};
