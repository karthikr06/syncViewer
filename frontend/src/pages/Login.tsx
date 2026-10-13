import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ErrorNote, Field } from "../components/ui";
import { env, missingConfig } from "../lib/env";
import { supabase } from "../lib/supabase";

// password is checked in submit() because the reset form has no password field
const schema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().optional(),
});
type Form = z.infer<typeof schema>;
type Mode = "in" | "up" | "reset";

export function Login() {
  const [mode, setMode] = useState<Mode>("in");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const {
    register,
    handleSubmit,
    setError: setFieldError,
    formState: { errors },
  } = useForm<Form>({ resolver: zodResolver(schema) });

  function switchTo(next: Mode) {
    setMode(next);
    setError(null);
    setInfo(null);
  }

  async function submit(v: Form) {
    setError(null);
    setInfo(null);
    const password = v.password ?? "";
    if (mode !== "reset" && password.length < 8) {
      setFieldError("password", { message: "At least 8 characters" });
      return;
    }
    setBusy(true);
    try {
      if (mode === "in") {
        const { error } = await supabase.auth.signInWithPassword({ email: v.email, password });
        if (error)
          setError(
            /invalid login credentials/i.test(error.message)
              ? "Wrong email or password. New here, or invited by your team? Choose Sign up."
              : error.message,
          );
      } else if (mode === "up") {
        const { data, error } = await supabase.auth.signUp({
          email: v.email,
          password,
          options: { emailRedirectTo: window.location.origin },
        });
        if (error)
          setError(
            /already registered/i.test(error.message)
              ? "This email already has an account. Choose Log in."
              : error.message,
          );
        else if (!data.session) setInfo("Check your email to confirm your account, then log in.");
      } else {
        const { error } = await supabase.auth.resetPasswordForEmail(v.email, {
          redirectTo: `${window.location.origin}/account/password`,
        });
        // same message either way: don't reveal which emails have accounts
        if (error && error.status !== 400) setError(error.message);
        else setInfo("If that email has an account, a reset link is on its way.");
      }
    } catch {
      setError("Can't reach the sign-in service. Check your connection.");
    } finally {
      setBusy(false);
    }
  }

  async function google() {
    setError(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: window.location.origin },
    });
    if (error) setError(error.message);
  }

  const label = { in: "Log in", up: "Create account", reset: "Send reset link" }[mode];

  const tab = (m: "in" | "up", text: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === m}
      onClick={() => switchTo(m)}
      className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition ${
        mode === m ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"
      }`}
    >
      {text}
    </button>
  );

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-4">
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight">
            Sync<span className="text-accent">Viewer</span>
          </h1>
          <p className="mt-1 text-sm text-muted">All your cloud VMs in one place.</p>
        </div>
        <div className="card space-y-4">
          {mode === "reset" ? (
            <div>
              <h2 className="font-semibold">Reset your password</h2>
              <p className="text-sm text-muted">We'll email you a link to choose a new one.</p>
            </div>
          ) : (
            <>
              <div className="flex gap-1 rounded-lg bg-subtle p-1" role="tablist">
                {tab("in", "Log in")}
                {tab("up", "Sign up")}
              </div>
              <p className="text-sm text-muted">
                {mode === "in"
                  ? "Welcome back. Log in with the account you already have."
                  : "New here? Create an account. If a teammate added your email, you'll join their workspace; otherwise you get your own workspace as its admin."}
              </p>
            </>
          )}
          {missingConfig.length > 0 && (
            <ErrorNote message={`Missing configuration: ${missingConfig.join(", ")}. Set it in .env.`} />
          )}
          <form className="space-y-3" onSubmit={handleSubmit(submit)} noValidate>
            <Field label="Email" error={errors.email?.message}>
              <input className="input" type="email" autoComplete="email" {...register("email")} />
            </Field>
            {mode !== "reset" && (
              <Field label={mode === "up" ? "Choose a password (8+ characters)" : "Password"} error={errors.password?.message}>
                <input
                  className="input"
                  type="password"
                  autoComplete={mode === "in" ? "current-password" : "new-password"}
                  {...register("password")}
                />
              </Field>
            )}
            <ErrorNote message={error} />
            {info && <p className="text-sm text-emerald-700 dark:text-emerald-400">{info}</p>}
            <button className="btn-primary w-full" disabled={busy}>
              {busy ? "Please wait…" : label}
            </button>
          </form>
          {env.googleAuth && mode !== "reset" && (
            <button className="btn-ghost w-full" onClick={() => void google()} type="button">
              Continue with Google
            </button>
          )}
          <div className="text-center text-sm">
            {mode === "in" && (
              <button className="text-muted hover:text-ink hover:underline" onClick={() => switchTo("reset")}>
                Forgot password?
              </button>
            )}
            {mode === "reset" && (
              <button className="link" onClick={() => switchTo("in")}>
                Back to log in
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
