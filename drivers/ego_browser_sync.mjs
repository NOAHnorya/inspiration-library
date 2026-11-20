// Runs inside `ego-browser nodejs`. Python prepends `const P = {...};` with:
// spaceName, platform, url, collection, accountMarker, boardId, knownIds,
// blockTerms, loginTerms, maxRounds, stopAfterKnown, stopAfterUnchanged.
// Read-only: it opens one collection page, scrolls and reads what is shown.
//
// Page callbacks cannot see Node variables, so each one is self-contained.
// Task-space tabs may run in the background, where innerText can be empty:
// callbacks read textContent instead.
const emit = (kind, value) => console.log(`__INSPIRATION_${kind}__` + JSON.stringify(value));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const known = new Set(P.knownIds);
const idOf = (url) => {
  const video = String(url).match(/\/(?:video|note)\/(\d+)/);
  if (video) return video[1];
  const notes = String(url).match(/\/([0-9a-f]{24})(?=\/|$|\?)/g) || [];
  return notes.length ? notes.at(-1).slice(1) : "";
};
const fail = (message, kind) => Object.assign(new Error(message), { kind });

function readPageState(terms) {
  const root = document.body || document.documentElement;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(node.parentElement?.tagName || "")
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const parts = [];
  let length = 0;
  while (walker.nextNode() && length < 60000) {
    const value = walker.currentNode.nodeValue.trim();
    if (value) {
      parts.push(value);
      length += value.length;
    }
  }
  const text = parts.join("\n");
  return {
    block: terms.block.some((term) => text.includes(term)),
    login: terms.login.some((term) => text.includes(term)),
    offline: text.includes("未连接到服务器"),
    text,
  };
}

function extractDouyin() {
  const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
  const linkSelector = 'a[href*="/video/"], a[href*="/note/"]';
  const count = (element) => element.querySelectorAll(linkSelector).length;
  const lists = [...document.querySelectorAll('ul[data-e2e="scroll-list"]')];
  const candidates = lists.length ? lists : [...document.querySelectorAll("ul")];
  const root = candidates.sort((a, b) => count(b) - count(a))[0];
  if (!root) return [];
  const out = [];
  const seen = new Set();
  for (const anchor of root.querySelectorAll(linkSelector)) {
    const match = anchor.href.match(/douyin\.com\/(video|note)\/(\d+)/);
    if (!match || seen.has(match[2])) continue;
    seen.add(match[2]);
    const card = anchor.closest("li") || anchor;
    const image = card.querySelector("img");
    const alt = clean(image?.alt);
    let cover = image ? image.currentSrc || image.src || image.getAttribute("data-src") || "" : "";
    if (cover.startsWith("data:")) cover = "";
    const leaves = [...card.querySelectorAll("*")]
      .filter((element) => !element.children.length && !/^(SCRIPT|STYLE|svg|path|use)$/i.test(element.tagName))
      .map((element) => clean(element.textContent))
      .filter((text) => text && !/^[\d.]+万?$/.test(text));
    const visible = leaves.sort((a, b) => b.length - a.length)[0] || "";
    let author = "";
    let title = visible;
    const split = alt.indexOf("：");
    if (split > 0) {
      author = alt.slice(0, split);
      if (!title) title = alt.slice(split + 1);
    } else if (!title) {
      title = alt;
    }
    out.push({ url: `https://www.douyin.com/${match[1]}/${match[2]}`, title, author, cover,
      raw: { alt, visible_title: visible } });
  }
  return out;
}

function extractXhs(boardId) {
  const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
  const pattern = new RegExp("/board/" + boardId + "/([0-9a-f]{24})");
  const items = new Map();
  for (const anchor of document.querySelectorAll("a[href]")) {
    const match = anchor.href.match(pattern);
    if (!match) continue;
    const card = anchor.closest("section.note-item") || anchor.closest("section") || anchor.parentElement;
    const title = clean(card?.querySelector("a.title, .title")?.textContent);
    const author = clean(card?.querySelector(".author .name, .author")?.textContent);
    const image = card?.querySelector("a.cover img, img");
    let cover = image ? image.currentSrc || image.src || "" : "";
    if (cover.startsWith("data:")) cover = "";
    const previous = items.get(match[1]);
    items.set(match[1], {
      url: previous && previous.url.includes("xsec_token") ? previous.url : anchor.href,
      title: previous?.title || title,
      author: previous?.author || author,
      cover: previous?.cover || cover,
    });
  }
  return [...items.values()];
}

