"use client";

import { useState, useMemo } from "react";
import { Port, PortCongestionLevel } from "@/lib/types";
import PortsMapWrapper from "@/components/ports/PortsMapWrapper";
import PortCard from "@/components/ports/PortCard";
import PortFilters from "@/components/ports/PortFilters";
import PortDetailModal from "@/components/ports/PortDetailModal";
import { Anchor } from "lucide-react";

type Props = {
  initialPorts: Port[];
};

type FilterLevel = "all" | PortCongestionLevel;

export default function PortsClient({ initialPorts }: Props) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedSeverity, setSelectedSeverity] = useState<FilterLevel>("all");
  const [selectedPort, setSelectedPort] = useState<Port | null>(null);
  const [isDetailOpen, setIsDetailOpen] = useState(false);

  // Helper to categorize port level
  const getPortSeverity = (port: Port): "critical" | "elevated" | "normal" => {
    if (port.congestion_level === "critical" || port.congestion_pct >= 80) {
      return "critical";
    }
    if (
      port.congestion_level === "elevated" ||
      port.congestion_level === "high" ||
      port.congestion_pct >= 50
    ) {
      return "elevated";
    }
    return "normal";
  };

  // Severity Counts
  const counts = useMemo(() => {
    const res = { all: initialPorts.length, critical: 0, elevated: 0, normal: 0 };
    initialPorts.forEach((port) => {
      const sev = getPortSeverity(port);
      res[sev]++;
    });
    return res;
  }, [initialPorts]);

  // Filtered Ports
  const filteredPorts = useMemo(() => {
    return initialPorts.filter((port) => {
      const sev = getPortSeverity(port);

      // Severity match
      if (selectedSeverity !== "all" && sev !== selectedSeverity) {
        return false;
      }

      // Search match
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const code = (port.code || port.id || "").toLowerCase();
        const name = port.name.toLowerCase();
        const country = port.country.toLowerCase();

        return code.includes(q) || name.includes(q) || country.includes(q);
      }

      return true;
    });
  }, [initialPorts, selectedSeverity, searchQuery]);

  const handleSelectPort = (port: Port) => {
    setSelectedPort(port);
    setIsDetailOpen(true);
  };

  const handleFocusMap = (port: Port) => {
    setSelectedPort(port);
  };

  return (
    <div className="space-y-6">
      {/* Header Section */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">
          Port Congestion
        </h1>
        <p className="text-slate-500 mt-1">
          Monitor real-time congestion and dwell times across global trade ports.
        </p>
      </div>

      {/* Search & Severity Filters */}
      <PortFilters
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        selectedSeverity={selectedSeverity}
        onSeverityChange={setSelectedSeverity}
        counts={counts}
      />

      {/* Interactive Map */}
      <PortsMapWrapper
        ports={filteredPorts}
        selectedPort={selectedPort}
        onSelectPort={handleSelectPort}
      />

      {/* Port Overview Cards List Section */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
        <div className="border-b border-slate-100 pb-4 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-slate-900">Port overview</h2>
            <p className="text-sm text-slate-500 mt-1">
              Click a port to inspect current conditions
            </p>
          </div>
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-slate-100 text-slate-600">
            Showing {filteredPorts.length} of {initialPorts.length} ports
          </span>
        </div>

        {filteredPorts.length > 0 ? (
          <div className="divide-y divide-slate-100">
            {filteredPorts.map((port) => (
              <PortCard
                key={port.id}
                port={port}
                onClick={() => handleSelectPort(port)}
                isSelected={selectedPort?.id === port.id}
              />
            ))}
          </div>
        ) : (
          <div className="py-12 text-center space-y-3">
            <div className="h-12 w-12 rounded-full bg-slate-100 flex items-center justify-center mx-auto text-slate-400">
              <Anchor className="h-6 w-6" />
            </div>
            <h3 className="text-base font-bold text-slate-900">No ports found</h3>
            <p className="text-sm text-slate-500 max-w-sm mx-auto">
              No ports matched your filter criteria. Try adjusting your search query or severity filter.
            </p>
          </div>
        )}
      </section>

      {/* Inspection Detail Modal */}
      <PortDetailModal
        port={selectedPort}
        isOpen={isDetailOpen}
        onClose={() => setIsDetailOpen(false)}
        onFocusMap={handleFocusMap}
      />
    </div>
  );
}
