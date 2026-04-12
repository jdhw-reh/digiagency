"use strict";

// ---------------------------------------------------------------------------
// Social Team view
// ---------------------------------------------------------------------------

const SOCIAL_SESSION_KEY = "agency_social_session";

const SOCIAL_STAGES = {
  idle:           { scout: true,  strategise: false, write: false, save: false, copy: false, downloadCsv: false, reset: true  },
  scouting:       { scout: false, strategise: false, write: false, save: false, copy: false, downloadCsv: false, reset: false },
  awaiting_idea:  { scout: false, strategise: true,  write: false, save: false, copy: false, downloadCsv: false, reset: true  },
  strategising:   { scout: false, strategise: false, write: false, save: false, copy: false, downloadCsv: false, reset: false },
  awaiting_copy:  { scout: false, strategise: false, write: true,  save: false, copy: false, downloadCsv: false, reset: true  },
  writing_posts:  { scout: false, strategise: false, write: false, save: false, copy: false, downloadCsv: false, reset: false },
  done:           { scout: true,  strategise: false, write: false, save: true,  copy: true,  downloadCsv: true,  reset: true  },
};

const SOCIAL_STAGE_ACTIVE_PANEL = {
  scouting:      "scout",
  strategising:  "strategist",
  writing_posts: "copywriter",
};

const SOCIAL_PIPELINE_STATE = {
  idle:           { active: 1, completed: [] },
  scouting:       { active: 1, completed: [] },
  awaiting_idea:  { active: 1, completed: [] },
  strategising:   { active: 2, completed: [1] },
  awaiting_copy:  { active: 2, completed: [1] },
  writing_posts:  { active: 3, completed: [1, 2] },
  done:           { active: 3, completed: [1, 2] },
};

// Character limits per platform
const PLATFORM_CHAR_LIMITS = {
  LinkedIn:  3000,
  X:          280,
  Instagram: 2200,
  TikTok:     150,
  YouTube:   5000,
  Facebook:  63206,
  Pinterest:  500,
  Threads:    500,
  Snapchat:   250,
};

// Platform detection from URL hostname
const PLATFORM_HOST_MAP = {
  "instagram.com":   "Instagram",
  "linkedin.com":    "LinkedIn",
  "twitter.com":     "X",
  "x.com":           "X",
  "tiktok.com":      "TikTok",
  "youtube.com":     "YouTube",
  "youtu.be":        "YouTube",
  "facebook.com":    "Facebook",
  "pinterest.com":   "Pinterest",
  "pinterest.co.uk": "Pinterest",
  "threads.net":     "Threads",
  "snapchat.com":    "Snapchat",
};

const PLATFORM_BADGE_CLASS = {
  Instagram: "platform-badge--instagram",
  LinkedIn:  "platform-badge--linkedin",
  X:         "platform-badge--x",
  TikTok:    "platform-badge--tiktok",
  YouTube:   "platform-badge--youtube",
  Facebook:  "platform-badge--facebook",
  Pinterest: "platform-badge--pinterest",
  Threads:   "platform-badge--threads",
  Snapchat:  "platform-badge--snapchat",
};

