(function () {
  try {
    var saved = localStorage.getItem('cheshire.theme');
    var dark =
      saved === 'dark' ||
      ((!saved || saved === 'system') && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  } catch (e) {}
})();
