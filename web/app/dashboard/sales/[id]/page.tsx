import AppHeader from "@/components/app-header";
import Sales from "./sales";

export default async function ArticleSales({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <main className="screen">
      <AppHeader current="dashboard" />
      <Sales id={(await params).id} />
    </main>
  );
}
