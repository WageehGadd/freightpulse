export type RateTrend = "rising" | "stable" | "falling";

export interface LaneSummary {
  trade_lane: string;
  container_type: string;
  current_rate_usd: number;
  change_7d_pct: number;
  trend: RateTrend;
  source: string;
  rate_date: string;
}

export interface RatePoint {
  date: string;
  rate_usd: number;
  avg_7d_usd?: number;
  avg_30d_usd?: number;
}

export interface RateLaneDetail {
  trade_lane: string;
  container_type: string;
  current_rate_usd: number;
  trend: RateTrend;
  source: string;
  history: RatePoint[];
}

export interface RateCompareData {
  trade_lane: string;
  container_type: string;
  current_rate_usd: number;
  avg_7d: number;
  avg_30d: number;
  avg_90d: number;
  vs_7d_pct: number;
  vs_30d_pct: number;
  vs_90d_pct: number;
}

export interface RatesAllResponse {
  lanes: LaneSummary[];
}
export type PortCongestionLevel = "low" | "medium" | "high" | "critical" | "elevated" | "normal";

export interface Port {
  id: string;
  code?: string;
  name: string;
  country: string;
  latitude: number;
  longitude: number;
  congestion_level: PortCongestionLevel;
  congestion_pct: number;
  vessels_waiting: number;
  avg_dwell_days?: number;
}
