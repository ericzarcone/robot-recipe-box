// Grocery list: save check-offs as you shop, and share or copy what is left.
(function () {
  const list = document.getElementById("grocery");
  const remaining = document.getElementById("remaining");
  const shareBtn = document.getElementById("share-list");
  const copyBtn = document.getElementById("copy-list");
  const status = document.getElementById("copy-status");
  const title = document.querySelector("h1").textContent + " · " + document.querySelector(".crumbs a").textContent;

  function boxes() {
    return list ? Array.from(list.querySelectorAll("input[type=checkbox]")) : [];
  }

  function updateRemaining() {
    const left = boxes().filter((b) => !b.checked).length;
    remaining.textContent = boxes().length ? `${left} left to get.` : "";
  }

  function listText() {
    const blocks = [];
    list.querySelectorAll(".aisle").forEach((aisle) => {
      const lines = Array.from(aisle.querySelectorAll("input:not(:checked)")).map((b) => `- ${b.dataset.line}`);
      if (lines.length) blocks.push([aisle.querySelector("h2").textContent, ...lines].join("\n"));
    });
    return blocks.join("\n\n");
  }

  function flash(text) {
    status.textContent = text;
    status.hidden = false;
    setTimeout(() => { status.hidden = true; }, 2500);
  }

  if (list) {
    list.addEventListener("change", async (e) => {
      const box = e.target;
      if (!box.matches("input[type=checkbox]")) return;
      updateRemaining();
      try {
        const res = await fetch(`/plans/${list.dataset.plan}/grocery/check`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: box.dataset.key, checked: box.checked }),
        });
        if (!res.ok) throw new Error(res.status);
      } catch {
        box.checked = !box.checked; // put it back so the page matches what is saved
        updateRemaining();
        flash("Could not save that. Check your connection.");
      }
    });
    updateRemaining();
  }

  if (navigator.share) {
    shareBtn.hidden = false;
    shareBtn.addEventListener("click", () => {
      navigator.share({ title, text: listText() }).catch(() => {});
    });
  }
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(listText());
      flash("Copied the items you still need.");
    } catch {
      flash("Copy is not available here.");
    }
  });
})();
