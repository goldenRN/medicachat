"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { fetchJson } from "@/lib/api";
import { getStoredToken, setStoredToken } from "@/lib/session";
import LogoMark from "@/components/logo-mark";

export default function LoginScreen() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (getStoredToken()) {
      router.replace("/chat");
    }
  }, [router]);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);

    try {
      const formData = new FormData(event.currentTarget);
      const emailValue = String(formData.get("email") || "").trim();
      const passwordValue = String(formData.get("password") || "").trim();

      const response = await fetchJson("/api/login", {
        method: "POST",
        body: {
          email: emailValue,
          password: passwordValue,
        },
        redirectOnAuthFailure: false,
      });

      setStoredToken(response.token);
      router.replace("/chat");
    } catch (submitError) {
      setError(submitError.message || "Нэвтрэх үед алдаа гарлаа.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-body">
      <div className="background-orb orb-left" />
      <div className="background-orb orb-right" />

      <div className="auth-shell">
        <section className="login-hero">
          <div className="logo-lockup">
            <LogoMark />
            <div>
              <p className="eyebrow">AI Knowledge Assistant</p>
              <h2>СОС Медикал Монгол</h2>
            </div>
          </div>
        </section>

        <section className="login-card bg-red">
          <div className="card-head">
            <h2>Нэвтрэх</h2>
          </div>

          <form className="form-stack" onSubmit={handleSubmit}>
            <label className="field">
              <span>Email Address</span>
              <input
                name="email"
                type="email"
                placeholder="Enter your email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>

            <label className="field">
              <span>Password</span>
              <input
                name="password"
                type="password"
                placeholder="Enter your password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>

            <button className="primary-button" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Нэвтэрч байна..." : "Login"}
            </button>
            <p className="error-text" aria-live="polite">
              {error}
            </p>
          </form>

          <footer className="login-footer">© 2026 SOS Medica Mongolia. All rights reserved.</footer>
        </section>
      </div>
    </main>
  );
}
