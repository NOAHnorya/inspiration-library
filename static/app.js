const $ = (selector) => document.querySelector(selector);
const state = {
  items: [], selected: new Set(), tags: [], include: new Set(), exclude: new Set(),
  detailId: null, groupItems: [], tagTimer: null,
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {...(options.body ? {"Content-Type": "application/json"} : {}), ...(options.headers || {})},
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || `请求失败 (${response.status})`);
  return data;
}

function toast(text) {
  const element = $("#toast");
  element.textContent = text;
  element.hidden = false;
  clearTimeout(element.timer);
  element.timer = setTimeout(() => { element.hidden = true; }, 2600);
}

function showError(error) {
  const element = $("#message");
  element.textContent = error.message || String(error);
  element.hidden = false;
  setTimeout(() => { element.hidden = true; }, 6000);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  toast("引用已复制");
}

function queryString() {
  const params = new URLSearchParams({limit: "200", semantic: String($("#semantic").checked)});
  const q = $("#query").value.trim();
  if (q) params.set("q", q);
  if ($("#platform").value) params.set("platform", $("#platform").value);
  if ($("#collection").value) params.set("collection", $("#collection").value);
  params.set("match", $("#tagMatch").value);
  state.include.forEach((tag) => params.append("tags", tag));
  state.exclude.forEach((tag) => params.append("exclude", tag));
  return params;
}

async function loadStats() {
  const data = await api("/api/health");
  const stats = data.stats;
  $("#libraryStats").textContent = `${stats.items} 条 · ${stats.assets} 个本地资产 · ${stats.groups} 个组合`;
}

async function loadFilters() {
  const data = await api("/api/filters");
  for (const [id, values] of [["platform", data.platforms], ["collection", data.collections]]) {
    const select = $("#" + id);
    const current = select.value;
    select.innerHTML = `<option value="">${id === "platform" ? "全部平台" : "全部收藏夹"}</option>` +
      values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
    select.value = current;
  }
}

async function loadTags() {
  state.tags = await api("/api/tags?query=" + encodeURIComponent($("#tagFilter").value.trim()));
  renderTags();
}

function renderTags() {
  const container = $("#tagList");
  let category = "";
  container.innerHTML = state.tags.map((tag) => {
    const heading = tag.category !== category ? `<div class="tag-category">${escapeHtml(tag.category)}</div>` : "";
    category = tag.category;
    return `${heading}<div class="tag-row">
      <span class="tag-name" title="${escapeHtml(tag.name)}">${escapeHtml(tag.name)}</span>
      <span class="tag-count">${tag.count}</span>
      <button class="tag-add ${state.include.has(tag.name) ? "active" : ""}" data-tag-action="include" data-tag="${escapeHtml(tag.name)}" title="包含标签">+</button>
      <button class="tag-remove ${state.exclude.has(tag.name) ? "active" : ""}" data-tag-action="exclude" data-tag="${escapeHtml(tag.name)}" title="排除标签">−</button>
    </div>`;
  }).join("");
}

function renderActiveFilters() {
  const chips = [];
  state.include.forEach((tag) => chips.push(`<span class="filter-chip">${escapeHtml(tag)}<button data-remove-tag="${escapeHtml(tag)}" data-kind="include">×</button></span>`));
  state.exclude.forEach((tag) => chips.push(`<span class="filter-chip excluded">排除 ${escapeHtml(tag)}<button data-remove-tag="${escapeHtml(tag)}" data-kind="exclude">×</button></span>`));
  $("#activeFilters").innerHTML = chips.join("");
}

async function search() {
  $("#message").hidden = true;
  $("#resultCount").textContent = "…";
  try {
    const data = await api("/api/items?" + queryString());
    state.items = data.items;
    $("#resultCount").textContent = data.total;
    renderItems();
  } catch (error) {
    showError(error);
    state.items = [];
    renderItems();
  }
}

