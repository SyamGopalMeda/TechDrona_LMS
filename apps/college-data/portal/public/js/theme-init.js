// Resolve the theme before first paint (saved choice, else the system preference). External file so a strict CSP
// (script-src 'self') does not block it. Loaded synchronously from <head>.
(function () {
  var t = null;
  try { t = new URLSearchParams(location.search).get('theme') || localStorage.getItem('td.theme'); } catch (e) { /* storage blocked */ }
  if (t !== 'light' && t !== 'dark') t = window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', t);
})();
