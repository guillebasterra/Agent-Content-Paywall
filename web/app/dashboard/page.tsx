import type { Metadata } from "next";
import AppHeader from "@/components/app-header";
import DashboardView from "./view";
import CommunitySettings from "@/components/community-settings";
import PublisherToken from "@/components/publisher-token";

export const metadata: Metadata = { title: "Dashboard" };
export const dynamic = "force-dynamic";

export default function DashboardPage() {
  return (
    <div className="screen">
      <AppHeader current="dashboard" />
      <DashboardView />
      <CommunitySettings applicationId={process.env.DISCORD_PUBLISHER_APPLICATION_ID} />
      <PublisherToken />
    </div>
  );
}
