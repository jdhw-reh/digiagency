"use strict";

const _VALID_PLANS = ["starter", "pro", "agency"];

function selectPlan(plan) {
  document.getElementById("plan-starter").classList.toggle("selected", plan === "starter");
  document.getElementById("plan-pro").classList.toggle("selected", plan === "pro");
  document.getElementById("plan-agency").classList.toggle("selected", plan === "agency");
  sessionStorage.setItem("selected_plan", plan);
}

function switchTab(tab) {
  const allForms = ["form-login", "form-register", "form-forgot", "form-reset", "form-join"];
  const showMap = { login: "form-login", register: "form-register", forgot: "form-forgot", join: "form-join" };
  const showId = showMap[tab] || "form-login";

  allForms.forEach(id => {
    const el = document.getElementById(id);
    if (!el || el.id === showId) return;
    el.style.opacity = "0";
    setTimeout(() => { el.style.display = "none"; }, 140);
  });

  const show = document.getElementById(showId);
  setTimeout(() => {
    show.style.display = "block";
    show.offsetHeight;
    show.style.opacity = "1";
  }, 140);

  const showingAuth = tab === "login" || tab === "register" || tab === "join";
  document.querySelector(".tabs").style.display = showingAuth ? "" : "none";
  document.getElementById("tab-login").classList.toggle("active",    tab === "login");
  document.getElementById("tab-register").classList.toggle("active", tab === "register");
  document.getElementById("tab-join").classList.toggle("active",     tab === "join");
  document.getElementById("login-error").textContent  = "";
  document.getElementById("reg-error").textContent    = "";
  document.getElementById("forgot-error").textContent = "";
  document.getElementById("join-error").textContent   = "";
}

async function doLogin() {
  const email    = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  const errEl    = document.getElementById("login-error");
  const btn      = document.getElementById("login-btn");

  errEl.textContent = "";
  if (!email || !password) { errEl.textContent = "Please enter your email and password."; return; }

  btn.disabled = true;
  btn.textContent = "Signing in…";

  try {
    const res  = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    let data = {};
    try { data = await res.json(); } catch { /* non-JSON response */ }

    if (!res.ok) {
      errEl.textContent = data.error || `Login failed (${res.status}).`;
      return;
    }

    if (data.subscription_status !== "active") {
      if (data.subscription_status === "inactive") {
        errEl.innerHTML = "Payment not yet confirmed. If you\u2019ve just completed checkout, wait a moment then sign in again. "
          + "<a href=\"#\" id=\"subscribe-link\" style=\"color:#5ba3ff;text-decoration:underline\">Subscribe now</a> if you haven\u2019t paid yet.";
        document.getElementById("subscribe-link").onclick = async (e) => {
          e.preventDefault();
          btn.disabled = true;
          btn.textContent = "Redirecting to payment\u2026";
          const plan = sessionStorage.getItem("selected_plan") || "pro";
          const cRes = await fetch(`/api/checkout/session?plan=${plan}`, { method: "POST" });
          let cData = {};
          try { cData = await cRes.json(); } catch { /* non-JSON */ }
          if (!cRes.ok || !cData.url) {
            errEl.textContent = cData.error || "Could not start checkout. Please contact support.";
            btn.disabled = false; btn.textContent = "Sign in";
            return;
          }
          window.location.href = cData.url;
        };
      } else {
        errEl.textContent = "Your subscription is not active. Please contact support.";
      }
      return;
    }

    window.location.href = "/app";
  } catch {
    errEl.textContent = "Network error — please try again.";
  } finally {
    btn.disabled = false;
    btn.textContent = "Sign in";
  }
}

async function doRegister() {
  const email    = document.getElementById("reg-email").value.trim();
  const password = document.getElementById("reg-password").value;
  const errEl    = document.getElementById("reg-error");
  const btn      = document.getElementById("reg-btn");

  errEl.textContent = "";
  if (!email || !password) { errEl.textContent = "Please fill in all fields."; return; }

  btn.disabled = true;
  btn.textContent = "Creating account…";

  try {
    const res  = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    let data = {};
    try { data = await res.json(); } catch { /* non-JSON response */ }

    if (!res.ok) {
      errEl.textContent = data.error || `Registration failed (${res.status}).`;
      return;
    }

    // Account created — now redirect to Stripe Checkout
    btn.textContent = "Redirecting to payment…";
    const plan = _VALID_PLANS.find(p => document.getElementById(`plan-${p}`)?.classList.contains("selected")) || "pro";
    const checkoutRes = await fetch(`/api/checkout/session?plan=${plan}`, { method: "POST" });
    let checkoutData = {};
    try { checkoutData = await checkoutRes.json(); } catch { /* non-JSON */ }

    if (!checkoutRes.ok || !checkoutData.url) {
      errEl.textContent = checkoutData.error || "Could not start checkout. Please contact support.";
      return;
    }

    window.location.href = checkoutData.url;
  } catch {
    errEl.textContent = "Network error — please try again.";
  } finally {
    btn.disabled = false;
    if (btn.textContent !== "Redirecting to payment…") btn.textContent = "Create account";
  }
}

