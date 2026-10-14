"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from "react";
import { LogIn, UserPlus } from "lucide-react";
import { api } from "@/lib/hooks";
import { nextPath, type Account, type Me } from "@/lib/auth";
import { Logo } from "../shell/Sidebar";

/** Who is signed in and whether registration is open. Someone already signed in goes straight on. */
function useMe(): Me | null {
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => {
    api<Me>("/api/auth/me")
      .then((body) => (body.account ? window.location.replace(nextPath()) : setMe(body)))
      .catch(() => setMe({ account: null, registration_open: false })); // server down: submitting will say why
  }, []);
  return me;
}

/** Sign-in or register, then a full page load so the dashboard starts fresh for this account. */
function useSubmit(url: string, body: () => object) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api<{ account: Account }>(url, { method: "POST", body: JSON.stringify(body()) });
      window.location.assign(nextPath());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }
  return { busy, error, submit };
}

/** This page's ?next=…, to keep it when switching between sign-in and register. Read after the first
 * render, so the prerendered HTML and the browser agree. */
function useQuery(): string {
  const [query, setQuery] = useState("");
  useEffect(() => setQuery(window.location.search), []);
  return query;
}

export function SignInView() {
  const me = useMe();
  const query = useQuery();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, submit } = useSubmit("/api/auth/login", () => ({ email: email.trim(), password }));

  return (
    <AuthFrame
      title="Sign in"
      subtitle="Welcome back. Sign in to check on your plant."
      footer={
        me?.registration_open ? (
          <>
            New here?{" "}
            <Link href={`/register${query}`} className="font-semibold text-brand-ink hover:underline">
              Create an account
            </Link>
          </>
        ) : me ? (
          "Need an account? Ask the GreenPulse owner for access."
        ) : null
      }
    >
      <form onSubmit={submit} className="space-y-4">
        <Field
          id="email"
          label="Email"
          type="email"
          required
          autoComplete="email"
          maxLength={254}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Field
          id="password"
          label="Password"
          type="password"
          required
          autoComplete="current-password"
          maxLength={200}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <ErrorNote error={error} />
        <SubmitButton busy={busy} disabled={!email.trim() || !password} icon={<LogIn className="size-4" aria-hidden />}>
          {busy ? "Signing in…" : "Sign in"}
        </SubmitButton>
      </form>
    </AuthFrame>
  );
}

export function RegisterView() {
  const me = useMe();
  const query = useQuery();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const { busy, error, submit } = useSubmit("/api/auth/register", () => ({ name: name.trim(), email: email.trim(), password, code }));
  const closed = me !== null && !me.registration_open;

  return (
    <AuthFrame
      title="Create an account"
      subtitle="You need the registration code from the GreenPulse owner."
      footer={
        <>
          Already have an account?{" "}
          <Link href={`/login${query}`} className="font-semibold text-brand-ink hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      {closed && (
        <p className="mb-4 rounded-lg bg-warning-bg px-3.5 py-3 text-sm text-warning-ink">
          Registration is closed on this GreenPulse. Ask its owner to set a registration code.
        </p>
      )}
      <form onSubmit={submit} className="space-y-4">
        <fieldset disabled={closed || busy} className="space-y-4">
          <Field id="name" label="Name" required autoComplete="name" maxLength={60} value={name} onChange={(event) => setName(event.target.value)} />
          <Field
            id="email"
            label="Email"
            type="email"
            required
            autoComplete="email"
            maxLength={254}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <Field
            id="password"
            label="Password"
            hint="At least 8 characters."
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            maxLength={200}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <Field
            id="code"
            label="Registration code"
            required
            autoComplete="off"
            spellCheck={false}
            maxLength={100}
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
        </fieldset>
        <ErrorNote error={error} />
        <SubmitButton
          busy={busy}
          disabled={closed || !name.trim() || !email.trim() || password.length < 8 || !code.trim()}
          icon={<UserPlus className="size-4" aria-hidden />}
        >
          {busy ? "Creating account…" : "Create account"}
        </SubmitButton>
      </form>
    </AuthFrame>
  );
}

function AuthFrame({ title, subtitle, footer, children }: { title: string; subtitle: string; footer: ReactNode; children: ReactNode }) {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center">
          <Logo />
        </div>
        <section className="rounded-xl border border-line bg-surface p-6 shadow-card">
          <h1 className="display text-xl text-ink">{title}</h1>
          <p className="mt-1 text-sm text-ink-3">{subtitle}</p>
          <div className="mt-5">{children}</div>
        </section>
        {footer && <p className="mt-4 text-center text-sm text-ink-3">{footer}</p>}
      </div>
    </main>
  );
}

function Field({ id, label, hint, ...input }: { id: string; label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label htmlFor={id} className="text-sm font-semibold text-ink">
        {label}
      </label>
      <input
        id={id}
        {...input}
        className="mt-1.5 w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/15 disabled:bg-sunk"
      />
      {hint && <p className="mt-1 text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-lg border border-critical/30 bg-critical-bg px-3.5 py-2.5 text-sm text-critical-ink">
      {error}
    </p>
  );
}

function SubmitButton({ busy, disabled, icon, children }: { busy: boolean; disabled: boolean; icon: ReactNode; children: ReactNode }) {
  return (
    <button
      type="submit"
      disabled={busy || disabled}
      className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white shadow-card transition-colors hover:bg-brand-strong disabled:cursor-not-allowed disabled:bg-line-strong"
    >
      {icon}
      {children}
    </button>
  );
}
