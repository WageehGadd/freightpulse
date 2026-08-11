"use client";

import { CarrierAdvisory } from "@/lib/types";
import { Clock, Calendar, ExternalLink } from "lucide-react";

type Props = {
  advisories: CarrierAdvisory[];
};

export default function CarrierAdvisoryFeed({ advisories }: Props) {
  const sortedAdvisories = [...advisories].sort(
    (a, b) =>
      new Date(b.published_at).getTime() - new Date(a.published_at).getTime()
  );

  // Helper for Carrier Logo Avatar Color
  const getCarrierBadgeColor = (carrier: string) => {
    const c = carrier.toLowerCase();
    if (c.includes("maersk")) return "bg-[#0066ff] text-white";
    if (c.includes("cma")) return "bg-[#dc2626] text-white";
    if (c.includes("msc")) return "bg-slate-900 text-white";
    if (c.includes("hapag")) return "bg-amber-600 text-white";
    if (c.includes("evergreen")) return "bg-emerald-600 text-white";
    if (c.includes("one")) return "bg-pink-600 text-white";
    return "bg-slate-800 text-white";
  };

  // Helper for Severity / Status Badge styling
  const getSeverityStyle = (severity: string) => {
    const s = severity.toLowerCase();
    if (s === "elevated") {
      return "bg-amber-100/90 text-amber-800 border-amber-200/80";
    }
    if (s === "advisory") {
      return "bg-blue-100/90 text-blue-700 border-blue-200/80";
    }
    if (s === "critical" || s === "high") {
      return "bg-red-100/90 text-red-700 border-red-200/80";
    }
    if (s === "normal" || s === "low") {
      return "bg-emerald-100/90 text-emerald-700 border-emerald-200/80";
    }
    return "bg-slate-100 text-slate-700 border-slate-200";
  };

  // Format type label
  const formatTypeLabel = (type: string) => {
    return type.replaceAll("_", " ");
  };

  // Format Published Date (e.g. Published Today, 09:24 or Published Yesterday, 16:42)
  const formatPublishedAt = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      const now = new Date();
      const diffHours = (now.getTime() - d.getTime()) / (1000 * 60 * 60);

      const timeString = d.toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });

      if (diffHours < 24) {
        return `Published Today, ${timeString}`;
      } else if (diffHours < 48) {
        return `Published Yesterday, ${timeString}`;
      } else {
        return `Published ${d.toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
        })}, ${timeString}`;
      }
    } catch {
      return `Published ${dateStr}`;
    }
  };

  // Format Effective Date Range (e.g. Effective Aug 24 – Sep 02)
  const formatEffectiveDate = (start: string | null, end?: string | null) => {
    if (!start) return "Not specified";
    try {
      const startDate = new Date(start);
      const startStr = startDate.toLocaleDateString("en-US", {
        month: "short",
        day: "2-digit",
      });

      if (end) {
        const endDate = new Date(end);
        const endStr = endDate.toLocaleDateString("en-US", {
          month: "short",
          day: "2-digit",
        });
        return `Effective ${startStr} – ${endStr}`;
      }

      return `Effective ${startStr}`;
    } catch {
      return `Effective ${start}`;
    }
  };

  return (
    <section className="space-y-5">
      {/* Header Bar */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Latest advisories</h2>
          <p className="mt-0.5 text-sm text-slate-500">
            {advisories.length} updates matching your filters
          </p>
        </div>

        <button
          onClick={() => {}}
          className="text-sm font-semibold text-blue-600 hover:text-blue-700 hover:underline cursor-pointer"
        >
          View archive
        </button>
      </div>

      {/* Advisories Stacked Cards */}
      <div className="space-y-4">
        {sortedAdvisories.map((advisory) => {
          const avatarColor = getCarrierBadgeColor(advisory.carrier);
          const initial = advisory.carrier.charAt(0).toUpperCase();

          return (
            <article
              key={advisory.id}
              className="rounded-2xl border border-slate-200/90 bg-white p-6 shadow-2xs hover:border-slate-300 transition-all duration-200"
            >
              {/* Top Header Row */}
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  {/* Carrier Logo Avatar */}
                  <div
                    className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${avatarColor} text-lg font-bold shadow-xs`}
                  >
                    {initial}
                  </div>

                  {/* Carrier Name & Category */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="font-bold text-slate-900 text-base leading-tight">
                      {advisory.carrier}
                    </span>
                    <span className="text-slate-400 font-normal">·</span>
                    <span className="text-sm text-slate-500 font-normal capitalize">
                      {formatTypeLabel(advisory.advisory_type)}
                    </span>
                  </div>
                </div>

                {/* Severity Status Pill */}
                <span
                  className={`rounded-full border px-3 py-0.5 text-xs font-semibold capitalize ${getSeverityStyle(
                    advisory.impact_severity
                  )}`}
                >
                  {advisory.impact_severity}
                </span>
              </div>

              {/* Title */}
              <h3 className="mt-3.5 text-lg font-bold text-slate-900 leading-snug">
                {advisory.title}
              </h3>

              {/* Summary */}
              <p className="mt-2 text-sm leading-relaxed text-slate-600 font-normal">
                {advisory.summary}
              </p>

              {/* Affected Route Lanes Pills */}
              {advisory.affected_lanes && advisory.affected_lanes.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {advisory.affected_lanes.map((lane) => (
                    <span
                      key={lane}
                      className="rounded-lg border border-slate-200/80 bg-slate-100/80 px-3 py-1.5 text-xs font-medium text-slate-700 inline-flex items-center gap-1"
                    >
                      {lane.includes("→") ? lane : lane.replace("-", " → ")}
                    </span>
                  ))}
                </div>
              )}

              {/* Footer Metadata Row */}
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3.5 text-xs text-slate-500">
                <div className="flex items-center gap-4 flex-wrap">
                  {/* Published Time */}
                  <span className="flex items-center gap-1.5">
                    <Clock className="h-3.5 w-3.5 text-slate-400" />
                    {formatPublishedAt(advisory.published_at)}
                  </span>

                  {/* Effective Dates */}
                  <span className="flex items-center gap-1.5">
                    <Calendar className="h-3.5 w-3.5 text-slate-400" />
                    {formatEffectiveDate(
                      advisory.effective_date,
                      advisory.effective_end_date
                    )}
                  </span>
                </div>

                {/* Read Full Advisory Link */}
                <a
                  href={advisory.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 font-semibold text-blue-600 hover:text-blue-700 hover:underline cursor-pointer"
                >
                  Read full advisory
                  <ExternalLink className="h-3 w-3" />
                </a>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
