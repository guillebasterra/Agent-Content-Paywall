/** Where a writer goes after signing in. A new writer has no payout method yet. */
export const landingPath = (payout: { xrpl_address: string | null; stripe?: { connected: boolean } } | null) =>
  payout?.xrpl_address || payout?.stripe?.connected ? "/dashboard" : "/onboarding/payout";
