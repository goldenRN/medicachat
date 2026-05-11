import { fetchJson } from "/assets/scripts/api.js";
import { getStoredToken, setStoredToken } from "/assets/scripts/session.js";

const elements = {
  form: document.querySelector("#login-form"),
  emailInput: document.querySelector("#email-input"),
  passwordInput: document.querySelector("#password-input"),
  errorText: document.querySelector("#login-error"),
};

bootstrap();

function bootstrap() {
  if (getStoredToken()) {
    window.location.replace("/chat");
    return;
  }

  elements.form.addEventListener("submit", handleLogin);
}

async function handleLogin(event) {
  event.preventDefault();
  elements.errorText.textContent = "";

  try {
    const response = await fetchJson("/api/login", {
      method: "POST",
      body: {
        email: elements.emailInput.value.trim(),
        password: elements.passwordInput.value.trim(),
      },
      redirectOnAuthFailure: false,
    });

    setStoredToken(response.token);
    window.location.replace("/chat");
  } catch (error) {
    elements.errorText.textContent = error.message || "Нэвтрэх үед алдаа гарлаа.";
  }
}
