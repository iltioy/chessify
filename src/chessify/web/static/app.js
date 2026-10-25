"use strict";

// Подписи — в i18n.js: t("cat.<категория>"), t("status.<статус>").
const CATEGORIES = {
  brilliant: { color: "#26c2a3" },
  best: { color: "#81b64c" },
  excellent: { color: "#5fa83f" },
  good: { color: "#95b776" },
  inaccuracy: { color: "#f7c631" },
  mistake: { color: "#ffa459" },
  blunder: { color: "#fa412d" },
};
const status = (s) => t(`status.${s}`);
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
let currentJob = null; // последний ответ /api/jobs/<id>
let tt = null; // TikTok: приложение и подключённые аккаунты (/api/tiktok)
let ttFilledFor = null; // форма публикации заполнена для этой задачи — не затирать правки подписи

const fmtTime = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
async function api(path, options = {}) {
  // Сервер отвечает на языке интерфейса: ошибки, тексты настроек, журнал новых задач.
  const res = await fetch(path, { ...options, headers: { ...(options.headers || {}), "X-Lang": LANG } });
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
    [name, `${p.label}${p.missing_keys.some((k) => k !== "HF_TOKEN") ? t("not_configured") : ""}`]));
  fillSelect(form.profile, profiles, config.default_profile);
  showProfileWarning();
}

function setupForm() {
  const form = $("#new-job");
  // Язык ролика (речь, тексты модели, надписи) по умолчанию — как язык интерфейса.
  fillSelect(form.language, { ru: t("lang.ru"), en: t("lang.en") }, LANG);
  form.profile.addEventListener("change", showProfileWarning);
  form.tiktok_account.addEventListener("change", showTikTokMode);
  form.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", () => {
    $("#mode-hint").textContent = t(`mode.hint.${form.mode.value}`);
  }));
}

async function loadMusic() {
  music = await api("/api/music");
  const options = { "": t("music.none"), ...Object.fromEntries(music.map((m) => [m, m])) };
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
  } catch (e) { alert(t("err.music", { e: e.message })); }
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
    parts.push(t("warn.keys", { label: profile.label, keys: llm.join("; ") }));
  }
  if (missing.includes("HF_TOKEN")) parts.push(t("warn.hf"));
  const open = el("button", { type: "button", textContent: t("open_settings") });
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
    text.textContent = n === 0 ? t("drop") : n === 1 ? input.files[0].name : t("drop.many", { n });
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
      for (const name of ["series", "hint", "start", "end", "speakers", "profile", "length", "preset", "music", "music_volume", "mode", "language", "tiktok_account", "tiktok_mode"]) {
        if (form[name].value !== "") data.append(name, form[name].value);
      }
      data.append("review", form.review.checked ? "true" : "false");
      const prefix = files.length > 1 ? t("upload.file", { i: i + 1, n: files.length }) : "";
      lastId = (await uploadOne(data, prefix)).id;
      refreshJobs();
    }
    form.video.value = "";
    form.video.dispatchEvent(new Event("change"));
    if (lastId) openJob(lastId);
  } catch (e) {
    alert(t("err.create", { e: e.message }));
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
        label.textContent = t("upload.progress", { prefix, p: Math.round((e.loaded / e.total) * 100) });
      }
    };
    xhr.onload = () => {
      if (xhr.status === 201) return resolve(JSON.parse(xhr.responseText));
      let msg = xhr.statusText;
      try { msg = JSON.parse(xhr.responseText).detail; } catch { /* не JSON */ }
      reject(new Error(typeof msg === "string" ? msg : JSON.stringify(msg)));
    };
    xhr.onerror = () => reject(new Error(t("err.network")));
    xhr.open("POST", "/api/jobs");
    xhr.setRequestHeader("X-Lang", LANG);
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
      el("span", { className: `badge ${j.status}`, textContent: status(j.status) }));
    li.addEventListener("click", () => openJob(j.id));
    return li;
  }));
}

// ---------- карточка задачи ----------

async function openJob(id) {
  if (dirty && id !== currentId && !confirm(t("confirm.leave"))) return;
  currentId = id;
  currentStatus = null;
  scene = null;
  dirty = false;
  candidatesLoadedFor = null;
  currentJob = null;
  ttFilledFor = null;
  const detail = $("#detail");
  detail.replaceChildren($("#detail-tpl").content.cloneNode(true));
  applyI18n(detail);
  bindDetail(detail);
  await refreshJobs();
  await poll();
}

