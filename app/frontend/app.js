const state = {
  config: null,
  people: [],
  pendingPerson: null,
  preview: null,
  manualSources: [],
  anchors: [],
  languageMode: "zh",
  activePersonId: null,
  noticeTimer: null,
};

const el = Object.fromEntries([
  "search-form", "search-button", "person-name", "identity-anchors", "language-mode",
  "config-hint", "config-light", "identity-panel", "identity-platform", "identity-title",
  "identity-snippet", "identity-link", "preview-platforms", "identity-back", "identity-confirm",
  "manual-source-form", "manual-source-url", "manual-source-list", "progress-panel",
  "progress-person", "progress-percent", "progress-bar", "progress-stage", "result-panel",
  "result-title", "result-language", "result-profiles", "result-sources", "result-overview",
  "result-identity", "result-accomplishments", "result-viewpoints", "result-evolution",
  "result-external", "result-timeline", "portrait-section", "result-images", "download-link",
  "ask-form", "ask-question", "ask-button", "ask-status", "ask-answer", "ask-answer-meta",
  "ask-answer-text", "ask-answer-sources", "person-count", "person-list",
  "settings-button", "settings-dialog", "settings-close", "settings-form", "brave-key",
  "deepseek-key", "saved-status", "notice",
].map((id) => [id.replaceAll("-", "_"), document.querySelector(`#${id}`)]));
el.process_steps = [...document.querySelectorAll(".process-steps li")];

async function request(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* use status */ }
    throw new Error(detail);
  }
  return response;
}

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function notice(message, type = "info") {
  window.clearTimeout(state.noticeTimer);
  el.notice.textContent = message;
  el.notice.classList.toggle("is-error", type === "error");
  el.notice.classList.add("is-visible");
  state.noticeTimer = window.setTimeout(() => el.notice.classList.remove("is-visible"), 4800);
}

function renderConfig() {
  const searchReady = Boolean(state.config?.search_configured);
  const allReady = Boolean(searchReady && state.config?.llm_configured);
  el.config_light.classList.toggle("is-ready", allReady);
  el.config_hint.classList.toggle("is-ready", allReady);
  el.config_hint.textContent = allReady ? "已连接" : searchReady ? "缺少 DeepSeek" : "设置 API";
  el.saved_status.textContent = `${searchReady ? "Brave 已连接" : "Brave 未连接"} · ${state.config?.llm_configured ? "DeepSeek 已连接" : "DeepSeek 未连接"}`;
}

async function loadConfig() {
  state.config = await (await request("/api/config")).json();
  renderConfig();
}

function renderPeople() {
  const complete = state.people.filter((person) => person.has_report);
  el.person_count.textContent = String(complete.length);
  el.person_list.replaceChildren();
  if (!complete.length) {
    el.person_list.append(node("p", "empty-state", "还没有完成的人物档案。"));
    return;
  }
  complete.forEach((person) => {
    const row = node("article", "person-item");
    const copy = node("div");
    copy.append(node("strong", "", person.name), node("small", "", person.overview || "人物知识档案"));
    const count = node("span", "", `${person.document_count || 0} 篇资料`);
    const open = node("button", "", "打开档案 →");
    open.type = "button";
    open.addEventListener("click", () => openExisting(person));
    row.append(copy, count, open);
    el.person_list.append(row);
  });
}

async function loadPeople() {
  state.people = await (await request("/api/persons")).json();
  renderPeople();
}

