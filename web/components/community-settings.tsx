"use client";

import { useState, type FormEvent } from "react";
import { writerFetch } from "@/lib/api-client";

export default function CommunitySettings({
  applicationId,
}: {
  applicationId?: string;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function pair(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setCode("");
    setBusy(true);
    try {
      const settings = Object.fromEntries(new FormData(event.currentTarget));
      const res = await writerFetch("/me/discord/pair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (!res.ok)
        throw new Error(
          "Check your writer login, role IDs and price, then try again.",
        );
      setCode((await res.json()).code);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not create a pairing code.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="pieces">
      <h2>Connect a Discord AMA channel</h2>
      <p>
        Install the publisher in your server and grant access to the AMA channel
        and a private review channel.{" "}
        {applicationId && (
          <a
            href={`https://discord.com/oauth2/authorize?client_id=${encodeURIComponent(applicationId)}&scope=bot%20applications.commands&permissions=0`}
          >
            Install in Discord
          </a>
        )}
      </p>
      <form onSubmit={pair}>
        <label>
          Editor role ID <input name="editor" pattern="[0-9]{17,20}" required />
        </label>{" "}
        <label>
          Reviewer role ID{" "}
          <input name="reviewer" pattern="[0-9]{17,20}" required />
        </label>{" "}
        <label>
          Default USD per read{" "}
          <input
            name="price_usd"
            type="number"
            min="0.000001"
            step="0.000001"
            defaultValue="0.01"
            required
          />
        </label>{" "}
        <button disabled={busy}>Create pairing code</button>
      </form>
      {error && <p role="alert">{error}</p>}
      {code && (
        <p role="status">
          In your AMA channel, run <code>/connect_ama</code> and select the
          private review channel. Your single-use code expires in 10 minutes:{" "}
          <code>{code}</code>.
        </p>
      )}
    </section>
  );
}
