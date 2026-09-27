// Shrink the sheet's font size until the recipe fits on one US Letter page, then print if asked.
(function () {
  const PX_PER_IN = 96;
  const LIMIT = 10 * PX_PER_IN; // 11in page minus 0.5in top and bottom margins
  const MAX_PT = 12.5;
  const MIN_PT = 7.5;
  const STEP_PT = 0.25;

  const sheet = document.getElementById("sheet");
  const page = document.getElementById("page");
  const viewport = document.getElementById("viewport");
  const status = document.getElementById("fit-status");

  function fit() {
    let size = MAX_PT;
    sheet.style.setProperty("--fs", size + "pt");
    while (sheet.scrollHeight > LIMIT && size > MIN_PT) {
      size -= STEP_PT;
      sheet.style.setProperty("--fs", size + "pt");
    }
    const fits = sheet.scrollHeight <= LIMIT;
    status.textContent = fits ? "Fits on one page" : "Too long for one page, prints on 2";
    status.classList.toggle("over", !fits);
    return fits;
  }

  // Scale the on-screen page preview down to the window width (phones). Printing ignores this.
  function preview() {
    const available = viewport.clientWidth - 32;
    const scale = Math.min(1, available / (8.5 * PX_PER_IN));
    page.style.transform = scale < 1 ? `scale(${scale})` : "";
    page.style.marginLeft = scale < 1 ? "0" : "";
    viewport.style.height = scale < 1 ? `${11 * PX_PER_IN * scale + 32}px` : "";
  }

  document.getElementById("print-btn").addEventListener("click", () => window.print());
  window.addEventListener("resize", preview);

  const ready = document.fonts ? document.fonts.ready : Promise.resolve();
  ready.then(() => {
    fit();
    preview();
    if (document.body.hasAttribute("data-autoprint")) {
      // Drop ?autoprint from the URL so Back/refresh does not open the dialog again.
      history.replaceState(null, "", location.pathname);
      setTimeout(() => window.print(), 250);
    }
  });
})();
