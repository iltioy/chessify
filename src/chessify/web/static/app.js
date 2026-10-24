"use strict";

const CATEGORIES = {
  brilliant: { label: "Блестящий", color: "#26c2a3" },
  best: { label: "Лучший", color: "#81b64c" },
  excellent: { label: "Отличный", color: "#5fa83f" },
  good: { label: "Хороший", color: "#95b776" },
  inaccuracy: { label: "Неточность", color: "#f7c631" },
  mistake: { label: "Ошибка", color: "#ffa459" },
  blunder: { label: "Зевок", color: "#fa412d" },
};
const STATUS = {
  queued: "в очереди", processing: "анализ", choose: "выбор сцены", review: "проверка ходов",
  rendering: "рендер", done: "готово", error: "ошибка",
};
const ACTIVE = new Set(["queued", "processing", "rendering"]);

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, props = {}, ...children) => {
  const { dataset, ...rest } = props; // dataset только для чтения — заполняем по ключам
  const node = Object.assign(document.createElement(tag), rest);
  Object.assign(node.dataset, dataset || {});
  node.append(...children);
  return node;
};

let config = null;
let currentId = null;
let currentStatus = null;
let scene = null; // редактируемая сцена текущей задачи
let dirty = false;
let pollTimer = null;
let music = []; // библиотека треков
let candidatesLoadedFor = null;

const fmtTime = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const MODE_HINTS = {
  clip: "Готовый фрагмент со сценой-дуэлью.",
  episode: "Серия целиком: модель найдёт сцены-дуэли, вы выберете одну. Знаете границы — укажите начало и конец.",
};

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* не JSON */ }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

function fillSelect(select, options, value) {
  select.replaceChildren(...Object.entries(options).map(([k, v]) => el("option", { value: k, textContent: v })));
  if (value) select.value = value;
}

// ---------- новая задача ----------

async function loadConfig() {
  config = await api("/api/config");
  const form = $("#new-job");
  fillSelect(form.length, config.lengths, form.length.value || "full");
  fillSelect(form.preset, config.presets, form.preset.value || "final");
  const profiles = Object.fromEntries(Object.entries(config.profiles).map(([name, p]) =>
    [name, `${p.label}${p.missing_keys.some((k) => k !== "HF_TOKEN") ? " — не настроено" : ""}`]));
  fillSelect(form.profile, profiles, config.default_profile);
  showProfileWarning();
}

function setupForm() {
  const form = $("#new-job");
  form.profile.addEventListener("change", showProfileWarning);
  form.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", () => {
    $("#mode-hint").textContent = MODE_HINTS[form.mode.value];
  }));
}

async function loadMusic() {
  music = await api("/api/music");
  const options = { "": "Без музыки", ...Object.fromEntries(music.map((m) => [m, m])) };
  [$("#new-job").music, f("music")].filter(Boolean).forEach((sel) => fillSelect(sel, options, sel.value));
}

async function uploadMusic(ev) {
  const file = ev.target.files[0];
  if (!file) return;
  const data = new FormData();
  data.append("file", file);
  try {
    const { name } = await api("/api/music", { method: "POST", body: data });
    await loadMusic();
    $("#new-job").music.value = name;
  } catch (e) { alert(`Не удалось загрузить трек: ${e.message}`); }
  ev.target.value = "";
}

function showProfileWarning() {
  const form = $("#new-job");
  const profile = config.profiles[form.profile.value];
  const missing = profile.missing_keys;
  const warn = $("#profile-warn");
  const llm = profile.missing_labels.filter((_, i) => missing[i] !== "HF_TOKEN");
  const parts = [];
  if (llm.length) {
    parts.push(`${profile.label}: не хватает ключей (${llm.join("; ")}) — анализ не запустится.`);
  }
  if (missing.includes("HF_TOKEN")) parts.push("Нет HF_TOKEN: разметка спикеров пропустится, стороны модель определит по смыслу.");
  const open = el("button", { type: "button", textContent: "Открыть настройки" });
  open.addEventListener("click", () => openSettings(llm.length ? form.profile.value : "hf"));
  warn.replaceChildren(parts.join(" ") + " ", open);
  warn.hidden = parts.length === 0;
}

