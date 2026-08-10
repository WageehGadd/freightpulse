"use client";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, X } from "lucide-react";

interface RateFiltersProps {
  search: string;
  onSearchChange: (value: string) => void;
  containerType: string;
  onContainerTypeChange: (value: string) => void;
}

export default function RateFilters({
  search,
  onSearchChange,
  containerType,
  onContainerTypeChange,
}: RateFiltersProps) {
  const hasActiveFilters = search !== "" || containerType !== "all";

  const clearFilters = () => {
    onSearchChange("");
    onContainerTypeChange("all");
  };

  return (
    <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 w-full">
      <div className="relative flex-1 max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search by trade lane or data source..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9 pr-8"
        />
        {search && (
          <button
            onClick={() => onSearchChange("")}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      <div className="flex items-center gap-2">
        <div className="inline-flex rounded-lg border p-1 bg-muted/40">
          <button
            onClick={() => onContainerTypeChange("all")}
            className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${
              containerType === "all"
                ? "bg-background text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            All Containers
          </button>
          <button
            onClick={() => onContainerTypeChange("40ft")}
            className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${
              containerType === "40ft"
                ? "bg-background text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            40ft (FEU)
          </button>
          <button
            onClick={() => onContainerTypeChange("20ft")}
            className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${
              containerType === "20ft"
                ? "bg-background text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            20ft (TEU)
          </button>
        </div>

        {hasActiveFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters} className="text-xs h-8">
            Clear Filters
          </Button>
        )}
      </div>
    </div>
  );
}

export { RateFilters };
