"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from "react";
import { LogIn, MailCheck, UserPlus } from "lucide-react";
import { ApiError, api } from "@/lib/hooks";
import { nextPath, type Me } from "@/lib/auth";
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

/** This page's ?next=…, to keep it when switching between sign-in and register. Read after the first
 * render, so the prerendered HTML and the browser agree. */
function useQuery(): string {
  const [query, setQuery] = useState("");
  useEffect(() => setQuery(window.location.search), []);
  return query;
}

/** Runs one request at a time and keeps its error for the form. */
function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run };
}

function post(url: string, body: object) {
  return api(url, { method: "POST", body: JSON.stringify(body) });
}

export function SignInView() {
  const me = useMe();
  const query = useQuery();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirming, setConfirming] = useState(false);
  const { busy, error, run } = useAction();

  function submit(event: FormEvent) {
    event.preventDefault();
    run(async () => {
      try {
        await post("/api/auth/login", { email: email.trim(), password });
        window.location.assign(nextPath());
      } catch (e) {
        if (e instanceof ApiError && e.reason === "unconfirmed") setConfirming(true);
        else throw e;
      }
    });
  }

  if (confirming) {
    return (
      <ConfirmStep
        email={email.trim()}
        note="Your email address isn't confirmed yet. Enter the code from the email we sent when you registered, or send a new one."
        back={{ label: "Back to sign in", onClick: () => setConfirming(false) }}
      />
    );
  }

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
          "Need an account? Ask the GreenPulse owner."
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
  const [sentTo, setSentTo] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const closed = me !== null && !me.registration_open;

  function submit(event: FormEvent) {
    event.preventDefault();
    run(async () => {
      const registered = await api<{ email: string }>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), email: email.trim(), password }),
      });
      setSentTo(registered.email);
    });
  }

  if (sentTo) {
    return <ConfirmStep email={sentTo} back={{ label: "Use a different email", onClick: () => setSentTo(null) }} />;
  }

  return (
    <AuthFrame
      title="Create an account"
      subtitle="We'll email you a 6-digit code to confirm your address."
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
          Registration is closed: this GreenPulse can&apos;t send email yet. Ask its owner to set it up.
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
        </fieldset>
        <ErrorNote error={error} />
        <SubmitButton
          busy={busy}
          disabled={closed || !name.trim() || !email.trim() || password.length < 8}
          icon={<UserPlus className="size-4" aria-hidden />}
        >
          {busy ? "Sending code…" : "Create account"}
        </SubmitButton>
      </form>
    </AuthFrame>
  );
}

/** Enter the emailed code: confirms the address and signs in. */
function ConfirmStep({ email, note, back }: { email: string; note?: string; back: { label: string; onClick: () => void } }) {
  const [code, setCode] = useState("");
  const [resent, setResent] = useState(false);
  const confirm = useAction();
  const resend = useAction();

  function submit(event: FormEvent) {
    event.preventDefault();
    confirm.run(async () => {
      await post("/api/auth/confirm", { email, code });
      window.location.assign(nextPath());
    });
  }

  function sendNewCode() {
    setResent(false);
    resend.run(async () => {
      await post("/api/auth/code", { email });
      setResent(true);
      setCode("");
    });
  }

  return (
    <AuthFrame
      title="Check your email"
      subtitle={
        <>
          We sent a 6-digit code to <span className="font-semibold text-ink">{email}</span>. It expires in 15 minutes.
        </>
      }
      footer={
        <button type="button" onClick={back.onClick} className="font-semibold text-brand-ink hover:underline">
          {back.label}
        </button>
      }
    >
      {note && <p className="mb-4 rounded-lg bg-info-bg px-3.5 py-3 text-sm text-info-ink">{note}</p>}
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="code" className="text-sm font-semibold text-ink">
            Code
          </label>
          <input
            id="code"
            required
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{6}"
            maxLength={6}
            placeholder="000000"
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
            disabled={confirm.busy}
            className="mt-1.5 w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-center text-xl font-semibold tracking-[0.4em] tabular-nums outline-none placeholder:text-line-strong focus:border-brand focus:ring-2 focus:ring-brand/15 disabled:bg-sunk"
          />
        </div>
        <ErrorNote error={confirm.error ?? resend.error} />
        {resent && !resend.error && (
          <p role="status" className="rounded-lg bg-good-bg px-3.5 py-2.5 text-sm text-good-ink">
            A new code is on its way. Check your inbox, and the spam folder.
          </p>
        )}
        <SubmitButton busy={confirm.busy} disabled={code.length !== 6} icon={<MailCheck className="size-4" aria-hidden />}>
          {confirm.busy ? "Checking…" : "Confirm and sign in"}
        </SubmitButton>
        <p className="text-center text-sm text-ink-3">
          No email?{" "}
          <button
            type="button"
            onClick={sendNewCode}
            disabled={resend.busy}
            className="font-semibold text-brand-ink hover:underline disabled:cursor-not-allowed disabled:text-ink-3"
          >
            {resend.busy ? "Sending…" : "Send a new code"}
          </button>
        </p>
      </form>
    </AuthFrame>
  );
}

function AuthFrame({ title, subtitle, footer, children }: { title: string; subtitle: ReactNode; footer: ReactNode; children: ReactNode }) {
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
