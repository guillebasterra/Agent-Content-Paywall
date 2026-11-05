/** Where a writer goes after signing in. A new writer has no payout method yet. */
export const landingPath = (payout: { xrpl_address: string | null } | null) =>
  payout?.xrpl_address ? "/dashboard" : "/onboarding/payout";