function setupDrop() {
  const drop = $("#drop");
  const input = drop.querySelector("input");
  const text = drop.querySelector(".file-text");
  const show = () => {
    const n = input.files.length;
    text.textContent = n === 0 ? "Перетащите видео сюда или выберите файлы"
      : n === 1 ? input.files[0].name : `${n} файлов — будет ${n} задач с одинаковыми настройками`;
  };
  input.addEventListener("change", show);
  ["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((e) => drop.addEventListener(e, () => drop.classList.remove("drag")));
  drop.addEventListener("drop", (ev) => {
    ev.preventDefault();
    if (ev.dataTransfer.files.length) { input.files = ev.dataTransfer.files; show(); }
  });
}

async function submitJob(ev) {
  ev.preventDefault();
  const form = ev.target;
  const files = [...form.video.files];
  const button = form.querySelector("button");
  button.disabled = true;
  let lastId = null;
  try {
    for (const [i, file] of files.entries()) {
      const data = new FormData();
      data.append("video", file);
      for (const name of ["series", "hint", "start", "end", "speakers", "profile", "length", "preset", "music", "music_volume", "mode"]) {
        if (form[name].value !== "") data.append(name, form[name].value);
      }
      data.append("review", form.review.checked ? "true" : "false");
      const prefix = files.length > 1 ? `Файл ${i + 1} из ${files.length}. ` : "";
      lastId = (await uploadOne(data, prefix)).id;
      refreshJobs();
    }
    form.video.value = "";
    form.video.dispatchEvent(new Event("change"));
    if (lastId) openJob(lastId);
  } catch (e) {
    alert(`Не удалось создать задачу: ${e.message}`);
  } finally {
    button.disabled = false;
    $("#upload").hidden = true;
  }
}

// XMLHttpRequest — ради прогресса загрузки большого файла.
function uploadOne(data, prefix) {
  const box = $("#upload");
  const bar = box.querySelector(".bar > div");
  const label = box.querySelector("span");
  box.hidden = false;
  bar.style.width = "0";
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        bar.style.width = `${(e.loaded / e.total) * 100}%`;
        label.textContent = `${prefix}Загрузка: ${Math.round((e.loaded / e.total) * 100)}%`;
      }
    };
    xhr.onload = () => {
      if (xhr.status === 201) return resolve(JSON.parse(xhr.responseText));
      let msg = xhr.statusText;
      try { msg = JSON.parse(xhr.responseText).detail; } catch { /* не JSON */ }
      reject(new Error(typeof msg === "string" ? msg : JSON.stringify(msg)));
    };
    xhr.onerror = () => reject(new Error("сеть недоступна"));
    xhr.open("POST", "/api/jobs");
    xhr.send(data);
  });
}

// ---------- список задач ----------

async function refreshJobs() {
  const jobs = await api("/api/jobs");
  const list = $("#jobs");
  $("#jobs-empty").hidden = jobs.length > 0;
  list.replaceChildren(...jobs.map((j) => {
    const li = el("li", { className: j.id === currentId ? "active" : "" },
      el("div", {},
        el("div", { className: "title", textContent: j.params.series }),
        el("div", { className: "sub", textContent: j.created.replace("T", " ") })),
      el("span", { className: `badge ${j.status}`, textContent: STATUS[j.status] }));
    li.addEventListener("click", () => openJob(j.id));
    return li;
  }));
}

// ---------- карточка задачи ----------

