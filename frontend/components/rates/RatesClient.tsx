"use client";

import { useState, useMemo, useEffect } from "react";
import { LaneSummary, RateCompareData } from "@/lib/types";
import RateOverviewTable from "./RateOverviewTable";
import RateCompareCard from "./RateCompareCard";
import RateTrendChart from "./RateTrendChart";
import RateFilters from "./RateFilters";
import { getRateCompare, getRateLane } from "@/lib/api";

interface RatesClientProps {
  initialLanes: LaneSummary[];
}

export default function RatesClient({ initialLanes }: RatesClientProps) {
  const [search, setSearch] = useState("");
  const [containerType, setContainerType] = useState("all");

  const filteredLanes = useMemo(() => {
    return initialLanes.filter((lane) => {
      const matchesSearch =
        search === "" ||
        lane.trade_lane.toLowerCase().includes(search.toLowerCase()) ||
        lane.source.toLowerCase().includes(search.toLowerCase());

      const matchesContainer =
        containerType === "all" || lane.container_type === containerType;

      return matchesSearch && matchesContainer;
    });
  }, [initialLanes, search, containerType]);

  // Selected trade lane state (defaults to Singapore-Europe or Shanghai-Europe or first available)
  const [selectedLane, setSelectedLane] = useState<LaneSummary>(() => {
    return (
      initialLanes.find((l) => l.trade_lane.includes("Singapore")) ||
      initialLanes[0] || {
        trade_lane: "Singapore-Europe",
        container_type: "40ft",
        current_rate_usd: 2650,
        change_7d_pct: -2.1,
        trend: "falling",
        source: "Alphaliner",
        rate_date: "2026-08-10",
      }
    );
  });

  const [compareData, setCompareData] = useState<RateCompareData | null>(null);
  const [historyData, setHistoryData] = useState<any[]>([]);

  // Fetch benchmark compare and time series data when selected lane changes
  useEffect(() => {
    let isMounted = true;
    async function loadLaneData() {
      try {
        const [comp, detail] = await Promise.all([
          getRateCompare(selectedLane.trade_lane, selectedLane.container_type),
          getRateLane(selectedLane.trade_lane, selectedLane.container_type),
        ]);
        if (isMounted) {
          setCompareData(comp);
          if (detail && detail.history) {
            setHistoryData(detail.history);
          }
        }
      } catch (err) {
        console.warn("Error loading selected lane benchmark data:", err);
      }
    }

    if (selectedLane) {
      loadLaneData();
    }

    return () => {
      isMounted = false;
    };
  }, [selectedLane]);

  return (
    <div className="space-y-6">
      {/* Top Filter Controls */}
      <RateFilters
        search={search}
        onSearchChange={setSearch}
        containerType={containerType}
        onContainerTypeChange={setContainerType}
      />

      {/* Side-by-Side Grid: All Trade Lanes Table (Left 2 cols) & Benchmark Comparison (Right 1 col) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch">
        <div className="lg:col-span-2">
          <RateOverviewTable
            lanes={filteredLanes}
            selectedLaneName={selectedLane.trade_lane}
            onSelectLane={(lane) => setSelectedLane(lane)}
          />
        </div>

        <div className="lg:col-span-1">
          <RateCompareCard
            data={compareData}
            lane={selectedLane.trade_lane}
            currentRate={selectedLane.current_rate_usd}
          />
        </div>
      </div>

      {/* Bottom Chart: Full Width 30-Day Rate Trend Chart */}
      <div className="w-full pt-2">
        <RateTrendChart
          data={historyData.length > 0 ? historyData : undefined}
          lane={selectedLane.trade_lane}
          containerType={selectedLane.container_type}
        />
      </div>
    </div>
  );
}

export { RatesClient };
