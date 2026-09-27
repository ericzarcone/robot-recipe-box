// Meal plan page: recipe picker with live search, and save day/servings changes right away.
(function () {
  const toggle = document.getElementById("picker-toggle");
  const picker = document.getElementById("picker");
  const input = document.getElementById("picker-q");
  const results = document.getElementById("picker-results");
  let timer = null;
  let loaded = false;

  async function load() {
    const url = `/plans/${picker.dataset.plan}/picker?q=${encodeURIComponent(input.value.trim())}`;
    const res = await fetch(url);
    if (res.status === 401) { location.reload(); return; }
    if (res.ok) results.innerHTML = await res.text();
  }

  if (toggle && picker) {
    toggle.addEventListener("click", () => {
      picker.hidden = !picker.hidden;
      toggle.setAttribute("aria-expanded", String(!picker.hidden));
      if (!picker.hidden) {
        input.focus();
        if (!loaded) { loaded = true; load(); }
      }
    });
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(load, 200);
    });
    // Reopen the picker after adding, so several recipes can be added in a row.
    if (sessionStorage.getItem("picker-open") === picker.dataset.plan) {
      sessionStorage.removeItem("picker-open");
      toggle.click();
    }
    results.addEventListener("submit", () => {
      try { sessionStorage.setItem("picker-open", picker.dataset.plan); } catch { /* private mode */ }
    });
  }

  document.querySelectorAll("form.autosubmit").forEach((form) => {
    form.querySelectorAll("select").forEach((el) => el.addEventListener("change", () => form.requestSubmit()));
    form.querySelectorAll("input").forEach((el) => el.addEventListener("change", () => form.requestSubmit()));
  });
})();