function detectPlatformFromUrl(url) {
  try {
    const hostname = new URL(url).hostname.replace(/^www\./, "");
    return PLATFORM_HOST_MAP[hostname] || null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const $s = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Mobile carousel helpers
// ---------------------------------------------------------------------------

const SOCIAL_PANEL_ORDER = ['social-panel-scout', 'social-panel-strategist', 'social-panel-copywriter'];

function socialScrollToPanel(panelId) {
  if (!window.matchMedia('(max-width: 480px)').matches) return;
  const grid = document.querySelector('#view-social .panel-grid');
  const panel = document.getElementById(panelId);
  if (!grid || !panel) return;
  grid.scrollTo({ left: panel.offsetLeft, behavior: 'smooth' });
}

function socialUpdateCarouselDots(panelId) {
  if (!window.matchMedia('(max-width: 480px)').matches) return;
  document.querySelectorAll('#social-carousel-dots .carousel-dot').forEach((dot) => {
    dot.classList.toggle('carousel-dot--active', dot.dataset.panel === panelId);
  });
}

function getSocialUi() {
  return {
    profileUrl:        $s("social-profile-url"),
    description:       $s("social-description"),
    platformBadge:     $s("social-platform-badge"),
    btnScout:          $s("social-btn-scout"),
    btnStrategise:     $s("social-btn-strategise"),
    btnWrite:          $s("social-btn-write"),
    btnCopyContent:    $s("social-btn-copy-content"),
    btnDownloadCsv:    $s("social-btn-download-csv"),
    btnSave:           $s("social-btn-save"),
    btnReset:          $s("social-btn-reset"),
    scoutOutput:       $s("social-scout-output"),
    strategistOutput:  $s("social-strategist-output"),
    copywriterStream:  $s("social-copywriter-stream"),
    postsContainer:    $s("social-posts-container"),
    scoutStatus:       $s("social-scout-status"),
    strategistStatus:  $s("social-strategist-status"),
    copywriterStatus:  $s("social-copywriter-status"),
    opportunityList:   $s("social-opportunity-list"),
    savedList:         $s("social-saved-list"),
    postCount:         $s("social-post-count"),
    panelScout:        $s("social-panel-scout"),
    panelStrategist:   $s("social-panel-strategist"),
    panelCopywriter:   $s("social-panel-copywriter"),
  };
}

let sui = null;
let SOCIAL_SESSION_ID = null;
let _socialInitialized = false;

// ---------------------------------------------------------------------------
// Platform badge
// ---------------------------------------------------------------------------

function updatePlatformBadge(platform) {
  if (!sui) return;
  const badge = sui.platformBadge;
  badge.className = "platform-badge";
  if (!platform) {
    badge.textContent = "";
    return;
  }
  const cls = PLATFORM_BADGE_CLASS[platform];
  if (cls) badge.classList.add(cls);
  badge.textContent = platform;
}

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

async function initSocialSession() {
  let sid = localStorage.getItem(SOCIAL_SESSION_KEY);

  if (!sid) {
    const res = await fetch("/api/social/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: window.getAppUserId ? window.getAppUserId() : "" }),
    });
    const data = await res.json();
    sid = data.session_id;
    localStorage.setItem(SOCIAL_SESSION_KEY, sid);
  }

  SOCIAL_SESSION_ID = sid;

  try {
    const state = await fetch(`/api/social/state?session_id=${SOCIAL_SESSION_ID}`).then((r) => r.json());
    restoreSocialState(state);
  } catch (e) {
    console.warn("Could not restore social session state:", e);
  }
}

function restoreSocialState(state) {
  if (!state) return;

  if (state.profile_url) sui.profileUrl.value = state.profile_url;
  if (state.description)  sui.description.value = state.description;

  if (state.detected_platform) {
    updatePlatformBadge(state.detected_platform);
  }

  if (state.calendar) {
    clearSocialEmptyState(sui.strategistOutput);
    sui.strategistOutput.innerHTML = renderMarkdown(state.calendar);
  }

  if (state.opportunities && state.opportunities.length > 0) {
    renderOpportunityList(state.opportunities, state.selected_opportunity);
    sui.panelScout.classList.add("topics-ready");
    if (state.selected_opportunity) {
      const idx = state.opportunities.findIndex(
        (o) => o.angle === state.selected_opportunity.angle
      );
      if (idx >= 0) selectOpportunityCard(idx);
    }
  }

  if (state.posts && state.posts.length > 0) {
    const n = state.posts.length;
    sui.copywriterStream.innerHTML = `<p style="color:var(--text-muted);font-style:italic">✓ ${n} post${n !== 1 ? "s" : ""} written</p>`;
    renderPostCards(state.posts);
    sui.panelCopywriter.classList.add("posts-ready");
    sui.postCount.textContent = `${n} posts`;
  }

  if (state.saved_posts && state.saved_posts.length > 0) {
    state.saved_posts.forEach((p) => addSavedPost(p.platform, p.url));
  }

  const safeStage = ["scouting", "strategising", "writing_posts"].includes(state.stage)
    ? "idle"
    : state.stage || "idle";
  setSocialStage(safeStage);
}

// ---------------------------------------------------------------------------
// Stage machine
// ---------------------------------------------------------------------------

function setSocialStage(stage) {
  const cfg = SOCIAL_STAGES[stage] || SOCIAL_STAGES.idle;

  sui.btnScout.disabled      = !cfg.scout;
  sui.btnStrategise.disabled = !cfg.strategise;
  sui.btnWrite.disabled      = !cfg.write;
  sui.btnCopyContent.disabled  = !cfg.copy;
  sui.btnDownloadCsv.disabled  = !cfg.downloadCsv;
  sui.btnSave.disabled         = !cfg.save;
  sui.btnReset.disabled       = !cfg.reset;

  [sui.scoutStatus, sui.strategistStatus, sui.copywriterStatus].forEach((el) => {
    el.textContent = "";
    el.classList.remove("running");
  });
  [sui.panelScout, sui.panelStrategist, sui.panelCopywriter].forEach((el) => {
    el.classList.remove("panel--active");
  });

  const activePanel = SOCIAL_STAGE_ACTIVE_PANEL[stage];
  if (activePanel) {
    const statusEl = $s(`social-${activePanel}-status`);
    statusEl.textContent = "Running…";
    statusEl.classList.add("running");
    $s(`social-panel-${activePanel}`).classList.add("panel--active");
    // Auto-advance carousel on mobile
    socialScrollToPanel(`social-panel-${activePanel}`);
    socialUpdateCarouselDots(`social-panel-${activePanel}`);
  }

  updateSocialPipeline(stage);
}

function updateSocialPipeline(stage) {
  const state = SOCIAL_PIPELINE_STATE[stage] || SOCIAL_PIPELINE_STATE.idle;

  for (let i = 1; i <= 4; i++) {
    const stepEl = $s(`social-step-${i}`);
    if (!stepEl) continue;
    stepEl.classList.remove("active", "completed");
    if (state.completed.includes(i)) {
      stepEl.classList.add("completed");
    } else if (state.active === i) {
      stepEl.classList.add("active");
    }
  }

  for (let i = 1; i <= 3; i++) {
    const lineEl = $s(`social-line-${i}-${i + 1}`);
    if (!lineEl) continue;
    if (state.completed.includes(i) && state.completed.includes(i + 1)) {
      lineEl.classList.add("completed");
    } else {
      lineEl.classList.remove("completed");
    }
  }
}

function markSocialSaved() {
  const step4 = $s("social-step-4");
  if (step4) {
    step4.classList.remove("active");
    step4.classList.add("completed");
    $s("social-line-3-4").classList.add("completed");
  }
}

// ---------------------------------------------------------------------------
// SSE helper
// ---------------------------------------------------------------------------

function startSocialSSE(endpoint, { onChunk, onOpportunities, onPosts, onDone, onError }) {
  const url = `${endpoint}?session_id=${SOCIAL_SESSION_ID}`;
  const es = new EventSource(url);

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk" && onChunk)                    onChunk(msg.text);
    else if (msg.type === "opportunities" && onOpportunities) onOpportunities(msg.data);
    else if (msg.type === "posts" && onPosts)                onPosts(msg.data);
    else if (msg.type === "done") { es.close(); if (onDone) onDone(); }
    else if (msg.type === "error") { es.close(); if (onError) onError(msg.message || "An error occurred."); }
  };

  es.onerror = () => {
    es.close();
    if (onError) onError("Connection to server lost. Please try again.");
  };

  return es;
}

