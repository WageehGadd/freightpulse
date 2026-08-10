"use client";

import Link from "next/link";
import { LaneSummary } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface RateOverviewTableProps {
  lanes: LaneSummary[];
  selectedLaneName?: string;
  onSelectLane?: (lane: LaneSummary) => void;
}

function SoftTrendPill({ trend }: { trend: "rising" | "falling" | "stable" | string }) {
  if (trend === "rising" || trend === "up") {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-red-100/90 text-red-700 dark:bg-red-950/60 dark:text-red-300">
        <TrendingUp className="h-3.5 w-3.5" />
        Rising
      </span>
    );
  }

  if (trend === "falling" || trend === "down") {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-emerald-100/90 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300">
        <TrendingDown className="h-3.5 w-3.5" />
        Falling
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-amber-100/90 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300">
      <Minus className="h-3.5 w-3.5" />
      Stable
    </span>
  );
}

export default function RateOverviewTable({
  lanes,
  selectedLaneName,
  onSelectLane,
}: RateOverviewTableProps) {
  if (!lanes || lanes.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-slate-500">
        No trade lanes match your search criteria.
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200/80 shadow-xs overflow-hidden">
      <div className="p-5 pb-3 border-b border-slate-100 dark:border-slate-800">
        <h3 className="text-lg font-bold text-slate-900 dark:text-white">
          All Trade Lanes
        </h3>
      </div>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader className="bg-slate-50/80 dark:bg-slate-800/50">
            <TableRow className="border-b border-slate-200/60">
              <TableHead className="font-bold text-slate-700 dark:text-slate-300 py-3.5">
                Trade Lane
              </TableHead>
              <TableHead className="font-bold text-slate-700 dark:text-slate-300 py-3.5">
                Container
              </TableHead>
              <TableHead className="font-bold text-slate-700 dark:text-slate-300 py-3.5 text-right">
                Rate (USD)
              </TableHead>
              <TableHead className="font-bold text-slate-700 dark:text-slate-300 py-3.5 text-right">
                7d Change
              </TableHead>
              <TableHead className="font-bold text-slate-700 dark:text-slate-300 py-3.5">
                Trend
              </TableHead>
              <TableHead className="font-bold text-slate-700 dark:text-slate-300 py-3.5">
                Source
              </TableHead>
            </TableRow>
          </TableHeader>

          <TableBody>
            {lanes.map((lane) => {
              const isPositiveChange = lane.change_7d_pct > 0;
              const isNegativeChange = lane.change_7d_pct < 0;
              const formattedLane = lane.trade_lane.replace("-", " → ");
              const isSelected =
                selectedLaneName &&
                (selectedLaneName === lane.trade_lane ||
                  selectedLaneName.replace("-", " → ") === formattedLane);

              return (
                <TableRow
                  key={`${lane.trade_lane}-${lane.container_type}`}
                  onClick={() => onSelectLane && onSelectLane(lane)}
                  className={`cursor-pointer transition-colors border-b border-slate-100 dark:border-slate-800 ${isSelected
                      ? "bg-blue-50/70 dark:bg-blue-950/40"
                      : "hover:bg-slate-50/80 dark:hover:bg-slate-800/40"
                    }`}
                >
                  <TableCell className="font-medium py-4">
                    <Link
                      href={`/rates/${encodeURIComponent(lane.trade_lane)}`}
                      className="text-slate-900 dark:text-slate-100 font-semibold hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
                      onClick={(e) => {
                        // Prevent navigation if user just wants to select row for chart
                        if (onSelectLane) {
                          e.stopPropagation();
                          onSelectLane(lane);
                        }
                      }}
                    >
                      {formattedLane}
                    </Link>
                  </TableCell>
                  <TableCell className="text-slate-600 dark:text-slate-300 py-4">
                    {lane.container_type}
                  </TableCell>
                  <TableCell className="text-right font-mono font-bold text-slate-900 dark:text-white py-4">
                    ${lane.current_rate_usd.toLocaleString()}
                  </TableCell>
                  <TableCell
                    className={`text-right font-bold font-mono text-sm py-4 ${isPositiveChange
                        ? "text-red-600 dark:text-red-400"
                        : isNegativeChange
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-slate-500"
                      }`}
                  >
                    {isPositiveChange ? "+" : ""}
                    {lane.change_7d_pct}%
                  </TableCell>
                  <TableCell className="py-4">
                    <SoftTrendPill trend={lane.trend} />
                  </TableCell>
                  <TableCell className="text-slate-500 text-sm py-4">
                    {lane.source}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

export { RateOverviewTable };
