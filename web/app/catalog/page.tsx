import type { Metadata } from "next";
import AppHeader from "@/components/app-header";
import CatalogView from "./view";

export const metadata: Metadata = { title: "Catalog" };
export const dynamic = "force-dynamic";

export default function CatalogPage() {
  return (
    <div className="screen">
      <AppHeader current="catalog" />
      <CatalogView />
    </div>
  );
}
