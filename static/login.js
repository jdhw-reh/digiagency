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
    const data = await res.json();

    if (!res.ok) {
      errEl.textContent = data.error || "Login failed.";
      return;
    }

    if (data.subscription_status !== "active") {
      errEl.textContent = "Your account is pending activation. Check back shortly.";
      return;
    }

    window.location.href = "/";
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
    const data = await res.json();

    if (!res.ok) {
      errEl.textContent = data.error || "Registration failed.";
      return;
    }

    // Show pending message — admin must activate before they can log in
    btn.style.display = "none";
    document.getElementById("pending-msg").style.display = "block";
  } catch {
    errEl.textContent = "Network error — please try again.";
  } finally {
    btn.disabled = false;
    if (btn.style.display !== "none") btn.textContent = "Create account";
  }
}

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
