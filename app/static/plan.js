// Meal plan page: the recipe picker (for the whole plan or one day), drag and drop between days,
// and saving day/servings changes right away.
(function () {
  const week = document.getElementById("week");
  const picker = document.getElementById("picker");
  const pickerFor = document.getElementById("picker-for");
  const input = document.getElementById("picker-q");
  const results = document.getElementById("picker-results");
  const topToggle = document.getElementById("picker-toggle");
  if (!week || !picker) return;
  const planId = week.dataset.plan;
  const home = { parent: picker.parentNode, next: picker.nextSibling }; // where the picker lives for "Add recipes"
  const REOPEN_KEY = "picker-open";

  // ---------- picker ----------

  let pickerDay = null; // null = closed, "" = any day, "0".."6" = that weekday
  let timer = null;

  async function loadPicker() {
    const params = new URLSearchParams({ q: input.value.trim(), day: pickerDay || "" });
    const res = await fetch(`/plans/${planId}/picker?${params}`);
    if (res.status === 401) { location.reload(); return; }
    if (res.ok) results.innerHTML = await res.text();
  }

  function openPicker(day, dayName) {
    pickerDay = day;
    const section = day === null ? null : week.querySelector(`.day[data-day="${day}"]`);
    if (section && dayName) {
      section.append(picker); // show the picker inside that day
      pickerFor.textContent = `Adding to ${dayName}`;
      pickerFor.hidden = false;
    } else {
      home.parent.insertBefore(picker, home.next);
      pickerFor.hidden = true;
    }
    picker.hidden = false;
    topToggle.setAttribute("aria-expanded", String(!section));
    week.querySelectorAll(".day-add").forEach((b) => b.setAttribute("aria-expanded", String(b.dataset.day === day && !!section)));
    input.focus({ preventScroll: true });
    picker.scrollIntoView({ behavior: "smooth", block: "nearest" });
    loadPicker();
  }

  function closePicker() {
    pickerDay = null;
    picker.hidden = true;
    topToggle.setAttribute("aria-expanded", "false");
    week.querySelectorAll(".day-add").forEach((b) => b.setAttribute("aria-expanded", "false"));
  }

  topToggle.addEventListener("click", () => {
    const openHere = !picker.hidden && pickerFor.hidden;
    openHere ? closePicker() : openPicker("", null);
  });

  week.addEventListener("click", (e) => {
    const add = e.target.closest(".day-add");
    if (!add) return;
    const openHere = !picker.hidden && pickerDay === add.dataset.day && !pickerFor.hidden;
    openHere ? closePicker() : openPicker(add.dataset.day, add.dataset.dayName);
  });

  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(loadPicker, 200);
  });

  // After adding, the page reloads. Reopen the picker where it was, so several recipes can go in a row.
  results.addEventListener("submit", () => {
    const where = pickerFor.hidden ? { day: "", name: null } : { day: pickerDay, name: pickerFor.textContent.replace("Adding to ", "") };
    try { sessionStorage.setItem(REOPEN_KEY, JSON.stringify({ plan: planId, ...where })); } catch { /* private mode */ }
  });
  try {
    const saved = JSON.parse(sessionStorage.getItem(REOPEN_KEY) || "null");
    sessionStorage.removeItem(REOPEN_KEY);
    if (saved && saved.plan === planId) openPicker(saved.day, saved.name);
  } catch { /* ignore bad or blocked storage */ }

  // ---------- save day and servings edits right away ----------

  document.querySelectorAll("form.autosubmit").forEach((form) => {
    form.querySelectorAll("select, input").forEach((el) => el.addEventListener("change", () => form.requestSubmit()));
  });

  // ---------- drag and drop between days ----------
  // Pointer Events, not the HTML drag and drop API: one code path for mouse and touch, and it works on iPhone.

  const EDGE = 70; // px from the top or bottom of the window where dragging scrolls the page
  const MAX_SPEED = 18; // px per frame
  let drag = null;

  function dayAt(x, y) {
    const el = document.elementFromPoint(x, y);
    return el ? el.closest(".day") : null;
  }

  function setTarget(section) {
    if (drag.target === section) return;
    if (drag.target) drag.target.classList.remove("drop-target");
    drag.target = section && section !== drag.from ? section : null;
    if (drag.target) drag.target.classList.add("drop-target");
  }

  function position() {
    drag.ghost.style.transform = `translate(${drag.x - drag.dx}px, ${drag.y - drag.dy}px)`;
    setTarget(dayAt(drag.x, drag.y));
  }

  function autoscroll() {
    if (!drag) return;
    let speed = 0;
    if (drag.y < EDGE) speed = -MAX_SPEED * (1 - drag.y / EDGE);
    else if (drag.y > window.innerHeight - EDGE) speed = MAX_SPEED * (1 - (window.innerHeight - drag.y) / EDGE);
    if (speed) {
      window.scrollBy(0, speed);
      position(); // the day under a still pointer changes while the page scrolls
    }
    drag.frame = requestAnimationFrame(autoscroll);
  }

  function endDrag() {
    cancelAnimationFrame(drag.frame);
    drag.ghost.remove();
    drag.item.classList.remove("dragging");
    if (drag.target) drag.target.classList.remove("drop-target");
    document.body.classList.remove("is-dragging");
    const done = drag;
    drag = null;
    return done;
  }

  // Put the item where the server will list it after a reload: day order, then the order it was added.
  function placeIn(section, item) {
    const list = section.querySelector(".day-items");
    const id = Number(item.dataset.item);
    const after = Array.from(list.children).find((el) => Number(el.dataset.item) > id);
    list.insertBefore(item, after || null);
  }

  async function drop(done) {
    const { item, from, target } = done;
    if (!target) return;
    const day = target.dataset.day === "" ? null : Number(target.dataset.day);
    placeIn(target, item); // move now, undo if the save fails
    const select = item.querySelector("select[name=day]");
    const previous = select.value;
    select.value = day === null ? "" : String(day);
    item.classList.add("just-moved");
    setTimeout(() => item.classList.remove("just-moved"), 900);
    try {
      const res = await fetch(`/plans/${planId}/items/${item.dataset.item}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ day }),
      });
      if (res.status === 401) { location.reload(); return; }
      if (!res.ok) throw new Error(String(res.status));
    } catch {
      placeIn(from, item);
      select.value = previous;
      window.alert("Could not move that recipe. Check your connection and try again.");
    }
  }

  week.addEventListener("pointerdown", (e) => {
    const handle = e.target.closest(".drag-handle");
    if (!handle || drag || (e.pointerType === "mouse" && e.button !== 0)) return;
    e.preventDefault();
    const item = handle.closest(".plan-item");
    const rect = item.getBoundingClientRect();
    const ghost = item.cloneNode(true);
    ghost.classList.add("drag-ghost");
    ghost.removeAttribute("id");
    ghost.setAttribute("aria-hidden", "true");
    ghost.style.width = `${rect.width}px`;
    document.body.append(ghost);
    item.classList.add("dragging");
    document.body.classList.add("is-dragging");
    handle.setPointerCapture(e.pointerId);
    drag = {
      item, ghost, handle, pointerId: e.pointerId, from: item.closest(".day"), target: null,
      x: e.clientX, y: e.clientY, dx: e.clientX - rect.left, dy: e.clientY - rect.top, frame: 0,
    };
    position();
    drag.frame = requestAnimationFrame(autoscroll);
  });

  week.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.pointerId) return;
    drag.x = e.clientX;
    drag.y = e.clientY;
    position();
  });

  week.addEventListener("pointerup", (e) => {
    if (!drag || e.pointerId !== drag.pointerId) return;
    drop(endDrag());
  });

  week.addEventListener("pointercancel", (e) => {
    if (drag && e.pointerId === drag.pointerId) endDrag();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drag) endDrag();
  });
})();
