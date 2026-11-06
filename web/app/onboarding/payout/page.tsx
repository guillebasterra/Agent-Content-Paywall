import type { Metadata } from "next";
import Logo from "@/components/logo";
import PayoutForm from "./form";

export const metadata: Metadata = { title: "Payout method" };

export default function PayoutPage() {
  return (
    <div className="screen">
      <header className="header">
        <Logo />
        <span className="mono muted">2 / 2</span>
      </header>
      <main className="centered">
        <div className="stack stack-medium">
          <h1>Add a payout method</h1>
          <p className="muted">Agents pay you each time they read your work. You can change this later.</p>
          <PayoutForm />
        </div>
      </main>
    </div>
  );
}
