import { LaneSummary } from "@/lib/types";

export const rates: LaneSummary[] = [
  {
    trade_lane: "Shanghai-Jeddah",
    container_type: "40ft",
    current_rate_usd: 2450,
    change_7d_pct: 5.2,
    trend: "rising",
    source: "MSC / Freightos",
    rate_date: "2026-08-10",
  },
  {
    trade_lane: "Singapore-Dubai",
    container_type: "40ft",
    current_rate_usd: 1980,
    change_7d_pct: -2.1,
    trend: "falling",
    source: "Maersk / SCFI",
    rate_date: "2026-08-10",
  },
  {
    trade_lane: "Ningbo-Alexandria",
    container_type: "40ft",
    current_rate_usd: 2150,
    change_7d_pct: 0.0,
    trend: "stable",
    source: "CMA CGM / WCI",
    rate_date: "2026-08-10",
  },
];
