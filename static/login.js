"use strict";

function selectPlan(plan) {
  document.getElementById("plan-starter").classList.toggle("selected", plan === "starter");
  document.getElementById("plan-pro").classList.toggle("selected", plan === "pro");
  sessionStorage.setItem("selected_plan", plan);
}

function switchTab(tab) {
  const showId = tab === "login" ? "form-login" : "form-register";
  const hideId = tab === "login" ? "form-register" : "form-login";
  const show = document.getElementById(showId);
  const hide = document.getElementById(hideId);

  hide.style.opacity = "0";
  setTimeout(() => {
    hide.style.display = "none";
    show.style.display = "block";
    show.offsetHeight; // force reflow
    show.style.opacity = "1";
  }, 140);

  document.getElementById("tab-login").classList.toggle("active",    tab === "login");
  document.getElementById("tab-register").classList.toggle("active", tab === "register");
  document.getElementById("login-error").textContent = "";
  document.getElementById("reg-error").textContent   = "";
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
    const plan = document.getElementById("plan-starter")?.classList.contains("selected")
      ? "starter"
      : "pro";
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

// Handle Stripe return URL params + persist plan selection
document.addEventListener("DOMContentLoaded", () => {
  const params = new URLSearchParams(window.location.search);

  const plan = params.get("plan");
  if (plan === "starter" || plan === "pro") {
    selectPlan(plan);
  } else {
    const stored = sessionStorage.getItem("selected_plan");
    if (stored === "starter" || stored === "pro") selectPlan(stored);
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
});