function cardTemplate(item) {
  const selected = state.selected.has(item.id);
  const cover = item.cover ? `<img class="cover" src="${escapeHtml(item.cover)}" alt="${escapeHtml(item.title)}" loading="lazy">` :
    `<div class="no-cover">封面待补充</div>`;
  return `<article class="card ${selected ? "selected" : ""}" data-item="${escapeHtml(item.id)}">
    <label class="select-card" title="选择素材"><input class="select-item" type="checkbox" data-id="${escapeHtml(item.id)}" ${selected ? "checked" : ""}></label>
    <button class="cover-button" data-detail="${escapeHtml(item.id)}">${cover}</button>
    <div class="card-body">
      <button class="cover-button" data-detail="${escapeHtml(item.id)}"><div class="card-title">${escapeHtml(item.title)}</div></button>
      <div class="card-meta">${escapeHtml(item.author || item.platform)} · ${escapeHtml(item.collection || item.platform)}</div>
      <div class="card-tags">${item.tag_names.slice(0,4).map((tag) => `<span class="small-tag">${escapeHtml(tag)}</span>`).join("")}</div>
    </div>
  </article>`;
}

function renderItems() {
  $("#results").innerHTML = state.items.map(cardTemplate).join("");
  $("#empty").hidden = state.items.length !== 0;
  updateSelection();
}

function updateSelection() {
  const count = state.selected.size;
  $("#selectionCount").textContent = count ? `· 已选 ${count} 条` : "";
  $("#copyRefs").disabled = count === 0;
  $("#groupSelected").disabled = count === 0;
  $("#compareSelected").disabled = count < 2 || count > 5;
  $("#briefSelected").disabled = count < 2 || count > 5;
  document.querySelectorAll(".card").forEach((card) => {
    card.classList.toggle("selected", state.selected.has(card.dataset.item));
  });
}

function tagEditor(item) {
  return item.tags.map((tag) => `<div class="edit-tag">
    <span class="name">${escapeHtml(tag.name)} <span class="muted">${escapeHtml(tag.category)} · ${tag.source === "manual" ? "人工" : "自动"} ${Math.round(tag.confidence * 100)}%</span></span>
    <button type="button" class="${tag.locked ? "locked" : ""}" data-lock="${escapeHtml(tag.name)}" data-locked="${tag.locked}">${tag.locked ? "已锁定" : "锁定"}</button>
    <button type="button" data-delete-tag="${escapeHtml(tag.name)}" aria-label="删除标签">×</button>
  </div>`).join("");
}

async function openDetail(itemId) {
  try {
    const item = await api("/api/items/" + encodeURIComponent(itemId));
    state.detailId = item.id;
    const useCases = (item.annotation.use_cases || []).join("，");
    $("#detailContent").innerHTML = `<div class="detail-layout">
      <div>
        ${item.cover ? `<img class="detail-cover" src="${escapeHtml(item.cover)}" alt="${escapeHtml(item.title)}">` : `<div class="no-cover">封面待补充</div>`}
        <div class="detail-section"><span class="reference">@${escapeHtml(item.id)}</span></div>
        <div class="detail-actions"><button class="secondary" type="button" id="copyDetailRef">复制引用</button><button class="secondary" type="button" id="findSimilar">找相似</button><button class="secondary" type="button" id="retryCover" ${item.import_status === "ready" ? "hidden" : ""}>重试封面</button></div>
      </div>
      <div>
        <h2 class="detail-title">${escapeHtml(item.title)}</h2>
        <div class="detail-meta">${escapeHtml(item.author || "未知作者")} · ${escapeHtml(item.platform)}<br>收藏夹：${escapeHtml(item.collection || "无")}<br>状态：${escapeHtml(item.import_status)}</div>
        <div class="detail-section"><a class="source-link" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">打开原始素材</a></div>
        <form id="detailForm" class="detail-form">
          <div class="detail-section"><h3>个人备注</h3><textarea id="detailNotes" rows="4">${escapeHtml(item.notes)}</textarea></div>
          <div class="detail-section"><h3>解读摘要</h3><input id="detailSummary" value="${escapeHtml(item.annotation.summary || "")}"></div>
          <div class="detail-section"><h3>创新点</h3><textarea id="detailInnovation" rows="3">${escapeHtml(item.annotation.innovation || "")}</textarea></div>
          <div class="detail-section"><h3>适用场景（逗号分隔）</h3><input id="detailUseCases" value="${escapeHtml(useCases)}"></div>
          <div class="detail-section"><h3>标签</h3><div class="edit-tags">${tagEditor(item)}</div>
            <div class="add-tag-row"><input id="newTag" placeholder="新增自定义标签"><button type="button" class="secondary" id="addTag">添加</button></div>
          </div>
          <div class="detail-actions"><button class="primary" type="submit">保存并更新索引</button><button class="secondary" type="button" id="regenerate">重新生成解读</button></div>
        </form>
      </div>
    </div>`;
    $("#detailDialog").showModal();
    bindDetail(item);
  } catch (error) { showError(error); }
}

