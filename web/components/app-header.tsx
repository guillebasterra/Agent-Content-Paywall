import Link from "next/link";
import { getSession } from "@/lib/session";
import { AUTH_MODE } from "@/lib/supabase-config";
import Logo from "./logo";
import SignOut from "./sign-out";

export default async function AppHeader({ current }: { current: "dashboard" | "catalog" }) {
  const session = await getSession();
  const name = session?.writer.name;
  return (
    <header className="header">
      <Logo />
      <nav aria-label="Main" className="nav">
        <Link href="/dashboard" aria-current={current === "dashboard" ? "page" : undefined}>Dashboard</Link>
        <Link href="/catalog" aria-current={current === "catalog" ? "page" : undefined}>Catalog</Link>
        {current !== "dashboard" && <Link href="/upload" className="button button-small">Upload</Link>}
        {name && <span className="avatar" role="img" aria-label={`Signed in as ${name}`}>{name[0]}</span>}
        {AUTH_MODE === "supabase" && name && <SignOut />}
      </nav>
    </header>
  );
}
