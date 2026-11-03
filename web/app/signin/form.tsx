"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

const NEXT = "/onboarding/payout";

/** UI only for now. See lib/session.ts. */
export default function SignInForm() {
  const router = useRouter();
  return (
    <>
      <form
        className="field-group"
        onSubmit={(event) => {
          event.preventDefault();
          router.push(NEXT);
        }}
      >
        <label htmlFor="email" className="label-muted">Email</label>
        <input id="email" className="input input-large" type="email" autoComplete="email" placeholder="you@example.com" />
        <button type="submit" className="button button-large">Continue</button>
      </form>
      <div className="divider">or</div>
      <div className="field-group">
        <Link href={NEXT} className="button button-outline button-large">Continue with Google</Link>
        <Link href={NEXT} className="button button-outline button-large">Sign in with an XRPL wallet</Link>
      </div>
      <p className="muted small">No account? <Link href={NEXT}>Create one</Link></p>
    </>
  );
}
