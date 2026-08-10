import { TrendingDown, TrendingUp, Minus } from "lucide-react";
import { RateTrend } from "@/lib/types";

interface Props {
  trend: RateTrend | "up" | "down" | "stable";
}

const TREND_CONFIG = {
  rising: { label: "Rising", icon: TrendingUp, color: "text-red-600 bg-red-50 border-red-200" },
  stable: { label: "Stable", icon: Minus, color: "text-yellow-700 bg-yellow-50 border-yellow-200" },
  falling: { label: "Falling", icon: TrendingDown, color: "text-green-600 bg-green-50 border-green-200" },
};

export default function TrendBadge({ trend }: Props) {
  // Normalize legacy trend strings
  let normalizedTrend: RateTrend = "stable";
  if (trend === "rising" || trend === "up") normalizedTrend = "rising";
  else if (trend === "falling" || trend === "down") normalizedTrend = "falling";
  else normalizedTrend = "stable";

  const config = TREND_CONFIG[normalizedTrend];
  const Icon = config.icon;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${config.color}`}
    >
      <Icon className="h-3.5 w-3.5" />
      {config.label}
    </span>
  );
}

export { TrendBadge };
