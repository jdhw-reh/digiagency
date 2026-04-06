"use strict";

function switchTab(tab) {
  document.getElementById("form-login").style.display    = tab === "login"    ? "block" : "none";
  document.getElementById("form-register").style.display = tab === "register" ? "block" : "none";
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
      btn.textContent = "Redirecting to payment…";
      const checkoutRes = await fetch("/api/checkout/session", { method: "POST" });
      let checkoutData = {};
      try { checkoutData = await checkoutRes.json(); } catch { /* non-JSON */ }
      if (!checkoutRes.ok || !checkoutData.url) {
        errEl.textContent = checkoutData.error || "Your subscription is inactive. Please contact support.";
        return;
      }
      window.location.href = checkoutData.url;
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
    const checkoutRes = await fetch("/api/checkout/session", { method: "POST" });
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

// Handle Stripe return URL params
document.addEventListener("DOMContentLoaded", () => {
  const params = new URLSearchParams(window.location.search);
  const checkout = params.get("checkout");
  if (checkout === "success") {
    document.getElementById("login-error").style.color = "#4ade80";
    document.getElementById("login-error").textContent = "Payment successful! Sign in to access your account.";
  } else if (checkout === "cancelled") {
    document.getElementById("login-error").textContent = "Checkout cancelled. Register again when you\u2019re ready.";
  }
  // Clean URL
  if (checkout) window.history.replaceState({}, "", "/login");
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
