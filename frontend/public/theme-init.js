// Applies the saved theme before the first paint (a separate file: the CSP forbids inline scripts).
(function () {
  var pref = "system";
  try { pref = localStorage.getItem("sv:theme") || "system"; } catch (e) { /* storage blocked */ }
  var dark = pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
})();