// ---------------------------------------------------------------------------
// Output helpers
// ---------------------------------------------------------------------------

function clearSocialEmptyState(el) {
  const empty = el.querySelector(".empty-state");
  if (empty) empty.remove();
}

function appendToSocialOutput(el, fullText) {
  clearSocialEmptyState(el);
  const cursor = el.querySelector(".stream-cursor");
  if (cursor) cursor.remove();
  el.innerHTML = renderMarkdown(fullText);
  const cur = document.createElement("span");
  cur.className = "stream-cursor";
  el.appendChild(cur);
  el.scrollTop = el.scrollHeight;
}

function finaliseSocialOutput(el) {
  const cursor = el.querySelector(".stream-cursor");
  if (cursor) cursor.remove();
}

// ---------------------------------------------------------------------------
// Opportunity card rendering
// ---------------------------------------------------------------------------

const HOOK_LABELS = {
  curiosity:   "Curiosity",
  contrarian:  "Contrarian",
  story:       "Story",
  proof:       "Proof",
  "how-to":    "How-to",
};

function renderOpportunityList(opportunities, selectedOpp) {
  sui.opportunityList.innerHTML = "";

  opportunities.forEach((opp, i) => {
    const label = document.createElement("label");
    label.className = "topic-option";
    label.dataset.index = i;

    const hookLabel = HOOK_LABELS[opp.hook_type] || opp.hook_type;

    label.innerHTML = `
      <input type="radio" name="social-opportunity" value="${i}" />
      <div class="topic-title">${escapeHtml(opp.angle)}</div>
      <div class="topic-meta">
        <span class="tag tag-intent">${escapeHtml(opp.platform)}</span>
        <span class="tag tag-keyword">${escapeHtml(hookLabel)}</span>
      </div>
      <p class="topic-why">${escapeHtml(opp.why_now)}</p>
    `;

    label.addEventListener("click", () => selectOpportunityCard(i));

    if (selectedOpp && selectedOpp.angle === opp.angle) {
      label.classList.add("selected");
      label.querySelector("input").checked = true;
    }

    sui.opportunityList.appendChild(label);
  });
}

