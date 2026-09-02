const state = {
  config: null,
  people: [],
  pendingPerson: null,
  preview: null,
  manualSources: [],
  anchors: [],
  languageMode: "zh",
  activePersonId: null,
  manualEditingSource: null,
  dossierEditingSource: null,
  noticeTimer: null,
};

const el = Object.fromEntries([
  "search-form", "search-button", "person-name", "identity-anchors", "language-mode",
  "landing-page", "enter-workbench", "workbench-shell",
  "config-hint", "config-light", "identity-panel", "identity-platform", "identity-title",
  "identity-snippet", "identity-link", "preview-platforms", "identity-canonical-name", "identity-back", "identity-confirm",
  "manual-source-form", "manual-source-url", "manual-source-clear", "manual-source-submit", "manual-source-list", "progress-panel",
  "progress-person", "progress-percent", "progress-bar", "progress-stage", "result-panel",
  "result-title", "result-language", "result-profiles", "result-sources", "result-overview",
  "result-identity", "result-accomplishments", "result-viewpoints", "result-evolution",
  "result-external", "result-timeline", "portrait-section", "result-images", "download-link",
  "ask-form", "ask-question", "ask-button", "ask-status", "ask-answer", "ask-answer-meta",
  "ask-answer-text", "ask-answer-sources", "person-count", "person-list",
  "dossier-source-form", "dossier-source-url", "dossier-source-clear", "dossier-source-button", "dossier-source-status",
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

function confirmSourceRemoval(actions, onConfirm) {
  const original = [...actions.childNodes];
  const question = node("span", "source-remove-question", "确定移除？");
  const confirm = node("button", "source-remove-confirm", "确定移除");
  confirm.type = "button";
  const cancel = node("button", "source-remove-cancel", "取消");
  cancel.type = "button";
  cancel.addEventListener("click", () => actions.replaceChildren(...original));
  confirm.addEventListener("click", async () => {
    confirm.disabled = true;
    cancel.disabled = true;
    try {
      await onConfirm();
    } catch (error) {
      actions.replaceChildren(...original);
      notice(error.message, "error");
    }
  });
  actions.replaceChildren(question, confirm, cancel);
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
    const actions = node("div", "person-actions");
    const open = node("button", "", "打开档案 →");
    open.type = "button";
    open.addEventListener("click", () => openExisting(person));
    const update = node("button", "", "补充资料 +");
    update.type = "button";
    update.addEventListener("click", async () => {
      await openExisting(person);
      el.dossier_source_url.focus();
      el.dossier_source_form.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    actions.append(open, update);
    row.append(copy, count, actions);
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
  const canonicalName = state.preview.canonical_name || state.pendingPerson.name;
  el.identity_canonical_name.textContent = canonicalName === state.pendingPerson.name
    ? `档案姓名：${canonicalName}`
    : `确认后将姓名修正为：${canonicalName}`;
  renderManualSources();
  el.identity_panel.hidden = false;
  el.identity_panel.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderManualSources() {
  el.manual_source_list.replaceChildren();
  state.manualSources.forEach((source, index) => {
    const item = node("div", "manual-source-item");
    item.classList.toggle("is-editing", state.manualEditingSource === source);
    const copy = node("div", "manual-source-copy");
    copy.append(node("strong", "", source.draft ? "待加入" : "已加入"), node("span", "", source.url));
    const actions = node("div", "manual-source-actions");
    const reedit = node("button", "", "重新填写");
    reedit.type = "button";
    reedit.addEventListener("click", () => beginManualSourceEdit(source));
    const remove = node("button", "", "移除");
    remove.type = "button";
    remove.addEventListener("click", () => confirmSourceRemoval(actions, () => removeManualSource(index)));
    actions.append(reedit, remove);
    item.append(copy, actions);
    el.manual_source_list.append(item);
  });
}

function resetManualSourceEditor() {
  state.manualEditingSource = null;
  el.manual_source_url.value = "";
  el.manual_source_clear.textContent = "清空";
  el.manual_source_submit.innerHTML = "添加信息源 <span>+</span>";
  renderManualSources();
}

function beginManualSourceEdit(source) {
  state.manualEditingSource = source;
  el.manual_source_url.value = source.url;
  el.manual_source_clear.textContent = "取消修改";
  el.manual_source_submit.innerHTML = "保存修改 <span>→</span>";
  el.manual_source_url.focus();
  renderManualSources();
}

async function removeManualSource(index) {
  const source = state.manualSources[index];
  if (!source) return;
  if (source.id) await request(`/api/sources/${source.id}`, { method: "DELETE" });
  state.manualSources.splice(index, 1);
  if (state.manualEditingSource === source) resetManualSourceEditor();
  else renderManualSources();
  notice("信息源已移除。", "info");
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
    state.manualSources = await Promise.all(state.manualSources.map(async (source) => {
      return (await request(`/api/persons/${state.pendingPerson.id}/sources`, {
        method: "POST", body: JSON.stringify({ url: source.url }),
      })).json();
    }));
    state.preview = await (await request(`/api/persons/${state.pendingPerson.id}/prepare`, {
      method: "POST", body: JSON.stringify({ anchors: state.anchors }),
    })).json();
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
  const url = el.manual_source_url.value.trim();
  if (!url) return;
  const editing = state.manualEditingSource;
  if (state.manualSources.some((item) => item !== editing && item.url === url)) {
    notice("这个网址已经加入。", "error");
    return;
  }
  if (editing) {
    try {
      if (editing.id) {
        const updated = await (await request(`/api/sources/${editing.id}`, {
          method: "PATCH", body: JSON.stringify({ url }),
        })).json();
        Object.assign(editing, updated);
      } else {
        editing.url = url;
      }
      resetManualSourceEditor();
      notice("网址修改已保存。", "info");
    } catch (error) { notice(error.message, "error"); }
    return;
  }
  if (!state.pendingPerson) {
    state.manualSources.push({ url, draft: true });
    el.manual_source_url.value = "";
    renderManualSources();
    notice("网址已暂存，确认人物后会一起加入。", "info");
    return;
  }
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

function enterWorkbench(target = ".hero") {
  el.landing_page.hidden = true;
  el.workbench_shell.hidden = false;
  document.body.classList.add("workbench-visible");
  window.requestAnimationFrame(() => {
    const destination = document.querySelector(target) || document.querySelector(".hero");
    destination.scrollIntoView({ behavior: "smooth", block: "start" });
  });
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
  const canonicalName = state.preview.canonical_name || state.pendingPerson.name;
  state.pendingPerson.name = canonicalName;
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
        confirmed_name: canonicalName,
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
  state.dossierEditingSource = null;
  el.dossier_source_url.value = "";
  el.dossier_source_clear.textContent = "清空";
  el.dossier_source_button.innerHTML = "添加并更新 <span>→</span>";
  el.dossier_source_status.textContent = "";
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
  // Keep every ingested URL in this list even when it also has a profile card;
  // this is the single place where users can correct or remove stored sources.
  const sourceItems = content.public_sources || [];
  fillList(el.result_sources, sourceItems, "没有其他收录资料。", (item) => {
    const row = node("div", "source-row");
    row.append(node("span", "", item.platform || "公开资料"), node("strong", "", item.title));
    const actions = node("div", "source-row-actions");
    const link = node("a", "", "打开原文 ↗"); link.href = item.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    actions.append(link);
    if (item.source_id) {
      const reedit = node("button", "", "重新填写");
      reedit.type = "button";
      reedit.addEventListener("click", () => {
        state.dossierEditingSource = item;
        el.dossier_source_url.value = item.url;
        el.dossier_source_clear.textContent = "取消修改";
        el.dossier_source_button.innerHTML = "保存并重新整理 <span>→</span>";
        el.dossier_source_url.focus();
        el.dossier_source_form.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      const remove = node("button", "", "移除");
      remove.type = "button";
      remove.addEventListener("click", () => {
        confirmSourceRemoval(actions, async () => {
          await request(`/api/sources/${item.source_id}`, { method: "DELETE" });
          row.remove();
          [...el.result_profiles.querySelectorAll("a")].forEach((profile) => {
            if (profile.href === new URL(item.url, window.location.href).href) profile.remove();
          });
          notice("来源及其正文已移除。补充正确网址后重新整理即可更新结论。", "info");
        });
      });
      actions.append(reedit, remove);
    }
    row.append(actions); return row;
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

async function refreshDossier(event) {
  event.preventDefault();
  const url = el.dossier_source_url.value.trim();
  if (!url || !state.activePersonId) return;
  if (!state.config?.llm_configured) {
    el.settings_dialog.showModal();
    notice("连接 DeepSeek 后即可重新整理档案。", "error");
    return;
  }
  const person = state.people.find((item) => item.id === state.activePersonId);
  state.pendingPerson = person || { id: state.activePersonId, name: el.result_title.textContent };
  el.dossier_source_button.disabled = true;
  el.dossier_source_status.textContent = "正在读取新资料并重新整理整份档案…";
  el.result_panel.hidden = true;
  el.progress_panel.hidden = false;
  updateProgress({ progress: 0, stage: "准备补充最新资料", status: "queued" });
  el.progress_panel.scrollIntoView({ behavior: "smooth", block: "center" });
  try {
    if (state.dossierEditingSource) {
      await request(`/api/sources/${state.dossierEditingSource.source_id}`, {
        method: "PATCH", body: JSON.stringify({ url }),
      });
    }
    const job = await (await request(`/api/persons/${state.activePersonId}/refresh`, {
      method: "POST",
      body: JSON.stringify({ urls: [url] }),
    })).json();
    await pollJob(job.id);
    el.dossier_source_url.value = "";
    state.dossierEditingSource = null;
    el.dossier_source_clear.textContent = "清空";
    el.dossier_source_button.innerHTML = "添加并更新 <span>→</span>";
    el.dossier_source_status.textContent = "已加入新资料并更新档案。";
  } catch (error) {
    el.progress_panel.hidden = true;
    el.result_panel.hidden = false;
    el.dossier_source_status.textContent = error.message;
    notice(error.message, "error");
  } finally {
    el.dossier_source_button.disabled = false;
  }
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
el.person_name.addEventListener("input", () => {
  if (!state.pendingPerson || el.person_name.value.trim() === state.pendingPerson.name) return;
  state.pendingPerson = null;
  state.preview = null;
  state.manualSources = [];
  renderManualSources();
});
el.manual_source_form.addEventListener("submit", addManualSource);
el.manual_source_clear.addEventListener("click", () => { resetManualSourceEditor(); el.manual_source_url.focus(); });
el.dossier_source_form.addEventListener("submit", refreshDossier);
el.dossier_source_clear.addEventListener("click", () => {
  state.dossierEditingSource = null;
  el.dossier_source_url.value = "";
  el.dossier_source_clear.textContent = "清空";
  el.dossier_source_button.innerHTML = "添加并更新 <span>→</span>";
  el.dossier_source_url.focus();
});
el.enter_workbench.addEventListener("click", () => enterWorkbench());
document.querySelectorAll('.site-nav a[href="#search-form"], .site-nav a[href="#recent-title"]').forEach((link) => {
  link.addEventListener("click", (event) => {
    if (!el.workbench_shell.hidden) return;
    event.preventDefault();
    enterWorkbench(link.getAttribute("href"));
  });
});
document.querySelector('.site-nav a[href="#landing-page"]').addEventListener("click", (event) => {
  event.preventDefault();
  el.workbench_shell.hidden = true;
  el.landing_page.hidden = false;
  document.body.classList.remove("workbench-visible");
  el.landing_page.scrollIntoView({ behavior: "smooth", block: "start" });
});
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
