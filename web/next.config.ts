import type { NextConfig } from "next";

const config: NextConfig = {
  devIndicators: false, // The floating badge would cover content on the demo screen.
  agentRules: false, // Agent guidance lives in the repo's CLAUDE.md.
};

export default config;
