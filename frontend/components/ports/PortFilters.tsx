"use client";

import { PortCongestionLevel } from "@/lib/types";
import { Search, X } from "lucide-react";

type FilterLevel = "all" | PortCongestionLevel;

type Props = {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  selectedSeverity: FilterLevel;
  onSeverityChange: (level: FilterLevel) => void;
  counts: {
    all: number;
    critical: number;
    elevated: number;
    medium?: number;
    normal: number;
    low?: number;
  };
};

export default function PortFilters({
  searchQuery,
  onSearchChange,
  selectedSeverity,
  onSeverityChange,
  counts,
}: Props) {
  const filterButtons: { label: string; value: FilterLevel; count: number; activeColor: string }[] = [
    {
      label: "All Ports",
      value: "all",
      count: counts.all,
      activeColor: "bg-slate-900 text-white border-slate-900",
    },
    {
      label: "Critical",
      value: "critical",
      count: counts.critical,
      activeColor: "bg-red-600 text-white border-red-600",
    },
    {
      label: "Elevated",
      value: "elevated",
      count: counts.elevated,
      activeColor: "bg-amber-500 text-white border-amber-500",
    },
    {
      label: "Normal",
      value: "normal",
      count: counts.normal,
      activeColor: "bg-emerald-600 text-white border-emerald-600",
    },
  ];

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      {/* Search Input Box */}
      <div className="relative flex-1 max-w-md">
        <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Filter by port name, code (e.g. JEA, SIP), or country..."
          className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-9 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none shadow-xs transition-colors"
        />
        {searchQuery && (
          <button
            onClick={() => onSearchChange("")}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Severity Filter Pills */}
      <div className="flex flex-wrap items-center gap-2">
        {filterButtons.map((btn) => {
          const isActive = selectedSeverity === btn.value;
          return (
            <button
              key={btn.value}
              onClick={() => onSeverityChange(btn.value)}
              className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-all duration-150 cursor-pointer ${
                isActive
                  ? btn.activeColor
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300"
              }`}
            >
              <span>{btn.label}</span>
              <span
                className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                  isActive
                    ? "bg-white/20 text-white"
                    : "bg-slate-100 text-slate-600"
                }`}
              >
                {btn.count}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
