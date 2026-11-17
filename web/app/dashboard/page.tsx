import type { Metadata } from "next";
import AppHeader from "@/components/app-header";
import DashboardView from "./view";

export const metadata: Metadata = { title: "Dashboard" };
export const dynamic = "force-dynamic";

export default function DashboardPage() {
  return (
    <div className="screen">
      <AppHeader current="dashboard" />
      <DashboardView />
    </div>
  );
}