function renderPreview() {
  const primary = state.preview.primary_source;
  el.identity_platform.textContent = primary.platform;
  el.identity_title.textContent = primary.title;
  el.identity_snippet.textContent = primary.snippet || "打开主页，通过头像、机构、作品或简介确认身份。";
  el.identity_link.href = primary.url;
  el.preview_platforms.replaceChildren();
  (state.preview.platform_links || []).forEach((item) => {
    const link = node("a", "", `${item.platform} · ${item.title}`);
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    el.preview_platforms.append(link);
  });
  renderManualSources();
  el.identity_panel.hidden = false;
  el.identity_panel.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderManualSources() {
  el.manual_source_list.replaceChildren();
  state.manualSources.forEach((source) => {
    const item = node("div", "manual-source-item");
    item.append(node("strong", "", "已加入"), node("span", "", source.url));
    el.manual_source_list.append(item);
  });
}

async function searchIdentity(event) {
  event.preventDefault();
  if (!state.config?.search_configured) {
    el.settings_dialog.showModal();
    notice("先连接 Brave Search。", "error");
    return;
  }
  const name = el.person_name.value.trim();
  if (!name) return;
  state.anchors = el.identity_anchors.value.split(/[，,、]/).map((item) => item.trim()).filter(Boolean);
  state.languageMode = el.language_mode.value;
  el.search_button.disabled = true;
  el.search_button.querySelector("span").textContent = "正在查找";
  el.result_panel.hidden = true;
  el.identity_panel.hidden = true;
  try {
    state.pendingPerson = await (await request("/api/persons", {
      method: "POST",
      body: JSON.stringify({ name, description: state.anchors.length ? `身份线索：${state.anchors.join("、")}` : null }),
    })).json();
    state.preview = await (await request(`/api/persons/${state.pendingPerson.id}/prepare`, {
      method: "POST", body: JSON.stringify({ anchors: state.anchors }),
    })).json();
    state.manualSources = [];
    renderPreview();
  } catch (error) {
    notice(error.message, "error");
  } finally {
    el.search_button.disabled = false;
    el.search_button.querySelector("span").textContent = "查找这个人";
  }
}

async function addManualSource(event) {
  event.preventDefault();
  if (!state.pendingPerson) return;
  const url = el.manual_source_url.value.trim();
  if (!url) return;
  try {
    const source = await (await request(`/api/persons/${state.pendingPerson.id}/sources`, {
      method: "POST", body: JSON.stringify({ url }),
    })).json();
    if (!state.manualSources.some((item) => item.url === source.url)) state.manualSources.push(source);
    el.manual_source_url.value = "";
    renderManualSources();
    notice("网址已加入。", "info");
  } catch (error) { notice(error.message, "error"); }
}

function updateProgress(job) {
  const progress = Math.max(0, Math.min(1, Number(job.progress || 0)));
  const percent = Math.round(progress * 100);
  el.progress_person.textContent = `${state.pendingPerson?.name || "人物"} 知识档案`;
  el.progress_percent.textContent = `${percent}%`;
  el.progress_bar.style.width = `${percent}%`;
  el.progress_stage.textContent = job.error || job.stage || "正在处理";
  const active = progress < .18 ? 0 : progress < .70 ? 1 : progress < .91 ? 2 : 3;
  el.process_steps.forEach((step, index) => {
    step.classList.toggle("is-done", index < active || job.status === "completed");
    step.classList.toggle("is-active", index === active && job.status !== "completed");
  });
}

async function confirmIdentity() {
  if (!state.config?.llm_configured) {
    el.settings_dialog.showModal();
    notice("连接 DeepSeek 后即可整理。", "error");
    return;
  }
  el.identity_confirm.disabled = true;
  el.identity_panel.hidden = true;
  el.progress_panel.hidden = false;
  updateProgress({ progress: 0, stage: "身份已确认，准备开始", status: "queued" });
  el.progress_panel.scrollIntoView({ behavior: "smooth", block: "center" });
  try {
    const job = await (await request(`/api/persons/${state.pendingPerson.id}/build`, {
      method: "POST",
      body: JSON.stringify({
        anchors: state.anchors,
        language_mode: state.languageMode,
        confirmed_source_url: state.preview.primary_source.url,
        use_existing_candidates: true,
      }),
    })).json();
    await pollJob(job.id);
  } catch (error) {
    el.progress_stage.textContent = error.message;
    notice(error.message, "error");
  } finally { el.identity_confirm.disabled = false; }
}

async function pollJob(jobId) {
  for (;;) {
    const job = await (await request(`/api/build-jobs/${jobId}`)).json();
    updateProgress(job);
    if (job.status === "completed") {
      const report = await (await request(`/api/persons/${job.person_id}/report`)).json();
      renderReport(report, job.download_url);
      el.progress_panel.hidden = true;
      await loadPeople();
      notice("档案完成。", "info");
      return;
    }
    if (job.status === "failed") throw new Error(job.error || "人物档案生成失败");
    await new Promise((resolve) => window.setTimeout(resolve, 900));
  }
}

function fillList(container, items, emptyText, render) {
  container.replaceChildren();
  if (!items?.length) { container.append(node("p", "empty-state", emptyText)); return; }
  items.forEach((item) => container.append(render(item)));
}

function renderImages(images) {
  el.result_images.replaceChildren();
  el.portrait_section.hidden = !images?.length;
  (images || []).slice(0, 4).forEach((item, index) => {
    const figure = node("figure", `portrait-card portrait-card-${index + 1}`);
    const link = node("a");
    link.href = item.source_url || item.full_url || item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const image = node("img");
    image.src = item.url;
    image.alt = item.caption || "人物公开图片";
    image.loading = index === 0 ? "eager" : "lazy";
    image.decoding = "async";
    image.addEventListener("error", () => {
      figure.remove();
      if (!el.result_images.children.length) el.portrait_section.hidden = true;
    });
    link.append(image);
    const caption = node("figcaption");
    caption.append(node("strong", "", item.caption || "公开图片"));
    const credit = [item.source_label, item.author, item.license].filter(Boolean).join(" · ");
    caption.append(node("small", "", credit || "查看图片来源"));
    figure.append(link, caption);
    el.result_images.append(figure);
  });
}

async function refreshImages(personId) {
  if (!personId) return;
  try {
    const payload = await (await request(`/api/persons/${personId}/images/refresh`, {
      method: "POST", body: JSON.stringify({}),
    })).json();
    if (state.activePersonId === personId) renderImages(payload.images || []);
  } catch (_) { /* Image enrichment is optional; keep the dossier readable. */ }
}

function renderReport(report, downloadUrl = null, personId = null) {
  const content = report.content || report;
  const resolvedPersonId = personId || report.person_id || null;
  state.activePersonId = resolvedPersonId;
  const languageLabels = { zh: "中文", en: "English", bilingual: "中英双语" };
  el.result_title.textContent = (content.title || "人物档案").replace(/\s*人物全景\s*$/, "");
  el.result_language.textContent = languageLabels[content.language_mode] || languageLabels.zh;
  el.result_overview.textContent = content.overview || "人物知识档案已生成。";
  renderImages(content.images || []);
  if (!content.images?.length && resolvedPersonId) refreshImages(resolvedPersonId);
  el.ask_question.value = "";
  el.ask_answer.hidden = true;
  el.ask_answer_meta.hidden = true;
  el.ask_answer_meta.textContent = "";
  el.ask_answer_text.textContent = "";
  el.ask_answer_sources.replaceChildren();

  fillList(el.result_profiles, content.public_profiles, "暂未识别到独立公开主页。", (item) => {
    const link = node("a", "profile-card");
    link.href = item.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.append(node("small", "", item.platform), node("strong", "", item.title || item.url));
    return link;
  });
  const profileUrls = new Set((content.public_profiles || []).map((item) => item.url));
  const sourceItems = (content.public_sources || []).filter((item) => !profileUrls.has(item.url));
  fillList(el.result_sources, sourceItems, "没有其他收录资料。", (item) => {
    const row = node("div", "source-row");
    row.append(node("span", "", item.platform || "公开资料"), node("strong", "", item.title));
    const link = node("a", "", "打开原文 ↗"); link.href = item.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    row.append(link); return row;
  });
  fillList(el.result_identity, content.identity, "现有资料没有形成独立身份条目。", (item) => node("li", "", item));
  fillList(el.result_accomplishments, content.accomplishments, "现有资料不足以列出明确事项。", (item) => {
    const card = node("article", "accomplishment-card");
    card.append(node("small", "", item.period || "时间不详"), node("h4", "", item.title), node("p", "", item.description || ""));
    return card;
  });
  fillList(el.result_viewpoints, content.viewpoint_topics, "现有资料不足以形成明确观点主题。", (topic) => {
    const block = node("section", "viewpoint-topic");
    block.append(node("h4", "", topic.name), node("p", "", topic.summary || ""));
    const list = node("ul");
    (topic.points || []).forEach((point) => {
      const item = node("li"); item.append(node("strong", "", point.statement));
      if (point.explanation) item.append(node("span", "", point.explanation));
      list.append(item);
    });
    block.append(list); return block;
  });
  fillList(el.result_evolution, content.viewpoint_evolution, "现有资料不足以判断明确变化。", (item) => {
    const row = node("div", "compact-item"); row.append(node("strong", "", item.period || "时间不详"), node("p", "", item.summary)); return row;
  });
  fillList(el.result_external, content.external_views, "现有资料没有形成可单独归纳的外部评价。", (item) => {
    const row = node("div", "compact-item"); row.append(node("p", "", item.summary)); return row;
  });
  fillList(el.result_timeline, content.timeline, "现有资料没有形成可用时间线。", (item) => {
    const row = node("div", "timeline-item"); row.append(node("strong", "", item.date || "日期不详"), node("p", "", item.event)); return row;
  });

  if (downloadUrl) { el.download_link.href = downloadUrl; el.download_link.onclick = null; }
  else if (personId) { el.download_link.href = "#"; el.download_link.onclick = (event) => downloadExisting(event, personId); }
  el.result_panel.hidden = false;
  el.result_panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function askKnowledgeBase(event) {
  event.preventDefault();
  const question = el.ask_question.value.trim();
  if (!question || !state.activePersonId) return;
  el.ask_button.disabled = true;
  el.ask_button.textContent = "…";
  el.ask_status.textContent = "正在查阅现有人物库";
  el.ask_answer.hidden = false;
  el.ask_answer.classList.add("is-loading");
  el.ask_answer_meta.hidden = true;
  el.ask_answer_meta.textContent = "";
  el.ask_answer_text.textContent = "正在查找相关资料…";
  el.ask_answer_sources.replaceChildren();
  const researchHint = window.setTimeout(() => {
    el.ask_status.textContent = "资料不足时正在进行针对性补充检索";
    el.ask_answer_text.textContent = "正在搜索并读取与这个问题直接相关的新资料…";
  }, 2200);
  try {
    const answer = await (await request(`/api/persons/${state.activePersonId}/ask`, {
      method: "POST", body: JSON.stringify({ question }),
    })).json();
    el.ask_answer_text.textContent = answer.answer;
    if (answer.research?.triggered) {
      const count = Number(answer.research.new_documents || 0);
      el.ask_answer_meta.hidden = false;
      el.ask_answer_meta.textContent = count
        ? `已针对这个问题补充检索，并新增 ${count} 篇资料。`
        : answer.research.status === "search_unavailable"
          ? "现有人物库资料不足，补充检索暂时不可用。"
          : "已完成针对性补充检索，暂未找到可读取的新资料。";
    }
    (answer.sources || []).forEach((source) => {
      const link = node("a", "", source.title || "打开原文");
      link.href = source.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      el.ask_answer_sources.append(link);
    });
  } catch (error) {
    el.ask_answer_text.textContent = error.message;
    notice(error.message, "error");
  } finally {
    window.clearTimeout(researchHint);
    el.ask_answer.classList.remove("is-loading");
    el.ask_button.disabled = false;
    el.ask_button.textContent = "↑";
    el.ask_status.textContent = "先查人物库，必要时自动补充检索";
  }
}

async function openExisting(person) {
  try {
    const report = await (await request(`/api/persons/${person.id}/report`)).json();
    renderReport(report, null, person.id);
  } catch (error) { notice(error.message, "error"); }
}

async function downloadExisting(event, personId) {
  event.preventDefault();
  try {
    const response = await request(`/api/persons/${personId}/export`, { method: "POST" });
    const blob = await response.blob(); const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "人物知识库.zip"; anchor.click(); URL.revokeObjectURL(url);
  } catch (error) { notice(error.message, "error"); }
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = {};
  if (el.brave_key.value.trim()) payload.brave_api_key = el.brave_key.value.trim();
  if (el.deepseek_key.value.trim()) payload.deepseek_api_key = el.deepseek_key.value.trim();
  if (!Object.keys(payload).length) { notice("填写一个 API Key。", "error"); return; }
  try {
    state.config = await (await request("/api/config", { method: "POST", body: JSON.stringify(payload) })).json();
    el.brave_key.value = ""; el.deepseek_key.value = ""; renderConfig();
    notice("已保存。", "info"); el.settings_dialog.close();
  } catch (error) { notice(error.message, "error"); }
}

el.search_form.addEventListener("submit", searchIdentity);
el.manual_source_form.addEventListener("submit", addManualSource);
el.identity_confirm.addEventListener("click", confirmIdentity);
el.identity_back.addEventListener("click", () => { el.identity_panel.hidden = true; document.querySelector(".hero").scrollIntoView({ behavior: "smooth" }); });
el.settings_button.addEventListener("click", () => el.settings_dialog.showModal());
el.settings_close.addEventListener("click", () => el.settings_dialog.close());
el.settings_dialog.addEventListener("click", (event) => { if (event.target === el.settings_dialog) el.settings_dialog.close(); });
el.settings_form.addEventListener("submit", saveSettings);
el.ask_form.addEventListener("submit", askKnowledgeBase);
document.querySelectorAll(".ask-suggestions button").forEach((button) => {
  button.addEventListener("click", () => { el.ask_question.value = button.textContent; el.ask_question.focus(); });
});

const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      entry.target.classList.add("is-visible");
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.08 });
document.querySelectorAll(".reveal").forEach((item) => revealObserver.observe(item));

const hero = document.querySelector(".hero");
hero.addEventListener("pointermove", (event) => {
  const x = (event.clientX / window.innerWidth - .5) * 12;
  const y = (event.clientY / window.innerHeight - .5) * 8;
  hero.style.setProperty("--wave-x", `${x}px`);
  hero.style.setProperty("--wave-y", `${y}px`);
});

Promise.all([loadConfig(), loadPeople()]).catch((error) => notice(error.message, "error"));