async function openJob(id) {
  if (dirty && id !== currentId && !confirm("Правки ходов не сохранены. Уйти?")) return;
  currentId = id;
  currentStatus = null;
  scene = null;
  dirty = false;
  candidatesLoadedFor = null;
  const detail = $("#detail");
  detail.replaceChildren($("#detail-tpl").content.cloneNode(true));
  bindDetail(detail);
  await refreshJobs();
  await poll();
}

function bindDetail(root) {
  root.querySelector('[data-a="delete"]').addEventListener("click", async () => {
    if (!confirm("Удалить задачу вместе с роликами?")) return;
    await api(`/api/jobs/${currentId}`, { method: "DELETE" }).catch((e) => alert(e.message));
    currentId = null;
    dirty = false;
    $("#detail").replaceChildren(el("div", { className: "placeholder", textContent: "Задача удалена" }));
    refreshJobs();
  });
  root.querySelector('[data-a="retry"]').addEventListener("click", async () => {
    await api(`/api/jobs/${currentId}/retry`, { method: "POST" }).catch((e) => alert(e.message));
    poll();
  });
  root.querySelector('[data-a="custom"]').addEventListener("click", () => {
    const start = Number(f("custom-start").value);
    const end = Number(f("custom-end").value);
    if (!(end > start)) return alert("Конец должен быть позже начала");
    chooseScene({ start, end });
  });
  root.querySelector('[data-a="save"]').addEventListener("click", () => saveScene().catch((e) => alert(e.message)));
  root.querySelector('[data-a="rescore"]').addEventListener("click", () => rescore().catch((e) => alert(e.message)));
  root.querySelector('[data-a="pace"]').addEventListener("click", () => sceneAction("/api/scene/pace").catch((e) => alert(e.message)));
  root.querySelector('[data-a="render"]').addEventListener("click", async () => {
    try {
      await saveScene();
      await api(`/api/jobs/${currentId}/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          length: f("length").value, preset: f("preset").value,
          music: f("music").value, music_volume: Number(f("music-volume").value),
        }),
      });
      poll();
    } catch (e) { alert(e.message); }
  });
  root.querySelectorAll("[data-s]").forEach((input) => input.addEventListener("input", () => { markDirty(); }));
}

const f = (name) => $(`#detail [data-f="${name}"]`);

async function poll() {
  clearTimeout(pollTimer);
  if (!currentId) return;
  let job;
  try {
    job = await api(`/api/jobs/${currentId}`);
  } catch (e) {
    return;
  }
  renderJob(job);
  if (job.status !== currentStatus) {
    const prev = currentStatus;
    currentStatus = job.status;
    if (prev !== null) refreshJobs();
  }
  if (job.has_scene && !scene && !ACTIVE.has(job.status)) await loadScene();
  if (ACTIVE.has(job.status)) pollTimer = setTimeout(poll, 1500);
}

function renderJob(job) {
  f("created").textContent = job.created.replace("T", " ");
  f("series").textContent = job.params.series;
  f("source").textContent = job.params.hint || "";
  const badge = f("badge");
  badge.className = `badge ${job.status}`;
  badge.textContent = STATUS[job.status];
  f("step").textContent = job.step;

  const bar = f("progress");
  bar.classList.toggle("hidden", !ACTIVE.has(job.status));
  bar.classList.toggle("indeterminate", ACTIVE.has(job.status) && job.progress === null);
  bar.firstElementChild.style.width = job.progress !== null ? `${job.progress * 100}%` : "";

  f("error").hidden = !job.error;
  f("error").textContent = job.error || "";
  $('#detail [data-a="retry"]').hidden = job.status !== "error";
  f("log").textContent = job.log.join("\n");

  const hasVideos = job.outputs.length > 0;
  f("videos").hidden = !hasVideos;
  if (hasVideos) {
    const latest = job.outputs[job.outputs.length - 1];
    const src = `/api/jobs/${job.id}/video/${encodeURIComponent(latest)}`;
    if (!f("player").src.endsWith(src)) f("player").src = src;
    f("outputs").replaceChildren(el("div", { className: "muted", textContent: "Скачать:" }),
      ...job.outputs.slice().reverse().map((name) =>
        el("a", { href: `/api/jobs/${job.id}/video/${encodeURIComponent(name)}`, download: name, textContent: name })));
  }

  f("choose").hidden = job.status !== "choose";
  if (job.status === "choose" && candidatesLoadedFor !== job.id) loadCandidates(job);

  const editable = job.has_scene && !ACTIVE.has(job.status);
  f("editor").hidden = !job.has_scene;
  f("editor").querySelectorAll("input, select, textarea, button").forEach((n) => { n.disabled = !editable; });
  if (config && !f("length").options.length) {
    fillSelect(f("length"), config.lengths, job.params.length);
    fillSelect(f("preset"), config.presets, job.params.preset);
    fillSelect(f("music"), { "": "Без музыки", ...Object.fromEntries(music.map((m) => [m, m])) }, job.params.music || "");
    f("music-volume").value = job.params.music_volume;
  }
}

// ---------- выбор сцены ----------

async function loadCandidates(job) {
  candidatesLoadedFor = job.id;
  const player = f("source-player");
  player.src = `/api/jobs/${job.id}/source`;
  const cands = await api(`/api/jobs/${job.id}/candidates`);
  f("candidates").replaceChildren(...cands.map((c, i) => {
    const watch = el("button", { className: "ghost", textContent: "Смотреть" });
    watch.addEventListener("click", () => { player.currentTime = c.start; player.play().catch(() => {}); });
    const take = el("button", { className: "primary", textContent: "Взять эту сцену" });
    take.addEventListener("click", () => chooseScene({ index: i }));
    return el("div", { className: "candidate" },
      el("div", { className: "head" },
        el("span", { className: "title", textContent: `${i + 1}. ${c.title}` }),
        el("span", { className: "score", textContent: `${c.score}/10` })),
      el("div", { className: "muted", textContent: `${fmtTime(c.start)}–${fmtTime(c.end)} · ${Math.round(c.end - c.start)} с · ${c.sides}` }),
      el("div", { textContent: c.why }),
      el("div", { className: "excerpt", textContent: `«${c.excerpt}»` }),
      el("div", { className: "buttons" }, watch, take));
  }));
  if (cands.length) {
    f("custom-start").value = cands[0].start;
    f("custom-end").value = cands[0].end;
  }
}

async function chooseScene(body) {
  try {
    await api(`/api/jobs/${currentId}/choose`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    candidatesLoadedFor = null;
    poll();
  } catch (e) { alert(e.message); }
}

// ---------- редактор ходов ----------

async function loadScene() {
  scene = await api(`/api/jobs/${currentId}/scene`);
  dirty = false;
  const s = (name) => $(`#detail [data-s="${name}"]`);
  s("title").value = scene.meta.title;
  s("white").value = scene.players.white.name;
  s("black").value = scene.players.black.name;
  s("verdict").value = scene.summary.verdict;
  s("line").value = scene.summary.line;
  for (const side of ["white", "black"]) {
    const avatar = scene.players[side].avatar;
    f(`ava-${side}`).src = avatar ? `/api/jobs/${currentId}/media/${avatar.split("/").pop()}` : "";
  }
  renderMoves();
  renderStats();
  f("saved").textContent = "";
}

function renderMoves() {
  const names = { white: scene.players.white.name, black: scene.players.black.name };
  f("moves").replaceChildren(...scene.moves.map((m, i) => {
    const category = el("select", { dataset: { m: "category" } });
    fillSelect(category, Object.fromEntries(Object.entries(CATEGORIES).map(([k, v]) => [k, v.label])), m.category);
    const title = el("input", { value: m.title, maxLength: 40, dataset: { m: "title" } });
    const evalInput = el("input", { type: "number", step: "0.1", min: "-5", max: "5", value: m.eval_after, title: "Шкала после хода", dataset: { m: "eval_after" } });
    const comment = el("textarea", { value: m.comment, rows: 2, maxLength: 220, dataset: { m: "comment" } });
    const show = el("input", { type: "checkbox", checked: m.show_card !== false, dataset: { m: "show_card" } });

    const card = el("div", { className: "move" },
      el("div", {},
        el("div", { className: "num", textContent: m.side === "white" ? `${m.n}.` : `${m.n}…` }),
        el("div", { className: "side-name", textContent: names[m.side] })),
      el("div", {},
        el("div", { className: "quote", textContent: `«${m.quote}»` }),
        el("div", { className: "fields" }, category, title, evalInput, comment),
        el("div", { className: "flags" }, el("label", {}, show, "Показывать карточку"),
          m.mate_in != null ? el("span", { className: "mate", textContent: m.mate_in === 0 ? "Шкала: # (мат)" : `Шкала: M${m.mate_in}` }) : "")));
    card.style.setProperty("--c", CATEGORIES[m.category].color);

    const update = (ev) => {
      if (ev?.target === evalInput) m.mate_in = null; // ручная правка шкалы отменяет отсчёт до мата у этого хода
      m.category = category.value;
      m.title = title.value;
      m.comment = comment.value;
      m.eval_after = Number(evalInput.value || 0);
      m.show_card = show.checked;
      card.style.setProperty("--c", CATEGORIES[m.category].color);
      renderStats();
      markDirty();
    };
    [category, title, evalInput, comment, show].forEach((n) => n.addEventListener("input", update));
    category.addEventListener("change", () => rescore().catch((e) => alert(e.message)));
    return card;
  }));
}

function renderStats() {
  const weights = config.weights;
  const parts = ["white", "black"].map((side) => {
    const own = scene.moves.filter((m) => m.side === side);
    const acc = own.length ? own.reduce((s, m) => s + weights[m.category], 0) / own.length : 0;
    return `${scene.players[side].name}: точность ${acc.toFixed(1)}`;
  });
  const lastMove = scene.moves[scene.moves.length - 1];
  const last = lastMove ? lastMove.eval_after : 0;
  const end = lastMove?.mate_in != null ? (lastMove.mate_in === 0 ? "# (мат)" : `M${lastMove.mate_in}`)
    : `${last > 0 ? "+" : ""}${Number(last).toFixed(1)}`;
  f("stats").replaceChildren(...parts.map((t) => el("span", { textContent: t })),
    el("span", { textContent: `шкала в конце ${end}` }));
}

function markDirty() {
  dirty = true;
  f("saved").textContent = "Есть несохранённые правки";
}

function collectScene() {
  const s = (name) => $(`#detail [data-s="${name}"]`).value;
  scene.meta.title = s("title");
  scene.players.white.name = s("white");
  scene.players.black.name = s("black");
  scene.summary.verdict = s("verdict");
  scene.summary.line = s("line");
}

// Шкала и темп карточек считаются на сервере тем же кодом, что и при анализе.
async function sceneAction(path) {
  if (!scene) return;
  collectScene();
  scene = await api(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(scene),
  });
  renderMoves();
  renderStats();
  markDirty();
}

const rescore = () => sceneAction("/api/scene/rescore");

async function saveScene() {
  if (!scene) return;
  collectScene();
  await api(`/api/jobs/${currentId}/scene`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(scene),
  });
  dirty = false;
  f("saved").textContent = "Сохранено";
}

// ---------- настройки: ключи и подключения ----------
// Слева — разделы (модели для разбора и распознавание речи), справа — выбранный раздел.
// Панели всех разделов живут в форме одновременно: правки в разных разделах сохраняются одной кнопкой.

let settings = null; // ответ /api/settings
let activeSection = null;
let pendingDefault = null; // «Сделать основной» до сохранения
const cleared = new Set(); // ключи, которые удалятся при сохранении
const SOURCE = { web: "задан здесь", env: "задан в .env", none: "не задан" };
const DEFAULT_KEY = "CHESSIFY_DEFAULT_PROFILE";
const NAV_GROUPS = { llm: "Модель для разбора", speech: "Распознавание речи" };
const SAVED_HINT = "Ключи хранятся на сервере и действуют сразу. В браузер они не возвращаются.";

function setupSettings() {
  const dialog = $("#settings");
  $("#open-settings").addEventListener("click", () => openSettings());
  dialog.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dialog.close()));
  $("#settings-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (await saveSettings()) $("#settings-saved").textContent = "Сохранено";
  });
}

async function openSettings(sectionId) {
  try {
    settings = await api("/api/settings");
  } catch (e) { alert(`Не удалось открыть настройки: ${e.message}`); return; }
  cleared.clear();
  pendingDefault = null;
  activeSection = sectionId || activeSection || settings.default_profile;
  $("#settings-error").hidden = true;
  $("#settings-saved").textContent = SAVED_HINT;
  renderSettings();
  $("#settings").showModal();
}

const currentDefault = () => pendingDefault || settings.default_profile;

function renderSettings() {
  const nav = $("#settings-nav");
  nav.replaceChildren();
  for (const [kind, title] of Object.entries(NAV_GROUPS)) {
    nav.append(el("div", { className: "nav-group", textContent: title }));
    for (const sec of settings.sections.filter((x) => x.kind === kind)) {
      const state = sec.ready === true ? "ready" : sec.ready === false ? "missing" : "unknown";
      const item = el("button", { type: "button", className: `nav-item ${sec.id === activeSection ? "active" : ""}` },
        el("span", { className: `dot ${state}`, title: { ready: "настроено", missing: "не настроено", unknown: "вход из терминала" }[state] }),
        el("span", { className: "nav-title", textContent: sec.title }),
        sec.id === currentDefault() ? el("span", { className: "tag web", textContent: "основная" }) : "");
      item.addEventListener("click", () => { activeSection = sec.id; showSection(); });
      nav.append(item);
    }
  }
  $("#settings-panes").replaceChildren(...settings.sections.map(sectionPane));
  showSection();
}

function showSection() {
  $("#settings-nav").querySelectorAll(".nav-item").forEach((b, i) => {
    b.classList.toggle("active", settings.sections[i].id === activeSection);
  });
  $("#settings-panes").querySelectorAll(".pane").forEach((p) => { p.hidden = p.dataset.id !== activeSection; });
}

function sectionPane(sec) {
  const pane = el("section", { className: "pane", dataset: { id: sec.id } },
    el("h3", { textContent: sec.title }),
    el("p", { className: "muted small", textContent: sec.about }));
  if (sec.link) pane.append(el("a", { href: sec.link, target: "_blank", rel: "noopener", textContent: "Получить ключ ↗" }));
  pane.append(...sec.fields.map(settingField));

  const actions = el("div", { className: "pane-actions" });
  const out = el("pre", { className: "check-out", hidden: true });
  const chips = el("div", { className: "chips", hidden: true });
  if (sec.check) {
    const check = el("button", { type: "button", className: "ghost", textContent: sec.fields.length ? "Сохранить и проверить" : "Проверить" });
    check.addEventListener("click", () => runCheck(sec, check));
    actions.append(check);
  }
  if (sec.kind === "llm") {
    if (sec.id === currentDefault()) {
      actions.append(el("span", { className: "tag web", textContent: "Основная модель: ей разбираются новые ролики" }));
    } else {
      const makeDefault = el("button", { type: "button", className: "ghost", textContent: "Сделать основной" });
      makeDefault.addEventListener("click", async () => {
        pendingDefault = sec.id;
        if (await saveSettings()) $("#settings-saved").textContent = `Основная модель — ${sec.title}`;
      });
      actions.append(makeDefault);
    }
  }
  pane.append(actions, out, chips);
  return pane;
}

function settingField(fd) {
  const input = fd.kind === "secret"
    ? el("input", { name: fd.key, type: "password", autocomplete: "new-password",
      placeholder: fd.masked ? `${fd.masked} — оставьте пустым, чтобы не менять` : "не задан" })
    : el("input", { name: fd.key, type: "text", value: fd.value || "", placeholder: fd.placeholder, autocomplete: "off" });
  const source = fd.source || "none";
  const tag = el("span", { className: `tag ${source}`, textContent: SOURCE[source] });
  const head = el("span", { className: "field-head" }, fd.label, el("code", { className: "var", textContent: fd.key }), tag);
  if (fd.source === "web") {
    const remove = el("button", { type: "button", className: "link-like", textContent: "удалить" });
    remove.addEventListener("click", () => {
      cleared.add(fd.key);
      input.value = "";
      tag.className = "tag cleared";
      tag.textContent = "удалится при сохранении";
    });
    head.append(remove);
  }
  input.addEventListener("input", () => cleared.delete(fd.key));
  const label = el("label", {}, head, input);
  if (fd.hint) label.append(el("span", { className: "hint small", textContent: fd.hint }));
  return label;
}

async function runCheck(sec, button) {
  button.disabled = true;
  try {
    if (sec.fields.length && !(await saveSettings())) return;
    const pane = $(`#settings-panes .pane[data-id="${sec.id}"]`);
    const out = pane.querySelector(".check-out");
    const chips = pane.querySelector(".chips");
    out.hidden = false;
    out.className = "check-out";
    out.textContent = "Проверяю…";
    try {
      const res = await api("/api/settings/check", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target: sec.check }),
      });
      out.className = `check-out ${res.ok ? "ok" : "fail"}`;
      out.textContent = res.lines.join("\n");
      // Модели на своём сервере — щелчком в поле «Модель»: имя обычно неизвестно заранее.
      const models = sec.id === "custom" ? res.models || [] : [];
      chips.hidden = models.length === 0;
      chips.replaceChildren(el("span", { className: "muted small", textContent: "Взять модель:" }), ...models.map((m) => {
        const chip = el("button", { type: "button", className: "ghost", textContent: m });
        chip.addEventListener("click", () => { $("#settings-form").elements.CUSTOM_LLM_MODEL.value = m; });
        return chip;
      }));
    } catch (e) {
      out.className = "check-out fail";
      out.textContent = e.message;
    }
  } finally { button.disabled = false; }
}

