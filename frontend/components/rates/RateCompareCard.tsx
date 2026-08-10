"use client";

import { useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RateCompareData } from "@/lib/types";

interface RateCompareCardProps {
  data?: RateCompareData | null;
  lane?: string;
  currentRate?: number;
}

const DEFAULT_COMPARE: RateCompareData = {
  trade_lane: "Singapore-Europe",
  container_type: "40ft",
  current_rate_usd: 2650,
  avg_7d: 2706,
  avg_30d: 2562,
  avg_90d: 2595,
  vs_7d_pct: -2.1,
  vs_30d_pct: 3.4,
  vs_90d_pct: 2.1,
};

export default function RateCompareCard({
  data = DEFAULT_COMPARE,
  lane,
  currentRate,
}: RateCompareCardProps) {
  const compare = data || DEFAULT_COMPARE;

  const displayLane = useMemo(() => {
    const rawLane = lane || compare.trade_lane || "Singapore → Europe";
    return rawLane.replace("-", " → ");
  }, [lane, compare.trade_lane]);

  const displayRate = currentRate ?? compare.current_rate_usd ?? 2650;

  const renderPill = (label: string, diffPct: number) => {
    const isPositive = diffPct > 0;
    const isNegative = diffPct < 0;

    return (
      <div className="flex items-center justify-between p-3.5 rounded-xl bg-slate-100/80 dark:bg-slate-800/60 border border-slate-200/50">
        <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
          {label}
        </span>
        <span
          className={`text-sm font-bold font-mono ${
            isPositive
              ? "text-red-600 dark:text-red-400"
              : isNegative
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-slate-500"
          }`}
        >
          {isPositive ? "+" : ""}
          {diffPct}%
        </span>
      </div>
    );
  };

  return (
    <Card className="w-full h-full bg-white dark:bg-slate-900 border border-slate-200/80 shadow-xs rounded-xl flex flex-col justify-between overflow-hidden">
      <CardHeader className="p-6 pb-4">
        <CardTitle className="text-lg font-bold text-slate-900 dark:text-white">
          Benchmark Comparison
        </CardTitle>
      </CardHeader>

      <CardContent className="p-6 pt-0 space-y-4 flex-1 flex flex-col justify-between">
        <div className="space-y-3">
          {/* Current Rate Card Box */}
          <div className="p-4 rounded-xl bg-slate-100/80 dark:bg-slate-800/60 border border-slate-200/50">
            <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-1">
              Current Rate
            </p>
            <p className="text-3xl font-extrabold font-mono text-slate-900 dark:text-white">
              ${displayRate.toLocaleString()}
            </p>
          </div>

          {/* Benchmark Comparison Rows */}
          <div className="space-y-2.5">
            {renderPill("vs 7d Avg", compare.vs_7d_pct)}
            {renderPill("vs 30d Avg", compare.vs_30d_pct)}
            {renderPill("vs 90d Avg", compare.vs_90d_pct)}
          </div>
        </div>

        {/* Selected Lane Footer */}
        <div className="pt-4 border-t border-slate-100 dark:border-slate-800">
          <p className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">
            SELECTED LANE
          </p>
          <p className="text-base font-bold text-slate-900 dark:text-white">
            {displayLane}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

export { RateCompareCard };