function bindDetail(root) {
  root.querySelector('[data-a="delete"]').addEventListener("click", async () => {
    if (!confirm(t("confirm.delete"))) return;
    await api(`/api/jobs/${currentId}`, { method: "DELETE" }).catch((e) => alert(e.message));
    currentId = null;
    dirty = false;
    $("#detail").replaceChildren(el("div", { className: "placeholder", textContent: t("deleted") }));
    refreshJobs();
  });
  root.querySelector('[data-a="retry"]').addEventListener("click", async () => {
    await api(`/api/jobs/${currentId}/retry`, { method: "POST" }).catch((e) => alert(e.message));
    poll();
  });
  root.querySelector('[data-a="custom"]').addEventListener("click", () => {
    const start = Number(f("custom-start").value);
    const end = Number(f("custom-end").value);
    if (!(end > start)) return alert(t("err.range"));
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
  root.querySelector('[data-a="tt-publish"]').addEventListener("click", publishTikTok);
  root.querySelector('[data-a="tt-settings"]').addEventListener("click", () => openSettings("tiktok"));
  f("tt-account").addEventListener("change", fillPrivacy);
  f("tt-mode").addEventListener("change", () => { f("tt-privacy").disabled = f("tt-mode").value === "inbox"; });
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
  if (ACTIVE.has(job.status) || job.tiktok?.state === "publishing") pollTimer = setTimeout(poll, 1500);
}

function renderJob(job) {
  currentJob = job;
  f("created").textContent = job.created.replace("T", " ");
  f("series").textContent = job.params.series;
  f("source").textContent = job.params.hint || "";
  const badge = f("badge");
  badge.className = `badge ${job.status}`;
  badge.textContent = status(job.status);
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
    f("outputs").replaceChildren(el("div", { className: "muted", textContent: t("download") }),
      ...job.outputs.slice().reverse().map((name) =>
        el("a", { href: `/api/jobs/${job.id}/video/${encodeURIComponent(name)}`, download: name, textContent: name })));
  }

  renderTikTok(job);

  f("choose").hidden = job.status !== "choose";
  if (job.status === "choose" && candidatesLoadedFor !== job.id) loadCandidates(job);

  const editable = job.has_scene && !ACTIVE.has(job.status);
  f("editor").hidden = !job.has_scene;
  f("editor").querySelectorAll("input, select, textarea, button").forEach((n) => { n.disabled = !editable; });
  if (config && !f("length").options.length) {
    fillSelect(f("length"), config.lengths, job.params.length);
    fillSelect(f("preset"), config.presets, job.params.preset);
    fillSelect(f("music"), { "": t("music.none"), ...Object.fromEntries(music.map((m) => [m, m])) }, job.params.music || "");
    f("music-volume").value = job.params.music_volume;
  }
}

// ---------- публикация в TikTok ----------
// Креды и токены хранит модуль tiktok-publisher на сервере; здесь — только имена аккаунтов и параметры поста.

const ttName = (a) => (a.username ? `${a.name} · @${a.username}` : a.name);

async function loadTikTok() {
  try { tt = await api("/api/tiktok"); } catch { tt = null; }
  const form = $("#new-job");
  const accounts = tt?.accounts || [];
  $("#tiktok-row").hidden = accounts.length === 0;
  fillSelect(form.tiktok_account, { "": t("tt.dont"), ...Object.fromEntries(accounts.map((a) => [a.name, ttName(a)])) },
    form.tiktok_account.value);
  showTikTokMode();
  if (currentJob) renderTikTok(currentJob);
}

function showTikTokMode() {
  const form = $("#new-job");
  form.tiktok_mode.closest("label").hidden = !form.tiktok_account.value;
}

function fillPrivacy() {
  const acc = (tt?.accounts || []).find((a) => a.name === f("tt-account").value);
  const levels = Object.fromEntries((tt?.privacy_levels || []).map((p) => [p, t(`tt.privacy.${p}`)]));
  const def = acc ? t("tt.privacy.default", { p: t(`tt.privacy.${acc.default_privacy}`) }) : "";
  fillSelect(f("tt-privacy"), { "": def, ...levels }, "");
}

function renderTikTok(job) {
  const box = f("tiktok");
  box.hidden = job.outputs.length === 0 || !tt;
  if (box.hidden) return;
  const accounts = tt.accounts;
  const info = job.tiktok;
  f("tt-empty").hidden = accounts.length > 0;
  f("tt-form").hidden = accounts.length === 0;
  f("tt-video").textContent = t("tt.video", { name: job.outputs[job.outputs.length - 1] });
  if (accounts.length && ttFilledFor !== job.id) {
    ttFilledFor = job.id;
    const preferred = info?.account || job.params.tiktok?.account;
    fillSelect(f("tt-account"), Object.fromEntries(accounts.map((a) => [a.name, ttName(a)])),
      accounts.some((a) => a.name === preferred) ? preferred : accounts[0].name);
    fillPrivacy();
    f("tt-mode").value = info?.mode || job.params.tiktok?.mode || "direct";
    f("tt-privacy").disabled = f("tt-mode").value === "inbox";
    f("tt-caption").value = info?.caption || job.params.tiktok?.caption || job.tiktok_caption || "";
  }
  $('#detail [data-a="tt-publish"]').disabled = info?.state === "publishing";
  const res = f("tt-result");
  res.hidden = !info;
  if (info) res.replaceChildren(...tiktokResult(info));
}

function tiktokResult(info) {
  const lines = [];
  const add = (text, cls = "") => lines.push(el("div", { className: cls, textContent: text }));
  const who = info.account;
  if (info.state === "publishing") add(t("tt.state.publishing", { who }));
  else if (info.state === "error") add(t("tt.state.error", { e: info.error || "" }), "fail");
  else if (info.status === "SEND_TO_USER_INBOX") add(t("tt.state.inbox", { who }), "ok");
  else if (info.state === "processing") add(t("tt.state.processing"));
  else add(t("tt.state.done", { who, p: info.privacy ? t(`tt.privacy.${info.privacy}`) : "" }), "ok");
  if (info.note) add(t("tt.note.unaudited"), "warn-text");
  if (info.url) {
    lines.push(el("a", { href: info.url, target: "_blank", rel: "noopener", textContent: info.url }));
  } else if (info.publish_id && info.state !== "error" && info.status !== "SEND_TO_USER_INBOX"
    && info.privacy !== "SELF_ONLY") {
    add(t("tt.no_link"), "muted small");
  }
  if (info.publish_id && info.state !== "publishing") {
    const refresh = el("button", { type: "button", className: "link-like", textContent: t("tt.refresh") });
    refresh.addEventListener("click", async () => {
      try { renderJob(await api(`/api/jobs/${currentId}/tiktok/refresh`, { method: "POST" })); } catch (e) { alert(e.message); }
    });
    lines.push(refresh);
  }
  return lines;
}

async function publishTikTok() {
  const info = currentJob?.tiktok;
  if (info && info.state !== "error" && !confirm(t("tt.confirm_again"))) return;
  try {
    await api(`/api/jobs/${currentId}/tiktok`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        account: f("tt-account").value, caption: f("tt-caption").value,
        privacy: f("tt-privacy").value || null, mode: f("tt-mode").value,
      }),
    });
    poll();
  } catch (e) { alert(e.message); }
}

