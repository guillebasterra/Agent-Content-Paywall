import type { Metadata } from "next";
import { Suspense } from "react";
import Logo from "@/components/logo";
import { API_URL } from "@/lib/api";
import SignInForm from "./form";

export const metadata: Metadata = { title: "Sign in" };

export default function SignInPage() {
  return (
    <div className="screen">
      <header className="header header-bare"><Logo /></header>
      <main className="centered">
        <div className="stack stack-narrow">
          <h1>Sign in</h1>
          <Suspense><SignInForm /></Suspense>
        </div>
      </main>
      <footer className="footer">
        <a className="mono" href={`${API_URL}/llms.txt`}>/llms.txt</a>
      </footer>
    </div>
  );
}