async function doForgotPassword() {
  const email = document.getElementById("forgot-email").value.trim();
  const errEl = document.getElementById("forgot-error");
  const btn   = document.getElementById("forgot-btn");

  errEl.textContent = "";
  if (!email) { errEl.textContent = "Please enter your email address."; return; }

  btn.disabled = true;
  btn.textContent = "Sending…";

  try {
    await fetch("/api/auth/forgot-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    errEl.classList.add("success");
    errEl.textContent = "If that email is registered, a reset link is on its way.";
    btn.textContent = "Link sent";
  } catch {
    errEl.classList.remove("success");
    errEl.textContent = "Network error — please try again.";
    btn.disabled = false;
    btn.textContent = "Send reset link";
  }
}

async function doResetPassword() {
  const token    = document.getElementById("reset-token").value;
  const password = document.getElementById("reset-password").value.trim();
  const errEl    = document.getElementById("reset-error");
  const btn      = document.getElementById("reset-btn");

  errEl.classList.remove("success");
  errEl.textContent = "";
  if (!password) { errEl.textContent = "Please enter a new password."; return; }

  btn.disabled = true;
  btn.textContent = "Updating…";

  try {
    const res = await fetch("/api/auth/reset-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, new_password: password }),
    });
    let data = {};
    try { data = await res.json(); } catch { /* non-JSON */ }

    if (!res.ok) {
      errEl.textContent = data.error || "Something went wrong. Please try again.";
      btn.disabled = false;
      btn.textContent = "Update password";
      return;
    }

    errEl.classList.add("success");
    errEl.textContent = "Password updated! Redirecting to sign in…";
    setTimeout(() => {
      window.history.replaceState({}, "", "/login");
      switchTab("login");
    }, 1800);
  } catch {
    errEl.textContent = "Network error — please try again.";
    btn.disabled = false;
    btn.textContent = "Update password";
  }
}

async function doJoinTeam() {
  const code      = document.getElementById("join-code").value.trim().toUpperCase();
  const name      = document.getElementById("join-name").value.trim();
  const email     = document.getElementById("join-email").value.trim();
  const password  = document.getElementById("join-password").value;
  const errEl     = document.getElementById("join-error");
  const successEl = document.getElementById("join-success");
  const btn       = document.getElementById("join-btn");

  errEl.textContent = "";
  successEl.style.display = "none";

  if (!code || !name || !email || !password) {
    errEl.textContent = "Please fill in all fields.";
    return;
  }
  if (!/^[A-Z0-9]{4}-[A-Z0-9]+$/.test(code)) {
    errEl.textContent = "Workspace code format looks wrong — check it with your admin (e.g. DIGI-7K2M).";
    return;
  }

  btn.disabled = true;
  btn.textContent = "Sending request\u2026";

  try {
    const res = await fetch("/api/auth/register-team-member", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_code: code, name, email, password }),
    });
    let data = {};
    try { data = await res.json(); } catch {}

    if (res.status === 201) {
      document.getElementById("form-join").style.display = "none";
      successEl.style.display = "block";
      const ownerDisplay = data.owner_email ? data.owner_email : "the workspace owner";
      successEl.textContent = `Request sent! We\u2019ll email you once ${ownerDisplay} approves your access.`;
      return;
    }

    if (res.status === 404) {
      errEl.textContent = "Workspace code not found. Double-check the code with your team admin.";
    } else if (res.status === 409) {
      errEl.textContent = "An account with this email already exists. Sign in instead, then request to join from your account settings.";
    } else if (res.status === 400) {
      errEl.textContent = (data.error || "").includes("full")
        ? "This workspace has reached its maximum number of seats."
        : (data.error || "Something went wrong. Please try again.");
    } else {
      errEl.textContent = data.error || `Something went wrong (${res.status}). Please try again.`;
    }
  } catch {
    errEl.textContent = "Network error \u2014 please try again.";
  } finally {
    btn.disabled = false;
    btn.textContent = "Request access";
  }
}

// Handle Stripe return URL params + persist plan selection
document.addEventListener("DOMContentLoaded", () => {
  const params = new URLSearchParams(window.location.search);

  // Password reset link — show reset form and hide everything else
  const resetToken = params.get("token");
  if (resetToken) {
    document.getElementById("reset-token").value = resetToken;
    ["form-login", "form-register", "form-forgot"].forEach(id => {
      document.getElementById(id).style.display = "none";
    });
    document.getElementById("form-reset").style.display = "block";
    document.querySelector(".tabs").style.display = "none";
    window.history.replaceState({}, "", "/reset-password");
    return; // skip plan/checkout param handling
  }

  const plan = params.get("plan");
  if (_VALID_PLANS.includes(plan)) {
    selectPlan(plan);
  } else {
    const stored = sessionStorage.getItem("selected_plan");
    if (_VALID_PLANS.includes(stored)) selectPlan(stored);
  }

  const checkout = params.get("checkout");
  if (checkout === "success") {
    const el = document.getElementById("login-error");
    el.classList.add("success");
    el.textContent = "Payment successful! Sign in to access your account.";
  } else if (checkout === "cancelled") {
    document.getElementById("login-error").textContent = "Checkout cancelled. Register again when you\u2019re ready.";
  }
  // Clean URL
  if (checkout || plan) window.history.replaceState({}, "", "/login");
});

// Enter key support
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("login-password").addEventListener("keydown", e => {
    if (e.key === "Enter") doLogin();
  });
  document.getElementById("login-email").addEventListener("keydown", e => {
    if (e.key === "Enter") document.getElementById("login-password").focus();
  });
  document.getElementById("reg-password").addEventListener("keydown", e => {
    if (e.key === "Enter") doRegister();
  });
  document.getElementById("forgot-email").addEventListener("keydown", e => {
    if (e.key === "Enter") doForgotPassword();
  });
  document.getElementById("join-password").addEventListener("keydown", e => {
    if (e.key === "Enter") doJoinTeam();
  });
  document.getElementById("join-email").addEventListener("keydown", e => {
    if (e.key === "Enter") document.getElementById("join-password").focus();
  });
});
