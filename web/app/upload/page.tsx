import type { Metadata } from "next";
import { getSession } from "@/lib/session";
import UploadForm from "./form";

export const metadata: Metadata = { title: "Upload" };
export const dynamic = "force-dynamic";

export default async function UploadPage() {
  const session = await getSession();
  return <UploadForm author={session?.writer.name ?? ""} />;
}