async function refreshDetail() {
  const id = state.detailId;
  $("#detailDialog").close();
  await openDetail(id);
  await Promise.all([search(), loadTags()]);
}

function bindDetail(item) {
  $("#copyDetailRef").onclick = () => copyText("@" + item.id);
  $("#findSimilar").onclick = () => findSimilar(item.id);
  $("#detailForm").onsubmit = async (event) => {
    event.preventDefault();
    const useCases = $("#detailUseCases").value.split(/[,，]/).map((v) => v.trim()).filter(Boolean);
    await api("/api/items/" + item.id, {method: "PATCH", body: JSON.stringify({
      notes: $("#detailNotes").value,
      annotation: {summary: $("#detailSummary").value, innovation: $("#detailInnovation").value, use_cases: useCases},
    })});
    toast("已保存并更新索引");
    await refreshDetail();
  };
  $("#addTag").onclick = async () => {
    const name = $("#newTag").value.trim();
    if (!name) return;
    await api("/api/items/" + item.id, {method: "PATCH", body: JSON.stringify({add_tags: [name]})});
    await refreshDetail();
  };
  document.querySelectorAll("[data-delete-tag]").forEach((button) => {
    button.onclick = async () => {
      await api("/api/items/" + item.id, {method: "PATCH", body: JSON.stringify({remove_tags: [button.dataset.deleteTag]})});
      await refreshDetail();
    };
  });
  document.querySelectorAll("[data-lock]").forEach((button) => {
    button.onclick = async () => {
      const locked = button.dataset.locked === "1";
      await api("/api/items/" + item.id, {method: "PATCH", body: JSON.stringify(locked ? {unlock_tags: [button.dataset.lock]} : {lock_tags: [button.dataset.lock]})});
      await refreshDetail();
    };
  });
  $("#regenerate").onclick = async () => {
    await api("/api/items/" + item.id + "/annotate?regenerate=true", {method: "POST"});
    toast("自动解读已更新，人工锁定内容已保留");
    await refreshDetail();
  };
  $("#retryCover").onclick = async () => {
    const result = await api("/api/items/" + item.id + "/retry-cover", {method: "POST"});
    toast(result.ok ? "封面已保存" : "封面仍无法下载，请手动补充");
    await refreshDetail();
  };
}

function openTextDialog(title, content) {
  $("#textDialogTitle").textContent = title;
  $("#textDialogContent").innerHTML = content;
  $("#textDialog").showModal();
}

async function findSimilar(itemId) {
  try {
    const data = await api("/api/items/" + encodeURIComponent(itemId) + "/similar?limit=10");
    const cards = data.items.map((item) => `<article class="card similar-item" data-similar-id="${escapeHtml(item.id)}">
      ${item.cover ? `<img class="cover" src="${escapeHtml(item.cover)}" alt="${escapeHtml(item.title)}">` : `<div class="no-cover">封面待补充</div>`}
      <div class="card-body"><div class="card-title">${escapeHtml(item.title)}</div><div class="similar-score">视觉相似度 ${Math.round(item.visual_score * 100)}%</div></div>
    </article>`).join("");
    if ($("#detailDialog").open) $("#detailDialog").close();
    openTextDialog("视觉相似素材", `<p class="muted">颜色分布与布局特征 · 标签筛选可复用当前检索条件</p><div class="grid">${cards}</div>`);
    document.querySelectorAll("[data-similar-id]").forEach((card) => {
      card.onclick = () => { $("#textDialog").close(); openDetail(card.dataset.similarId); };
    });
  } catch (error) { showError(error); }
}

async function compareSelected() {
  try {
    const data = await api("/api/agent/compare", {method: "POST", body: JSON.stringify({ids: [...state.selected]})});
    const shared = data.shared_tags.length ? data.shared_tags.map(escapeHtml).join("、") : "没有共同标签";
    const cards = data.items.map((item) => `<div class="comparison-card"><h4>${escapeHtml(item.title)}</h4>
      <div class="reference">${escapeHtml(item.reference)}</div><p>${escapeHtml(item.distinctive_tags.join("、") || "无独有标签")}</p>
      <a class="source-link" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">原始证据</a></div>`).join("");
    openTextDialog("灵感对比", `<div class="comparison-section"><h3>共同特征</h3><p>${shared}</p></div>${cards}`);
  } catch (error) { showError(error); }
}

