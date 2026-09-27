// Recipe page: favorite toggle without a reload, and the "Add to plan" panel.
(function () {
  const favForm = document.getElementById("fav-form");
  if (favForm) {
    favForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = favForm.querySelector("input[name=favorite]");
      const button = favForm.querySelector("button");
      try {
        const res = await fetch(favForm.action, {
          method: "POST",
          body: new FormData(favForm),
          headers: { Accept: "application/json" },
        });
        if (res.status === 401) { location.reload(); return; }
        const { favorite } = await res.json();
        input.value = favorite ? "0" : "1";
        button.classList.toggle("on", favorite);
        button.setAttribute("aria-pressed", String(favorite));
        button.querySelector(".star").textContent = favorite ? "★" : "☆";
      } catch {
        favForm.submit();
      }
    });
  }

  const toggle = document.getElementById("plan-toggle");
  const panel = document.getElementById("plan-panel");
  if (toggle && panel) {
    toggle.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      toggle.setAttribute("aria-expanded", String(!panel.hidden));
      if (!panel.hidden) panel.querySelector("select").focus();
    });
  }
})();