// ---------- выбор сцены ----------

async function loadCandidates(job) {
  candidatesLoadedFor = job.id;
  const player = f("source-player");
  player.src = `/api/jobs/${job.id}/source`;
  const cands = await api(`/api/jobs/${job.id}/candidates`);
  f("candidates").replaceChildren(...cands.map((c, i) => {
    const watch = el("button", { className: "ghost", textContent: t("watch") });
    watch.addEventListener("click", () => { player.currentTime = c.start; player.play().catch(() => {}); });
    const take = el("button", { className: "primary", textContent: t("take") });
    take.addEventListener("click", () => chooseScene({ index: i }));
    return el("div", { className: "candidate" },
      el("div", { className: "head" },
        el("span", { className: "title", textContent: `${i + 1}. ${c.title}` }),
        el("span", { className: "score", textContent: `${c.score}/10` })),
      el("div", { className: "muted", textContent: `${fmtTime(c.start)}–${fmtTime(c.end)} · ${Math.round(c.end - c.start)} ${t("seconds")} · ${c.sides}` }),
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
    fillSelect(category, Object.fromEntries(Object.keys(CATEGORIES).map((k) => [k, t(`cat.${k}`)])), m.category);
    const title = el("input", { value: m.title, maxLength: 40, dataset: { m: "title" } });
    const evalInput = el("input", { type: "number", step: "0.1", min: "-5", max: "5", value: m.eval_after, title: t("eval.tip"), dataset: { m: "eval_after" } });
    const comment = el("textarea", { value: m.comment, rows: 2, maxLength: 220, dataset: { m: "comment" } });
    const show = el("input", { type: "checkbox", checked: m.show_card !== false, dataset: { m: "show_card" } });

    const card = el("div", { className: "move" },
      el("div", {},
        el("div", { className: "num", textContent: m.side === "white" ? `${m.n}.` : `${m.n}…` }),
        el("div", { className: "side-name", textContent: names[m.side] })),
      el("div", {},
        el("div", { className: "quote", textContent: `«${m.quote}»` }),
        el("div", { className: "fields" }, category, title, evalInput, comment),
        el("div", { className: "flags" }, el("label", {}, show, t("show_card")),
          m.mate_in != null ? el("span", { className: "mate", textContent: m.mate_in === 0 ? t("mate.now") : t("mate.in", { n: m.mate_in }) }) : "")));
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
    return t("stats.accuracy", { name: scene.players[side].name, acc: acc.toFixed(1) });
  });
  const lastMove = scene.moves[scene.moves.length - 1];
  const last = lastMove ? lastMove.eval_after : 0;
  const end = lastMove?.mate_in != null ? (lastMove.mate_in === 0 ? t("mate.short") : `M${lastMove.mate_in}`)
    : `${last > 0 ? "+" : ""}${Number(last).toFixed(1)}`;
  f("stats").replaceChildren(...parts.map((t) => el("span", { textContent: t })),
    el("span", { textContent: t("stats.end", { end }) }));
}

function markDirty() {
  dirty = true;
  f("saved").textContent = t("unsaved");
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
  f("saved").textContent = t("saved");
}

// ---------- настройки: ключи и подключения ----------
// Слева — разделы (модели для разбора и распознавание речи), справа — выбранный раздел.
// Панели всех разделов живут в форме одновременно: правки в разных разделах сохраняются одной кнопкой.

let settings = null; // ответ /api/settings
let activeSection = null;
let pendingDefault = null; // «Сделать основной» до сохранения
const cleared = new Set(); // ключи, которые удалятся при сохранении

const DEFAULT_KEY = "CHESSIFY_DEFAULT_PROFILE";
const NAV_GROUPS = ["llm", "speech", "publish"];

function setupSettings() {
  const dialog = $("#settings");
  $("#open-settings").addEventListener("click", () => openSettings());
  dialog.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dialog.close()));
  $("#settings-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (await saveSettings()) $("#settings-saved").textContent = t("saved");
  });
}

