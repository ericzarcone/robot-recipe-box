// Small behaviors shared by every page. Kept out of inline attributes so the CSP can forbid inline script.
(function () {
  document.addEventListener("submit", (e) => {
    const message = e.target.dataset && e.target.dataset.confirm;
    if (message && !window.confirm(message)) e.preventDefault();
  }, true);
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-print]")) window.print();
  });
})();
