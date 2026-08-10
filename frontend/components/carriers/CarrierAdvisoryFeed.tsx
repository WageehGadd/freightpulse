"use client";

import { CarrierAdvisory } from "@/lib/types";

type Props = {
  advisories: CarrierAdvisory[];
};

const severityStyles = {
  low: "bg-emerald-100 text-emerald-700",
  medium: "bg-amber-100 text-amber-700",
  high: "bg-red-100 text-red-700",
};

const typeLabels = {
  surcharge: "Surcharge",
  route_suspension: "Route Suspension",
  schedule_change: "Schedule Change",
  congestion: "Congestion",
};

export default function CarrierAdvisoryFeed({ advisories }: Props) {
  const sortedAdvisories = [...advisories].sort(
    (a, b) =>
      new Date(b.published_at).getTime() - new Date(a.published_at).getTime(),
  );

  return (
    <section className="rounded-2xl border bg-card p-6 shadow-sm">
      <div className="mb-5">
        <h2 className="text-xl font-bold">Carrier Advisories</h2>

        <p className="mt-1 text-sm text-muted-foreground">
          Latest carrier announcements affecting freight operations.
        </p>
      </div>

      <div className="max-h-[650px] space-y-4 overflow-y-auto pr-2">
        {sortedAdvisories.map((advisory) => (
          <article
            key={advisory.id}
            className="rounded-xl border p-5 transition hover:shadow-sm"
          >
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="rounded-md bg-primary px-2.5 py-1 text-xs font-bold text-primary-foreground">
                  {advisory.carrier}
                </span>

                <span className="rounded-md bg-muted px-2.5 py-1 text-xs font-medium">
                  {typeLabels[advisory.advisory_type]}
                </span>
              </div>

              <span
                className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                  severityStyles[advisory.impact_severity]
                }`}
              >
                {advisory.impact_severity}
              </span>
            </div>

            {/* Title */}
            <h3 className="mt-4 text-base font-bold">{advisory.title}</h3>

            {/* Summary */}
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {advisory.summary}
            </p>

            {/* Affected lanes */}
            <div className="mt-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Affected lanes
              </p>

              <div className="flex flex-wrap gap-2">
                {advisory.affected_lanes.map((lane) => (
                  <span
                    key={lane}
                    className="rounded-full border bg-background px-3 py-1 text-xs font-medium"
                  >
                    {lane}
                  </span>
                ))}
              </div>
            </div>

            {/* Footer */}
            <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
              <span>
                Effective:{" "}
                {advisory.effective_date
                  ? new Date(advisory.effective_date).toLocaleDateString()
                  : "Not specified"}
              </span>

              <span>
                Published:{" "}
                {new Date(advisory.published_at).toLocaleDateString()}
              </span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
