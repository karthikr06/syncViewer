import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ErrorNote, Field } from "../components/ui";
import { missingConfig } from "../lib/env";
import { supabase } from "../lib/supabase";

const schema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(8, "At least 8 characters"),
});
type Form = z.infer<typeof schema>;

export function Login() {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Form>({ resolver: zodResolver(schema) });

  async function submit(v: Form) {
    setError(null);
    setInfo(null);
    setBusy(true);
    try {
      if (mode === "in") {
        const { error } = await supabase.auth.signInWithPassword(v);
        if (error) setError(error.message);
      } else {
        const { data, error } = await supabase.auth.signUp({
          ...v,
          options: { emailRedirectTo: window.location.origin },
        });
        if (error) setError(error.message);
        else if (!data.session) setInfo("Check your email to confirm your account, then sign in.");
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

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div>
          <h1 className="text-2xl font-bold">SyncViewer</h1>
          <p className="text-sm text-slate-500">All your cloud VMs in one place.</p>
        </div>
        {missingConfig.length > 0 && (
          <ErrorNote message={`Missing configuration: ${missingConfig.join(", ")}. Set it in .env.`} />
        )}
        <form className="space-y-3" onSubmit={handleSubmit(submit)} noValidate>
          <Field label="Email" error={errors.email?.message}>
            <input className="input" type="email" autoComplete="email" {...register("email")} />
          </Field>
          <Field label="Password" error={errors.password?.message}>
            <input
              className="input"
              type="password"
              autoComplete={mode === "in" ? "current-password" : "new-password"}
              {...register("password")}
            />
          </Field>
          <ErrorNote message={error} />
          {info && <p className="text-sm text-emerald-700 dark:text-emerald-400">{info}</p>}
          <button className="btn-primary w-full" disabled={busy}>
            {busy ? "Please wait…" : mode === "in" ? "Sign in" : "Create account"}
          </button>
        </form>
        <button className="btn-ghost w-full" onClick={() => void google()} type="button">
          Continue with Google
        </button>
        <button
          className="w-full text-center text-sm text-sky-600 hover:underline"
          onClick={() => {
            setMode(mode === "in" ? "up" : "in");
            setError(null);
          }}
        >
          {mode === "in" ? "No account? Sign up" : "Have an account? Sign in"}
        </button>
      </div>
    </div>
  );
}
