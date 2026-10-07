import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ErrorNote, Field, PageHeader } from "../components/ui";
import { supabase } from "../lib/supabase";

const schema = z
  .object({
    password: z.string().min(8, "At least 8 characters"),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, { message: "Passwords don't match", path: ["confirm"] });
type Form = z.infer<typeof schema>;

/** Also the landing page of the "forgot password" email link (Supabase signs the user in first). */
export function ChangePassword() {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<Form>({ resolver: zodResolver(schema) });

  async function submit(v: Form) {
    setError(null);
    setDone(false);
    setBusy(true);
    try {
      const { error } = await supabase.auth.updateUser({ password: v.password });
      if (error) setError(error.message);
      else {
        setDone(true);
        reset();
      }
    } catch {
      setError("Can't reach the sign-in service. Check your connection.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Change password" />
      <form className="card max-w-sm space-y-3" onSubmit={handleSubmit(submit)} noValidate>
        <Field label="New password" error={errors.password?.message}>
          <input className="input" type="password" autoComplete="new-password" {...register("password")} />
        </Field>
        <Field label="Repeat new password" error={errors.confirm?.message}>
          <input className="input" type="password" autoComplete="new-password" {...register("confirm")} />
        </Field>
        <ErrorNote message={error} />
        {done && <p className="text-sm text-emerald-700 dark:text-emerald-400">Password updated.</p>}
        <button className="btn-primary w-full" disabled={busy}>
          {busy ? "Please wait…" : "Update password"}
        </button>
      </form>
    </>
  );
}