function scrollOnce() {
  const anchor = document.querySelector('ul[data-e2e="scroll-list"]') || document.querySelector("section.note-item")
    || document.querySelector("a[href*='/board/']");
  let element = anchor;
  while (element && element !== document.body) {
    const style = getComputedStyle(element);
    if (/(auto|scroll)/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 10) break;
    element = element.parentElement;
  }
  const target = element && element !== document.body ? element : document.scrollingElement;
  const before = target.scrollTop;
  target.scrollBy(0, Math.max(400, target.clientHeight * 0.85));
  return target.scrollTop !== before;
}

function clickByText(name) {
  const target = [...document.querySelectorAll("*")]
    .find((element) => !element.children.length && (element.textContent || "").trim() === name);
  if (!target) return false;
  target.click();
  return true;
}

let task;
let handOff = false;
try {
  task = await taskSpace(P.spaceName);
  const page = task.page("p1");
  try {
    await page.goto(P.url, { timeout: 45000, waitUntil: "domcontentloaded" });
  } catch (error) {
    if (!/committed/.test(String(error.message))) throw error;
  }
  const terms = { block: P.blockTerms, login: P.platform === "xiaohongshu" ? P.loginTerms : [] };
  const safety = async () => {
    const state = await page.evaluate(readPageState, terms);
    if (state.block) throw fail("检测到验证码或风控，已停止操作。请在浏览器中处理后再更新。", "blocked");
    if (state.login) throw fail("小红书登录已失效。请在浏览器中登录，然后重新点击更新。", "needs_login");
    if (state.offline) throw fail("平台页面未能连接服务器，请检查网络后重试。", "failed");
    return state.text;
  };

  if (P.platform === "douyin") {
    let ready = false;
    for (let attempt = 0; attempt < 20 && !ready; attempt++) {
      const text = await safety();
      ready = (!P.accountMarker || text.includes(P.accountMarker)) && text.includes(P.collection);
      if (!ready) await sleep(1500);
    }
    if (!ready) throw fail("抖音收藏夹不可读，请检查浏览器登录状态后重试。", "needs_login");
    try {
      await page.click(`text="${P.collection}"`, { label: "打开收藏夹" });
    } catch (error) {
      if (!(await page.evaluate(clickByText, P.collection))) throw fail("找不到抖音收藏夹：" + P.collection, "failed");
    }
    await page.waitForFunction(() => document.querySelectorAll(
      'ul[data-e2e="scroll-list"] a[href*="/video/"], ul[data-e2e="scroll-list"] a[href*="/note/"]').length > 0,
      undefined, { timeout: 20000 }).catch(() => {});
  } else {
    await page.waitForFunction((id) => document.querySelectorAll(`a[href*="/board/${id}/"]`).length > 0,
      P.boardId, { timeout: 20000 }).catch(() => {});
  }
  await sleep(1500);

  const items = new Map();
  const merge = (current) => {
    for (const item of current) {
      const key = idOf(item.url);
      if (!key) continue;
      const existing = items.get(key);
      if (!existing) items.set(key, item);
      else for (const field of ["title", "author", "cover"]) if (!existing[field] && item[field]) existing[field] = item[field];
    }
  };
  const read = () => P.platform === "douyin" ? page.evaluate(extractDouyin) : page.evaluate(extractXhs, P.boardId);
  let lastFingerprint = "";
  let unchanged = 0;
  let done = false;
  for (let round = 1; round <= P.maxRounds; round++) {
    await safety();
    const current = await read();
    merge(current);
    const ordered = [...items.values()];
    let trailingKnown = 0;
    for (let index = ordered.length - 1; index >= 0 && known.has(idOf(ordered[index].url)); index--) trailingKnown++;
    const fingerprint = current.map((item) => idOf(item.url)).join(",");
    unchanged = fingerprint === lastFingerprint ? unchanged + 1 : 0;
    lastFingerprint = fingerprint;
    emit("PROGRESS", { round, found: ordered.length, new: ordered.filter((item) => !known.has(idOf(item.url))).length });
    if (trailingKnown >= P.stopAfterKnown || unchanged >= P.stopAfterUnchanged) {
      if (!ordered.length) throw fail(P.collection + " 没有读取到作品，页面结构可能已变化", "failed");
      done = true;
      break;
    }
    await page.evaluate(scrollOnce);
    await sleep(2000 + Math.random() * 1000);
  }
  if (!done) throw fail(`${P.collection} 超过 ${P.maxRounds} 次读取仍未到达已知条目，已安全停止`, "failed");
  await sleep(1200);
  merge(await read());
  emit("RESULT", { ok: true, items: [...items.values()] });
} catch (error) {
  handOff = error.kind === "blocked" || error.kind === "needs_login";
  emit("RESULT", { ok: false, kind: error.kind || "failed", error: String(error.message || error) });
} finally {
  if (task) {
    try {
      if (handOff) await task.handOff();
      else await task.finish({ keep: [] });
    } catch (error) {
      console.error("ego-browser cleanup: " + String(error.message || error));
    }
  }
}