async function openSettings(sectionId) {
  try {
    [settings, tt] = await Promise.all([api("/api/settings"), api("/api/tiktok")]);
  } catch (e) { alert(t("err.settings", { e: e.message })); return; }
  cleared.clear();
  pendingDefault = null;
  activeSection = sectionId || activeSection || settings.default_profile;
  $("#settings-error").hidden = true;
  $("#settings-saved").textContent = t("settings.hint");
  renderSettings();
  $("#settings").showModal();
}

const currentDefault = () => pendingDefault || settings.default_profile;

function renderSettings() {
  const nav = $("#settings-nav");
  nav.replaceChildren();
  for (const kind of NAV_GROUPS) {
    nav.append(el("div", { className: "nav-group", textContent: t(`nav.${kind}`) }));
    for (const sec of settings.sections.filter((x) => x.kind === kind)) {
      const state = sec.ready === true ? "ready" : sec.ready === false ? "missing" : "unknown";
      const item = el("button", { type: "button", className: `nav-item ${sec.id === activeSection ? "active" : ""}`, dataset: { id: sec.id } },
        el("span", { className: `dot ${state}`, title: t(`dot.${state}`) }),
        el("span", { className: "nav-title", textContent: sec.title }),
        sec.id === currentDefault() ? el("span", { className: "tag web", textContent: t("main") }) : "");
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
  if (sec.link) {
    pane.append(el("a", { href: sec.link, target: "_blank", rel: "noopener",
      textContent: t(sec.id === "tiktok" ? "tt.dev_link" : "get_key") }));
  }
  pane.append(...sec.fields.map(settingField));
  if (sec.id === "tiktok") {
    pane.append(el("div", { className: "tt-pane", id: "tt-pane" }));
    queueMicrotask(renderTikTokPane);
  }

  const actions = el("div", { className: "pane-actions" });
  const out = el("pre", { className: "check-out", hidden: true });
  const chips = el("div", { className: "chips", hidden: true });
  if (sec.check) {
    const check = el("button", { type: "button", className: "ghost", textContent: sec.fields.length ? t("check.save") : t("check") });
    check.addEventListener("click", () => runCheck(sec, check));
    actions.append(check);
  }
  if (sec.kind === "llm") {
    if (sec.id === currentDefault()) {
      actions.append(el("span", { className: "tag web", textContent: t("main.long") }));
    } else {
      const makeDefault = el("button", { type: "button", className: "ghost", textContent: t("make_main") });
      makeDefault.addEventListener("click", async () => {
        pendingDefault = sec.id;
        if (await saveSettings()) $("#settings-saved").textContent = t("main.saved", { title: sec.title });
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
      placeholder: fd.masked ? t("secret.keep", { masked: fd.masked }) : t("source.none") })
    : el("input", { name: fd.key, type: "text", value: fd.value || "", placeholder: fd.placeholder, autocomplete: "off" });
  const source = fd.source || "none";
  const tag = el("span", { className: `tag ${source}`, textContent: t(`source.${source}`) });
  const head = el("span", { className: "field-head" }, fd.label, el("code", { className: "var", textContent: fd.key }), tag);
  if (fd.source === "web") {
    const remove = el("button", { type: "button", className: "link-like", textContent: t("remove") });
    remove.addEventListener("click", () => {
      cleared.add(fd.key);
      input.value = "";
      tag.className = "tag cleared";
      tag.textContent = t("remove.pending");
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
    out.textContent = t("checking");
    try {
      const res = await api("/api/settings/check", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target: sec.check }),
      });
      out.className = `check-out ${res.ok ? "ok" : "fail"}`;
      out.textContent = res.lines.join("\n");
      // Модели на своём сервере — щелчком в поле «Модель»: имя обычно неизвестно заранее.
      const models = sec.id === "custom" ? res.models || [] : [];
      chips.hidden = models.length === 0;
      chips.replaceChildren(el("span", { className: "muted small", textContent: t("take_model") }), ...models.map((m) => {
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

// ---------- настройки: TikTok ----------

let ttConnectTimer = null;

async function ttCall(path, method, body) {
  const error = $("#settings-error");
  try {
    tt = await api(path, { method, headers: { "Content-Type": "application/json" }, body: body && JSON.stringify(body) });
    error.hidden = true;
    renderTikTokPane();
    loadTikTok();
    return true;
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
    return false;
  }
}

function renderTikTokPane() {
  const box = $("#tt-pane");
  if (!box || !tt) return;
  const dot = $(`#settings-nav .nav-item[data-id="tiktok"] .dot`);
  if (dot) dot.className = `dot ${tt.accounts.length ? "ready" : "missing"}`;

  const steps = el("ol", { className: "tt-steps small" },
    ...["tt.step1", "tt.step2", "tt.step3"].map((k) => el("li", { textContent: t(k) })),
    el("li", {}, t("tt.step4"), " ", el("code", { textContent: `http://127.0.0.1:*${tt.callback_path}` })),
    el("li", { textContent: t("tt.step5") }));

  const key = el("input", { type: "text", value: tt.app?.client_key || "", autocomplete: "off", placeholder: "aw…" });
  const secret = el("input", { type: "password", autocomplete: "new-password",
    placeholder: tt.app ? t("secret.keep", { masked: tt.app.secret_masked }) : t("source.none") });
  const saveApp = el("button", { type: "button", className: "ghost", textContent: t("tt.save_app") });
  saveApp.addEventListener("click", async () => {
    if (await ttCall("/api/tiktok/app", "PUT", { client_key: key.value, client_secret: secret.value })) {
      $("#settings-saved").textContent = t("saved");
    }
  });
  const app = el("div", { className: "tt-app" },
    el("label", {}, el("span", { className: "field-head" }, "Client key"), key),
    el("label", {}, el("span", { className: "field-head" }, "Client secret"), secret),
    el("div", { className: "pane-actions" }, saveApp));

  const accounts = el("div", { className: "tt-accounts" },
    el("div", { className: "nav-group", textContent: t("tt.accounts") }),
    ...(tt.accounts.length ? tt.accounts.map(ttAccountRow) : [el("p", { className: "muted small", textContent: t("tt.no_accounts") })]));

  const names = new Set(tt.accounts.map((a) => a.name));
  let suggested = "main";
  for (let i = 2; names.has(suggested); i++) suggested = `main${i}`;
  const name = el("input", { type: "text", value: suggested, autocomplete: "off", maxLength: 40 });
  const connect = el("button", { type: "button", className: "primary", textContent: t("tt.connect"), disabled: !tt.app });
  const flow = el("div", { className: "tt-flow", hidden: true });
  connect.addEventListener("click", () => ttConnect(name.value.trim(), flow));
  const connectBox = el("div", { className: "tt-connect" },
    el("div", { className: "row" },
      el("label", { className: "grow" }, el("span", { textContent: t("tt.account_name") }), name),
      el("div", { className: "pane-actions" }, connect)),
    tt.app ? "" : el("p", { className: "muted small", textContent: t("tt.need_app") }),
    flow);

  box.replaceChildren(steps, app, accounts, connectBox,
    el("p", { className: "muted small", textContent: t("tt.audit") }));
}

function ttAccountRow(a) {
  const privacy = el("select", {});
  fillSelect(privacy, Object.fromEntries(tt.privacy_levels.map((p) => [p, t(`tt.privacy.${p}`)])), a.default_privacy);
  privacy.addEventListener("change", () => ttCall(`/api/tiktok/accounts/${encodeURIComponent(a.name)}`, "PUT",
    { default_privacy: privacy.value }));
  const remove = el("button", { type: "button", className: "ghost danger", textContent: t("tt.disconnect") });
  remove.addEventListener("click", () => {
    if (confirm(t("tt.confirm_disconnect", { name: ttName(a) }))) ttCall(`/api/tiktok/accounts/${encodeURIComponent(a.name)}`, "DELETE");
  });
  return el("div", { className: "tt-account" },
    el("div", { className: "grow" },
      el("div", { className: "title", textContent: a.display_name || a.username || a.name }),
      el("div", { className: "muted small", textContent: ttName(a) })),
    el("label", {}, el("span", { textContent: t("tt.default_privacy") }), privacy),
    remove);
}

async function ttConnect(name, flow) {
  const tab = window.open("", "_blank"); // сразу, в ответ на нажатие — иначе браузер заблокирует вкладку
  let res;
  try {
    res = await api("/api/tiktok/connect", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ account: name }),
    });
  } catch (e) {
    tab?.close();
    $("#settings-error").textContent = e.message;
    $("#settings-error").hidden = false;
    return;
  }
  if (tab) tab.location = res.url;
  const paste = el("input", { type: "text", autocomplete: "off", placeholder: "http://127.0.0.1:…/api/tiktok/callback/?code=…" });
  const done = el("button", { type: "button", className: "ghost", textContent: t("tt.finish") });
  done.addEventListener("click", async () => {
    if (paste.value.trim() && await ttCall("/api/tiktok/finish", "POST", { url: paste.value.trim() })) stopConnectWait();
  });
  flow.hidden = false;
  flow.replaceChildren(
    el("p", { className: "small", textContent: res.local ? t("tt.flow.local") : t("tt.flow.remote") }),
    el("a", { href: res.url, target: "_blank", rel: "noopener", textContent: t("tt.open_login") }),
    el("label", {}, el("span", { textContent: t("tt.paste") }), paste),
    el("div", { className: "pane-actions" }, done));
  // Вход завершается в другой вкладке — ждём, пока аккаунт появится в списке.
  const before = new Set(tt.accounts.map((a) => `${a.name}:${a.connected_at}`));
  const started = Date.now();
  stopConnectWait();
  ttConnectTimer = setInterval(async () => {
    if (Date.now() - started > 5 * 60 * 1000 || !$("#settings").open) return stopConnectWait();
    try {
      const next = await api("/api/tiktok");
      if (next.accounts.some((a) => !before.has(`${a.name}:${a.connected_at}`))) {
        stopConnectWait();
        tt = next;
        renderTikTokPane();
        loadTikTok();
        $("#settings-saved").textContent = t("tt.connected");
      }
    } catch { /* следующая попытка */ }
  }, 3000);
}

function stopConnectWait() {
  clearInterval(ttConnectTimer);
  ttConnectTimer = null;
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

applyI18n();
document.querySelectorAll("[data-lang]").forEach((b) => {
  b.classList.toggle("active", b.dataset.lang === LANG);
  b.addEventListener("click", () => { if (b.dataset.lang !== LANG) setLang(b.dataset.lang); });
});

window.addEventListener("beforeunload", (e) => { if (dirty) e.preventDefault(); });
$("#new-job").addEventListener("submit", submitJob);
$("#music-upload").addEventListener("change", uploadMusic);
setupDrop();
setupForm();
setupSettings();
Promise.all([loadConfig(), loadMusic(), loadTikTok()]).catch((e) => alert(t("err.config", { e: e.message })));
refreshJobs();
setInterval(refreshJobs, 5000);
