"use client";

import { useMemo, useState } from "react";
import { CarrierAdvisory, AdvisoryType } from "@/lib/types";
import CarrierAdvisoryFeed from "@/components/carriers/CarrierAdvisoryFeed";

type Props = {
  initialAdvisories: CarrierAdvisory[];
};

export default function CarriersClient({ initialAdvisories }: Props) {
  const [selectedCarrier, setSelectedCarrier] = useState("all");
  const [selectedType, setSelectedType] = useState<"all" | AdvisoryType>("all");
  const [selectedLane, setSelectedLane] = useState("all");

  const carriers = useMemo(
    () => [...new Set(initialAdvisories.map((item) => item.carrier))],
    [initialAdvisories],
  );

  const types = useMemo(
    () => [...new Set(initialAdvisories.map((item) => item.advisory_type))],
    [initialAdvisories],
  );

  const lanes = useMemo(
    () => [
      ...new Set(initialAdvisories.flatMap((item) => item.affected_lanes)),
    ],
    [initialAdvisories],
  );

  const filteredAdvisories = useMemo(() => {
    return initialAdvisories.filter((advisory) => {
      const carrierMatch =
        selectedCarrier === "all" || advisory.carrier === selectedCarrier;

      const typeMatch =
        selectedType === "all" || advisory.advisory_type === selectedType;

      const laneMatch =
        selectedLane === "all" ||
        advisory.affected_lanes.includes(selectedLane);

      return carrierMatch && typeMatch && laneMatch;
    });
  }, [initialAdvisories, selectedCarrier, selectedType, selectedLane]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Carrier Advisories
        </h1>

        <p className="mt-1 text-muted-foreground">
          Monitor the latest carrier announcements affecting freight operations.
        </p>
      </div>

      {/* Filters */}
      <div className="rounded-2xl border bg-card p-5">
        <div className="grid gap-4 md:grid-cols-3">
          {/* Carrier */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Carrier</label>

            <select
              value={selectedCarrier}
              onChange={(e) => setSelectedCarrier(e.target.value)}
              className="h-10 w-full rounded-md border bg-background px-3 text-sm"
            >
              <option value="all">All carriers</option>

              {carriers.map((carrier) => (
                <option key={carrier} value={carrier}>
                  {carrier}
                </option>
              ))}
            </select>
          </div>

          {/* Type */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Advisory type</label>

            <select
              value={selectedType}
              onChange={(e) =>
                setSelectedType(e.target.value as "all" | AdvisoryType)
              }
              className="h-10 w-full rounded-md border bg-background px-3 text-sm"
            >
              <option value="all">All types</option>

              {types.map((type) => (
                <option key={type} value={type}>
                  {type.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </div>

          {/* Lane */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Affected lane</label>

            <select
              value={selectedLane}
              onChange={(e) => setSelectedLane(e.target.value)}
              className="h-10 w-full rounded-md border bg-background px-3 text-sm"
            >
              <option value="all">All lanes</option>

              {lanes.map((lane) => (
                <option key={lane} value={lane}>
                  {lane}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Result count */}
        <div className="mt-4 text-sm text-muted-foreground">
          Showing{" "}
          <span className="font-semibold text-foreground">
            {filteredAdvisories.length}
          </span>{" "}
          of{" "}
          <span className="font-semibold text-foreground">
            {initialAdvisories.length}
          </span>{" "}
          advisories
        </div>
      </div>

      {/* Feed */}
      <CarrierAdvisoryFeed advisories={filteredAdvisories} />
    </div>
  );
}