async function briefSelected() {
  const goal = window.prompt("这次创作目标（可选）", "");
  if (goal === null) return;
  try {
    const data = await api("/api/agent/brief", {method: "POST", body: JSON.stringify({ids: [...state.selected], goal})});
    openTextDialog("组合引用", `<div class="brief-text">${escapeHtml(data.text)}</div><div class="detail-actions"><button id="copyBrief" class="primary">复制参考说明</button></div>`);
    $("#copyBrief").onclick = () => copyText(data.text);
  } catch (error) { showError(error); }
}

async function openGroupDialog(itemIds, existing = null) {
  state.groupItems = [...itemIds];
  $("#groupId").value = existing?.id || "";
  $("#groupName").value = existing?.name || "";
  $("#groupDescription").value = existing?.description || "";
  $("#groupDialogTitle").textContent = existing ? "编辑灵感组合" : "保存灵感组合";
  await renderGroupItems();
  $("#groupDialog").showModal();
}

async function renderGroupItems() {
  const items = await Promise.all(state.groupItems.map((id) => api("/api/items/" + encodeURIComponent(id))));
  $("#groupItems").innerHTML = items.map((item, index) => `<div class="sortable-item">
    <span class="title">${escapeHtml(item.title)}</span><span class="muted">${index + 1}</span>
    <button type="button" data-move="up" data-index="${index}" ${index === 0 ? "disabled" : ""}>↑</button>
    <button type="button" data-move="down" data-index="${index}" ${index === items.length - 1 ? "disabled" : ""}>↓</button>
    <button type="button" data-remove-index="${index}" aria-label="移出组合">×</button>
  </div>`).join("");
  document.querySelectorAll("[data-move]").forEach((button) => {
    button.onclick = async () => {
      const index = Number(button.dataset.index);
      const next = button.dataset.move === "up" ? index - 1 : index + 1;
      [state.groupItems[index], state.groupItems[next]] = [state.groupItems[next], state.groupItems[index]];
      await renderGroupItems();
    };
  });
  document.querySelectorAll("[data-remove-index]").forEach((button) => {
    button.onclick = async () => { state.groupItems.splice(Number(button.dataset.removeIndex), 1); await renderGroupItems(); };
  });
}

async function loadGroups() {
  const data = await api("/api/groups");
  $("#groupsList").innerHTML = data.length ? data.map((group) => `<div class="group-row"><div class="info"><h3>${escapeHtml(group.name)}</h3><p>${group.item_count} 条素材 · ${escapeHtml(group.description || "无说明")}</p></div><button class="secondary" data-open-group="${escapeHtml(group.id)}">打开与排序</button></div>`).join("") : `<div class="empty">还没有命名组合。先在图库中选择素材。</div>`;
  $("#groupsDialog").showModal();
  document.querySelectorAll("[data-open-group]").forEach((button) => {
    button.onclick = async () => {
      const group = await api("/api/groups/" + button.dataset.openGroup);
      $("#groupsDialog").close();
      await openGroupDialog(group.item_ids, group);
    };
  });
}

async function loadImports() {
  const data = await api("/api/imports?limit=50");
  $("#importRecords").innerHTML = data.map((record) => `<div class="import-row"><span class="status-${escapeHtml(record.status)}">${escapeHtml(record.status)}</span> · ${escapeHtml(record.source_type)}<div class="source">${escapeHtml(record.source_value)}</div>${record.error ? `<div class="source">${escapeHtml(record.error)}</div>` : ""}</div>`).join("");
  $("#importsDialog").showModal();
}

async function submitImport(formId, endpoint, valueKey, inputId) {
  $(formId).onsubmit = async (event) => {
    event.preventDefault();
    const button = event.target.querySelector("button");
    button.disabled = true;
    try {
      const result = await api(endpoint, {method: "POST", body: JSON.stringify({[valueKey]: $(inputId).value.trim()})});
      toast(`导入完成：${result.status || "已处理"}${result.count !== undefined ? ` ${result.count} 条` : ""}`);
      await Promise.all([loadStats(), loadFilters(), loadTags(), search(), loadImports()]);
    } catch (error) { showError(error); }
    finally { button.disabled = false; }
  };
}

