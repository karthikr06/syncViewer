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
        if (error) setError(error.message);
      } else if (mode === "up") {
        const { data, error } = await supabase.auth.signUp({
          email: v.email,
          password,
          options: { emailRedirectTo: window.location.origin },
        });
        if (error) setError(error.message);
        else if (!data.session) setInfo("Check your email to confirm your account, then sign in.");
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

  const label = { in: "Sign in", up: "Create account", reset: "Send reset link" }[mode];

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div>
          <h1 className="text-2xl font-bold">SyncViewer</h1>
          <p className="text-sm text-slate-500">
            {mode === "reset" ? "Reset your password." : "All your cloud VMs in one place."}
          </p>
        </div>
        {missingConfig.length > 0 && (
          <ErrorNote message={`Missing configuration: ${missingConfig.join(", ")}. Set it in .env.`} />
        )}
        <form className="space-y-3" onSubmit={handleSubmit(submit)} noValidate>
          <Field label="Email" error={errors.email?.message}>
            <input className="input" type="email" autoComplete="email" {...register("email")} />
          </Field>
          {mode !== "reset" && (
            <Field label="Password" error={errors.password?.message}>
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
        <div className="flex justify-between text-sm">
          <button className="text-sky-600 hover:underline" onClick={() => switchTo(mode === "in" ? "up" : "in")}>
            {mode === "in" ? "No account? Sign up" : "Back to sign in"}
          </button>
          {mode === "in" && (
            <button className="text-slate-500 hover:underline" onClick={() => switchTo("reset")}>
              Forgot password?
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
