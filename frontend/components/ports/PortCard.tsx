import { Port } from "@/lib/types";

type Props = {
  port: Port;
  onClick?: () => void;
  isSelected?: boolean;
};

export default function PortCard({ port, onClick, isSelected }: Props) {
  const code = (
    port.code ||
    port.id ||
    port.name.slice(0, 3)
  ).toUpperCase();

  const isCritical =
    port.congestion_level === "critical" || port.congestion_pct >= 80;
  const isElevated =
    !isCritical &&
    (port.congestion_level === "elevated" ||
      port.congestion_level === "high" ||
      port.congestion_pct >= 50);

  const statusLabel = isCritical
    ? "Critical"
    : isElevated
    ? "Elevated"
    : "Normal";

  const colorStyles = isCritical
    ? {
        badgeBg: "bg-red-500",
        statusText: "text-red-600",
        progressFill: "bg-red-500",
      }
    : isElevated
    ? {
        badgeBg: "bg-amber-500",
        statusText: "text-amber-600",
        progressFill: "bg-amber-500",
      }
    : {
        badgeBg: "bg-emerald-500",
        statusText: "text-emerald-600",
        progressFill: "bg-emerald-500",
      };

  const dwellDays = port.avg_dwell_days ?? (port.congestion_pct > 70 ? 5.2 : 3.5);

  return (
    <div
      onClick={onClick}
      className={`group py-5 transition-all duration-200 ${
        onClick ? "cursor-pointer hover:bg-slate-50/60" : ""
      } ${isSelected ? "bg-slate-50/80" : ""}`}
    >
      {/* Top Header Row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          {/* Port Code Badge */}
          <div
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${colorStyles.badgeBg} text-xs font-bold tracking-wider text-white shadow-xs`}
          >
            {code}
          </div>

          {/* Port Name & Country */}
          <div>
            <h3 className="font-bold text-slate-900 text-base leading-tight">
              {port.name}
            </h3>
            <p className="text-sm text-slate-500 mt-0.5">
              {port.country}
            </p>
          </div>
        </div>

        {/* Status Text Label */}
        <span className={`text-sm font-semibold ${colorStyles.statusText}`}>
          {statusLabel}
        </span>
      </div>

      {/* Middle Congestion Index & Progress Bar Line */}
      <div className="mt-4 space-y-1.5">
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-500">Congestion index</span>
          <span className="font-bold text-slate-900">
            {port.congestion_pct}/100
          </span>
        </div>

        {/* Progress bar track (horizontal line) */}
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className={`h-full rounded-full transition-all duration-500 ${colorStyles.progressFill}`}
            style={{ width: `${Math.min(100, Math.max(0, port.congestion_pct))}%` }}
          />
        </div>
      </div>

      {/* Bottom Metrics Row */}
      <div className="mt-3 flex items-center justify-between text-xs sm:text-sm text-slate-500">
        <div>
          Avg. dwell{" "}
          <span className="font-bold text-slate-900">{dwellDays} days</span>
        </div>
        <div>
          Waiting{" "}
          <span className="font-bold text-slate-900">
            {port.vessels_waiting} vessels
          </span>
        </div>
      </div>
    </div>
  );
}
