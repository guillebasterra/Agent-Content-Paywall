import type { Metadata } from "next";
import Logo from "@/components/logo";
import { PAYMENT_RAIL } from "@/lib/api";
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
          <h1>{PAYMENT_RAIL === "base" ? "How you get paid" : "Add a payout method"}</h1>
          <PayoutForm />
        </div>
      </main>
    </div>
  );
}