$("#searchForm").onsubmit = (event) => { event.preventDefault(); search(); };
$("#platform").onchange = search;
$("#collection").onchange = search;
$("#tagMatch").onchange = search;
$("#semantic").onchange = search;
$("#tagFilter").oninput = () => { clearTimeout(state.tagTimer); state.tagTimer = setTimeout(loadTags, 180); };
$("#tagList").onclick = (event) => {
  const button = event.target.closest("[data-tag-action]");
  if (!button) return;
  const tag = button.dataset.tag;
  const include = button.dataset.tagAction === "include";
  const primary = include ? state.include : state.exclude;
  const other = include ? state.exclude : state.include;
  if (primary.has(tag)) primary.delete(tag); else { primary.add(tag); other.delete(tag); }
  renderTags(); renderActiveFilters(); search();
};
$("#activeFilters").onclick = (event) => {
  const button = event.target.closest("[data-remove-tag]");
  if (!button) return;
  state[button.dataset.kind].delete(button.dataset.removeTag);
  renderTags(); renderActiveFilters(); search();
};
$("#results").onchange = (event) => {
  if (!event.target.classList.contains("select-item")) return;
  if (event.target.checked) state.selected.add(event.target.dataset.id); else state.selected.delete(event.target.dataset.id);
  updateSelection();
};
$("#results").onclick = (event) => {
  const button = event.target.closest("[data-detail]");
  if (button) openDetail(button.dataset.detail);
};
$("#copyRefs").onclick = () => copyText([...state.selected].map((id) => "@" + id).join(" "));
$("#compareSelected").onclick = compareSelected;
$("#briefSelected").onclick = briefSelected;
$("#groupSelected").onclick = () => openGroupDialog([...state.selected]);
$("#openGroups").onclick = loadGroups;
$("#openImports").onclick = loadImports;
$("#groupForm").onsubmit = async (event) => {
  event.preventDefault();
  const id = $("#groupId").value;
  const payload = {name: $("#groupName").value, description: $("#groupDescription").value, item_ids: state.groupItems};
  await api(id ? "/api/groups/" + id : "/api/groups", {method: id ? "PUT" : "POST", body: JSON.stringify(payload)});
  $("#groupDialog").close();
  toast("组合已保存");
  loadStats();
};

async function healthCheck() {
  const data = await api("/api/maintenance/health");
  const report = {ok: data.ok, issues: data.issues, duplicate_urls: data.duplicate_urls,
    semantic_vectors_missing: data.semantic_vectors_missing, visual_vectors_missing: data.visual_vectors_missing};
  $("#maintenanceResult").innerHTML = `<p><strong>${data.ok ? "检查通过" : "发现待处理项"}</strong> · ${data.stats.items} 条素材 · ${data.stats.assets} 个资产</p><pre>${escapeHtml(JSON.stringify(report, null, 2))}</pre>`;
}

$("#openMaintenance").onclick = async () => {
  $("#maintenanceDialog").showModal();
  await healthCheck();
};
$("#runHealth").onclick = healthCheck;
$("#runReindex").onclick = async () => {
  const button = $("#runReindex");
  button.disabled = true;
  try {
    const result = await api("/api/maintenance/reindex", {method: "POST"});
    toast(`已重建 ${result.items} 条索引`);
    await healthCheck();
    await Promise.all([loadTags(), search()]);
  } finally { button.disabled = false; }
};
$("#runBackup").onclick = async () => {
  const button = $("#runBackup");
  button.disabled = true;
  try {
    const result = await api("/api/maintenance/backup", {method: "POST", body: "{}"});
    $("#maintenanceResult").innerHTML = `<p><strong>备份完成</strong></p><pre>${escapeHtml(result.path)}\n${result.bytes} 字节</pre>`;
  } finally { button.disabled = false; }
};

document.querySelectorAll("[data-close]").forEach((button) => { button.onclick = () => $("#" + button.dataset.close).close(); });
submitImport("#importUrlForm", "/api/import/url", "url", "#importUrl");
submitImport("#importFileForm", "/api/import/file", "path", "#importFile");
submitImport("#importXhsForm", "/api/import/xhs", "path", "#importXhs");
submitImport("#importDouyinForm", "/api/import/douyin", "path", "#importDouyin");

Promise.all([loadStats(), loadFilters(), loadTags(), search()]).catch(showError);