// Отправляются только изменения: пустой ключ — «не менять», пустой текст вместо заданного здесь — удалить.
async function saveSettings() {
  const form = $("#settings-form");
  const values = {};
  const clear = [...cleared];
  for (const fd of settings.sections.flatMap((x) => x.fields)) {
    const v = form.elements[fd.key].value.trim();
    if (fd.kind === "secret") { if (v) values[fd.key] = v; }
    else if (v !== (fd.value || "")) {
      if (v) values[fd.key] = v;
      else if (fd.source === "web") clear.push(fd.key);
    }
  }
  if (pendingDefault && pendingDefault !== settings.default_profile) values[DEFAULT_KEY] = pendingDefault;
  const error = $("#settings-error");
  try {
    settings = await api("/api/settings", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values, clear }),
    });
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
    return false;
  }
  error.hidden = true;
  cleared.clear();
  pendingDefault = null;
  renderSettings();
  await loadConfig();
  return true;
}

// ---------- старт ----------

window.addEventListener("beforeunload", (e) => { if (dirty) e.preventDefault(); });
$("#new-job").addEventListener("submit", submitJob);
$("#music-upload").addEventListener("change", uploadMusic);
setupDrop();
setupForm();
setupSettings();
Promise.all([loadConfig(), loadMusic()]).catch((e) => alert(`Не удалось загрузить настройки: ${e.message}`));
refreshJobs();
setInterval(refreshJobs, 5000);
