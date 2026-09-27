// Cooking mode: keep the screen awake, bigger text, tap to check off ingredients and steps.
(function () {
  const recipe = document.getElementById("recipe");
  if (!recipe) return;
  const body = document.body;
  const toggle = document.getElementById("cook-toggle");
  const bar = document.getElementById("cookbar");
  const status = document.getElementById("wake-status");
  const video = document.getElementById("nosleep-video");
  const KEY = `cook:${recipe.dataset.slug}`;
  const steps = Array.from(recipe.querySelectorAll(".step"));
  const ingredients = Array.from(recipe.querySelectorAll(".ingredient"));

  let cooking = false;
  let lock = null;
  let usingVideo = false;
  let requesting = false;
  let state = load();

  function load() {
    try {
      return JSON.parse(sessionStorage.getItem(KEY)) || { on: false, done: [], current: null };
    } catch {
      return { on: false, done: [], current: null };
    }
  }

  function save() {
    try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch { /* private mode */ }
  }

  function setStatus(on, text) {
    status.textContent = text;
    status.classList.toggle("on", on);
  }

  async function keepAwake() {
    if (!cooking || requesting || lock || usingVideo) return;
    requesting = true;
    try {
      await requestAwake();
    } finally {
      requesting = false;
    }
    // stop() may have run while the request was in flight.
    if (!cooking) letSleep();
  }

  async function requestAwake() {
    if ("wakeLock" in navigator) {
      try {
        lock = await navigator.wakeLock.request("screen");
        lock.addEventListener("release", () => {
          lock = null;
          if (cooking) setStatus(false, "Screen may sleep. Tap to keep it on.");
        });
        setStatus(true, "Screen stays on");
        return;
      } catch { /* not allowed right now; try the video fallback */ }
    }
    try {
      await video.play();
      usingVideo = true;
      setStatus(true, "Screen stays on");
    } catch {
      setStatus(false, "Tap to keep the screen on");
    }
  }

  function letSleep() {
    if (lock) lock.release().catch(() => {});
    lock = null;
    if (usingVideo) video.pause();
    usingVideo = false;
  }

  function render() {
    const done = new Set(state.done);
    ingredients.forEach((el) => el.classList.toggle("done", done.has(el.dataset.key)));
    const currentIndex = steps.findIndex((el) => el.dataset.key === state.current);
    steps.forEach((el, i) => {
      el.classList.toggle("current", cooking && i === currentIndex);
      el.classList.toggle("done", done.has(el.dataset.key));
    });
  }

  function start() {
    cooking = true;
    state.on = true;
    if (!state.current && steps.length) state.current = steps[0].dataset.key;
    body.classList.add("cooking");
    bar.hidden = false;
    toggle.textContent = "Cooking…";
    toggle.setAttribute("aria-pressed", "true");
    setStatus(false, "Keeping screen on…");
    keepAwake();
    save();
    render();
  }

  function stop() {
    cooking = false;
    state.on = false;
    body.classList.remove("cooking");
    bar.hidden = true;
    toggle.textContent = "Start cooking";
    toggle.setAttribute("aria-pressed", "false");
    letSleep();
    save();
    render();
  }

  function toggleDone(key) {
    const done = new Set(state.done);
    done.has(key) ? done.delete(key) : done.add(key);
    state.done = Array.from(done);
  }

  function onStepTap(el) {
    const i = steps.indexOf(el);
    if (el.dataset.key === state.current) {
      // Tapping the current step finishes it and moves on.
      toggleDone(el.dataset.key);
      const next = steps.slice(i + 1).find((s) => !state.done.includes(s.dataset.key));
      state.current = next ? next.dataset.key : null;
      if (next) next.scrollIntoView({ behavior: "smooth", block: "center" });
    } else {
      state.current = el.dataset.key;
    }
  }

  toggle.addEventListener("click", () => (cooking ? stop() : start()));
  document.getElementById("cook-exit").addEventListener("click", stop);
  document.getElementById("cook-reset").addEventListener("click", () => {
    state.done = [];
    state.current = steps.length ? steps[0].dataset.key : null;
    save();
    render();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  recipe.addEventListener("click", (e) => {
    if (!cooking) return;
    const ingredient = e.target.closest(".ingredient");
    const step = e.target.closest(".step");
    if (ingredient) toggleDone(ingredient.dataset.key);
    else if (step) onStepTap(step);
    else return;
    save();
    render();
  });

  // A tap anywhere retries when the browser needed a user gesture.
  document.addEventListener("click", () => keepAwake());

  // iOS and Android drop the wake lock when the page is hidden. Take it again on return.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") keepAwake();
  });

  if (state.on) start();
  else render();
})();
