import Review from "./review";

export default async function Page({
  params,
}: {
  params: Promise<{ guild: string; channel: string; message: string }>;
}) {
  const { guild, channel, message } = await params;
  return <Review source={[guild, channel, message].join("/")} />;
}