function selectOpportunityCard(index) {
  document.querySelectorAll('input[name="social-opportunity"]').forEach((el, i) => {
    const card = el.closest(".topic-option");
    card.classList.toggle("selected", i === index);
    el.checked = i === index;
  });
}

// ---------------------------------------------------------------------------
// Post card rendering
// ---------------------------------------------------------------------------

function renderPostCards(posts) {
  sui.postsContainer.innerHTML = "";

  posts.forEach((post) => {
    const platform = post.platform || "LinkedIn";
    const content = post.content || "";
    const charLimit = PLATFORM_CHAR_LIMITS[platform] || 3000;
    const charCount = content.length;
    const overLimit = charCount > charLimit;

    const badgeClass = {
      LinkedIn:  "badge-linkedin",
      X:         "badge-x",
      Instagram: "badge-instagram",
      TikTok:    "badge-tiktok",
      YouTube:   "badge-youtube",
      Facebook:  "badge-facebook",
      Pinterest: "badge-pinterest",
      Threads:   "badge-threads",
      Snapchat:  "badge-snapchat",
    }[platform] || "badge-linkedin";

    const card = document.createElement("div");
    card.className = "post-card";
    card.innerHTML = `
      <div class="post-card-header">
        <span class="post-platform-badge ${badgeClass}">${escapeHtml(platform)}</span>
        <div class="post-card-actions">
          <span class="post-char-count ${overLimit ? "over-limit" : ""}">${charCount.toLocaleString()} / ${charLimit.toLocaleString()}</span>
          <button class="btn-copy" data-content="${escapeAttrSocial(content)}">Copy</button>
        </div>
      </div>
      <div class="post-card-content">${escapeHtml(content)}</div>
    `;

    const copyBtn = card.querySelector(".btn-copy");
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(post.content);
        copyBtn.textContent = "Copied!";
        copyBtn.classList.add("copied");
        setTimeout(() => {
          copyBtn.textContent = "Copy";
          copyBtn.classList.remove("copied");
        }, 2000);
      } catch {
        copyBtn.textContent = "Error";
        setTimeout(() => { copyBtn.textContent = "Copy"; }, 1500);
      }
    });

    // "Send to Video Director" button — only for video-native platforms
    const VIDEO_ELIGIBLE_PLATFORMS = new Set(["TikTok", "Instagram", "YouTube"]);
    if (VIDEO_ELIGIBLE_PLATFORMS.has(platform)) {
      const videoBtn = document.createElement("button");
      videoBtn.className = "btn-send-video";
      videoBtn.textContent = "→ Video Director";
      videoBtn.addEventListener("click", () => {
        sessionStorage.setItem(
          "pendingVideoScript",
          JSON.stringify({ content: post.content, platform })
        );
        window.navigateTo("video");
      });
      card.querySelector(".post-card-actions").appendChild(videoBtn);
    }

    sui.postsContainer.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// Saved posts footer
// ---------------------------------------------------------------------------

function addSavedPost(platform, url) {
  const empty = sui.savedList.querySelector(".saved-empty");
  if (empty) empty.remove();

  const li = document.createElement("li");
  li.className = "saved-item";
  li.innerHTML = `<a href="${escapeAttrSocial(url)}" target="_blank" rel="noopener">📄 ${escapeHtml(platform)} post ↗</a>`;
  sui.savedList.appendChild(li);
}

// ---------------------------------------------------------------------------
// Error toast
// ---------------------------------------------------------------------------

function showSocialError(message) {
  const toast = document.getElementById("error-toast");
  toast.textContent = message;
  toast.classList.add("visible");
  setTimeout(() => toast.classList.remove("visible"), 6000);
}

