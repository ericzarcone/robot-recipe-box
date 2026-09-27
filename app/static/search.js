// Live search: update the results as you type, without a full page load.
(function () {
  const form = document.getElementById("search-form");
  const input = document.getElementById("search-input");
  const results = document.getElementById("results");
  if (!form || !input || !results) return;

  let timer = null;
  let controller = null;

  function params() {
    const p = new URLSearchParams(new FormData(form));
    if (!p.get("q")) p.delete("q");
    return p;
  }

  async function run() {
    const p = params();
    if (controller) controller.abort();
    controller = new AbortController();
    try {
      const res = await fetch(`/search?${p}`, { signal: controller.signal, headers: { "X-Requested-With": "fetch" } });
      if (res.status === 401) { location.reload(); return; }
      if (!res.ok) return;
      results.innerHTML = await res.text();
      const qs = p.toString();
      history.replaceState(null, "", qs ? `/?${qs}` : "/");
      // Keep the category chips pointing at the current query.
      document.querySelectorAll(".chips a.chip").forEach((a) => {
        const url = new URL(a.href);
        if (p.get("q")) url.searchParams.set("q", p.get("q")); else url.searchParams.delete("q");
        a.href = url.pathname + url.search;
      });
    } catch (err) {
      if (err.name !== "AbortError") console.error(err);
    }
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(run, 200);
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    clearTimeout(timer);
    input.blur(); // close the phone keyboard
    run();
  });
})();