// ---------------------------------------------------------------------------
// HTML escaping
// ---------------------------------------------------------------------------

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function escapeAttrSocial(str) {
  if (!str) return "#";
  return String(str).replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Button handlers
// ---------------------------------------------------------------------------

function wireSocialButtons() {
  // Live platform detection as user types URL
  sui.profileUrl.addEventListener("input", () => {
    const platform = detectPlatformFromUrl(sui.profileUrl.value.trim());
    updatePlatformBadge(platform);
  });

  // Scout Account
  sui.btnScout.addEventListener("click", async () => {
    const profileUrl = sui.profileUrl.value.trim();
    if (!profileUrl) { showSocialError("Please paste a social media profile URL first."); return; }

    const platform = detectPlatformFromUrl(profileUrl);
    if (!platform) { showSocialError("Couldn't recognise the platform from this URL. Please check it and try again."); return; }

    const description = sui.description.value.trim();

    await fetch("/api/social/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SOCIAL_SESSION_ID }),
    });

    await fetch("/api/social/context", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: SOCIAL_SESSION_ID,
        profile_url: profileUrl,
        description,
        detected_platform: platform,
      }),
    });

    sui.scoutOutput.innerHTML = '<div class="empty-state">Searching…</div>';
    sui.opportunityList.innerHTML = "";
    sui.strategistOutput.innerHTML = '<div class="empty-state">Waiting for an opportunity to be selected…</div>';
    sui.copywriterStream.innerHTML = '<div class="empty-state">Waiting for a content calendar…</div>';
    sui.postsContainer.innerHTML = "";
    sui.panelScout.classList.remove("topics-ready");
    sui.panelCopywriter.classList.remove("posts-ready");
    sui.postCount.textContent = "";
    sui.btnSave.innerHTML = "↑ Save to Notion";

    setSocialStage("scouting");

    let scoutText = "";
    startSocialSSE("/api/social/stream/scout", {
      onChunk: (text) => { scoutText += text; appendToSocialOutput(sui.scoutOutput, scoutText); },
      onOpportunities: (opps) => {
        renderOpportunityList(opps, null);
        sui.panelScout.classList.add("topics-ready");
      },
      onDone: () => { finaliseSocialOutput(sui.scoutOutput); setSocialStage("awaiting_idea"); },
      onError: (msg) => { setSocialStage("idle"); showSocialError(msg); },
    });
  });

  // Build Calendar
  sui.btnStrategise.addEventListener("click", async () => {
    const selected = document.querySelector('input[name="social-opportunity"]:checked');
    if (!selected) { showSocialError("Please select an opportunity from the list first."); return; }

    const res = await fetch("/api/social/select-opportunity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SOCIAL_SESSION_ID, opportunity_index: parseInt(selected.value, 10) }),
    });

    if (!res.ok) { showSocialError("Failed to select opportunity. Please try again."); return; }

    sui.strategistOutput.innerHTML = "";
    setSocialStage("strategising");

    let stratText = "";
    startSocialSSE("/api/social/stream/strategise", {
      onChunk: (text) => { stratText += text; appendToSocialOutput(sui.strategistOutput, stratText); },
      onDone: () => { finaliseSocialOutput(sui.strategistOutput); setSocialStage("awaiting_copy"); },
      onError: (msg) => { setSocialStage("awaiting_idea"); showSocialError(msg); },
    });
  });

  // Write Posts
  sui.btnWrite.addEventListener("click", () => {
    sui.copywriterStream.innerHTML = "";
    sui.postsContainer.innerHTML = "";
    sui.panelCopywriter.classList.remove("posts-ready");
    sui.postCount.textContent = "";
    setSocialStage("writing_posts");

    let copywriterText = "";
    startSocialSSE("/api/social/stream/write-posts", {
      onChunk: (text) => { copywriterText += text; appendToSocialOutput(sui.copywriterStream, copywriterText); },
      onPosts: (posts) => {
        finaliseSocialOutput(sui.copywriterStream);
        const n = posts.length;
        sui.copywriterStream.innerHTML = `<p style="color:var(--text-muted);font-style:italic">✓ ${n} post${n !== 1 ? "s" : ""} written</p>`;
        renderPostCards(posts);
        sui.panelCopywriter.classList.add("posts-ready");
        sui.postCount.textContent = `${n} post${n !== 1 ? "s" : ""}`;
      },
      onDone: () => setSocialStage("done"),
      onError: (msg) => { setSocialStage("awaiting_copy"); showSocialError(msg); },
    });
  });

  // Copy Content
  sui.btnCopyContent.addEventListener("click", async () => {
    const cards = sui.postsContainer.querySelectorAll(".post-card");
    const lines = [];
    cards.forEach((card) => {
      const platform = card.querySelector(".post-platform-badge")?.textContent?.trim() || "";
      const content  = card.querySelector(".post-card-content")?.textContent?.trim() || "";
      if (platform) lines.push(`[${platform}]`);
      if (content)  lines.push(content);
      lines.push("");
    });
    try {
      await navigator.clipboard.writeText(lines.join("\n").trim());
      sui.btnCopyContent.textContent = "Copied!";
      setTimeout(() => { sui.btnCopyContent.textContent = "Copy Content"; }, 2000);
    } catch {
      showSocialError("Could not copy to clipboard");
    }
  });

  // Download CSV
  sui.btnDownloadCsv.addEventListener("click", () => {
    const cards = sui.postsContainer.querySelectorAll(".post-card");
    const rows = [["platform", "content", "char_count"]];
    cards.forEach((card) => {
      const platform = card.querySelector(".post-platform-badge")?.textContent?.trim() || "";
      const content  = card.querySelector(".post-card-content")?.textContent?.trim() || "";
      rows.push([platform, content, String(content.length)]);
    });
    const csv = rows.map((r) => r.map((v) => `"${v.replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "social-posts.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  });

  // Save to Notion
  sui.btnSave.addEventListener("click", async () => {
    sui.btnSave.disabled = true;
    sui.btnSave.innerHTML = "⏳ Saving…";

    try {
      const res = await fetch("/api/social/save-notion", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: SOCIAL_SESSION_ID }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Unknown error saving to Notion");

      data.saved.forEach((p) => addSavedPost(p.platform, p.url));
      sui.btnSave.innerHTML = "✓ Saved";
      sui.btnReset.disabled = false;
      markSocialSaved();
    } catch (e) {
      sui.btnSave.disabled = false;
      sui.btnSave.innerHTML = "↑ Save to Notion";
      showSocialError(`Notion save failed: ${e.message}`);
    }
  });

  // New Campaign
  sui.btnReset.addEventListener("click", async () => {
    await fetch("/api/social/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SOCIAL_SESSION_ID }),
    });

    sui.scoutOutput.innerHTML = '<div class="empty-state">Waiting to scout account…</div>';
    sui.strategistOutput.innerHTML = '<div class="empty-state">Waiting for an opportunity to be selected…</div>';
    sui.copywriterStream.innerHTML = '<div class="empty-state">Waiting for a content calendar…</div>';
    sui.postsContainer.innerHTML = "";
    sui.opportunityList.innerHTML = "";
    sui.panelScout.classList.remove("topics-ready");
    sui.panelCopywriter.classList.remove("posts-ready");
    sui.postCount.textContent = "";
    sui.btnSave.innerHTML = "↑ Save to Notion";

    setSocialStage("idle");
  });
}

// ---------------------------------------------------------------------------
// View mount hook
// ---------------------------------------------------------------------------

function viewDidMount_social() {
  if (_socialInitialized) return;
  _socialInitialized = true;

  sui = getSocialUi();
  wireSocialButtons();

  // Carousel: dot tap targets
  document.querySelectorAll('#social-carousel-dots .carousel-dot').forEach((dot) => {
    dot.addEventListener('click', () => {
      socialScrollToPanel(dot.dataset.panel);
      socialUpdateCarouselDots(dot.dataset.panel);
    });
  });

  // Carousel: keep dots in sync with manual swipes
  const _socialGrid = document.querySelector('#view-social .panel-grid');
  if (_socialGrid) {
    _socialGrid.addEventListener('scroll', () => {
      if (!window.matchMedia('(max-width: 480px)').matches) return;
      const idx = Math.round(_socialGrid.scrollLeft / _socialGrid.offsetWidth);
      socialUpdateCarouselDots(SOCIAL_PANEL_ORDER[Math.min(idx, SOCIAL_PANEL_ORDER.length - 1)]);
    }, { passive: true });
  }

  initSocialSession().catch((e) => showSocialError(`Failed to initialise session: ${e.message}`));
}

window.viewDidMount_social = viewDidMount_social;
