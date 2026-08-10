"use client";

import { Port } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Anchor, Clock, AlertTriangle, Ship, Navigation, CheckCircle2, X } from "lucide-react";

type Props = {
  port: Port | null;
  isOpen: boolean;
  onClose: () => void;
  onFocusMap?: (port: Port) => void;
};

export default function PortDetailModal({
  port,
  isOpen,
  onClose,
  onFocusMap,
}: Props) {
  if (!port) return null;

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
    ? "Critical Congestion"
    : isElevated
    ? "Elevated Congestion"
    : "Normal Operations";

  const colorStyles = isCritical
    ? {
        badgeBg: "bg-red-500",
        statusBg: "bg-red-50 text-red-700 border-red-200",
        barColor: "bg-red-500",
      }
    : isElevated
    ? {
        badgeBg: "bg-amber-500",
        statusBg: "bg-amber-50 text-amber-700 border-amber-200",
        barColor: "bg-amber-500",
      }
    : {
        badgeBg: "bg-emerald-500",
        statusBg: "bg-emerald-50 text-emerald-700 border-emerald-200",
        barColor: "bg-emerald-500",
      };

  const dwellDays = port.avg_dwell_days ?? (port.congestion_pct > 70 ? 5.2 : 3.5);

  // Mock port advisories tailored to port severity
  const mockAdvisories = isCritical
    ? [
        {
          id: "1",
          title: "Terminal 2 Berth Congestion",
          severity: "high",
          message: `Heavy container backlog causing berth delays of 14-24h for incoming vessels at ${port.name}.`,
          time: "2 hours ago",
        },
        {
          id: "2",
          title: "Feeder Service Rerouting Advisory",
          severity: "medium",
          message: "Carriers advising potential diversion to alternate regional hub terminals.",
          time: "6 hours ago",
        },
      ]
    : isElevated
    ? [
        {
          id: "1",
          title: "Peak Gate Waiting Notice",
          severity: "medium",
          message: "Increased truck gate wait times expected during peak afternoon pickup windows.",
          time: "4 hours ago",
        },
      ]
    : [
        {
          id: "1",
          title: "Smooth Operational Flow",
          severity: "low",
          message: "Terminal berths and gate turnarounds operating within standard SLA schedules.",
          time: "1 hour ago",
        },
      ];

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg p-0 gap-0 overflow-hidden bg-white rounded-2xl border border-slate-200 shadow-xl">
        {/* Header Header Banner */}
        <div className="p-6 bg-slate-900 text-white relative">
          <button
            onClick={onClose}
            className="absolute top-4 right-4 h-8 w-8 rounded-full bg-white/10 flex items-center justify-center text-slate-300 hover:text-white hover:bg-white/20 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>

          <div className="flex items-center gap-4">
            <div
              className={`h-14 w-14 rounded-2xl ${colorStyles.badgeBg} flex items-center justify-center font-bold text-base text-white tracking-widest shadow-md shrink-0`}
            >
              {code}
            </div>

            <div>
              <DialogTitle className="text-xl font-bold text-white leading-tight">
                {port.name}
              </DialogTitle>
              <DialogDescription className="text-slate-400 text-sm mt-0.5 flex items-center gap-2">
                <span>{port.country}</span>
                <span>•</span>
                <span className="font-mono text-xs text-slate-400">
                  {port.latitude.toFixed(2)}°N, {port.longitude.toFixed(2)}°E
                </span>
              </DialogDescription>
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between">
            <span
              className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs font-semibold ${colorStyles.statusBg}`}
            >
              {isCritical ? (
                <AlertTriangle className="h-3.5 w-3.5 text-red-600" />
              ) : isElevated ? (
                <Clock className="h-3.5 w-3.5 text-amber-600" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
              )}
              {statusLabel}
            </span>

            {onFocusMap && (
              <button
                onClick={() => {
                  onFocusMap(port);
                  onClose();
                }}
                className="flex items-center gap-1.5 text-xs font-semibold text-sky-400 hover:text-sky-300 transition-colors cursor-pointer"
              >
                <Navigation className="h-3.5 w-3.5" />
                Focus on Map
              </button>
            )}
          </div>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-6 max-h-[70vh] overflow-y-auto">
          {/* Congestion Gauge Score */}
          <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-4 space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-semibold text-slate-700">Congestion Index</span>
              <span className="text-lg font-bold text-slate-900">
                {port.congestion_pct} / 100
              </span>
            </div>

            <div className="h-3 w-full bg-slate-200 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${colorStyles.barColor} transition-all duration-500`}
                style={{ width: `${port.congestion_pct}%` }}
              />
            </div>

            <p className="text-xs text-slate-500 pt-1">
              Calculated from vessel queuing density, dwell times, and berth occupancy rates.
            </p>
          </div>

          {/* Operational Metrics Grid */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-1">
              <div className="flex items-center gap-2 text-slate-500 text-xs font-medium">
                <Clock className="h-4 w-4 text-slate-400" />
                <span>Avg. Container Dwell</span>
              </div>
              <p className="text-2xl font-bold text-slate-900">{dwellDays} days</p>
              <p className="text-[11px] text-slate-400">Yard dwell time prior to gate out</p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-1">
              <div className="flex items-center gap-2 text-slate-500 text-xs font-medium">
                <Ship className="h-4 w-4 text-slate-400" />
                <span>Vessels Waiting</span>
              </div>
              <p className="text-2xl font-bold text-slate-900">{port.vessels_waiting}</p>
              <p className="text-[11px] text-slate-400">Anchored outside terminal gates</p>
            </div>
          </div>

          {/* Port Operational Advisories */}
          <div className="space-y-3">
            <h4 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Anchor className="h-4 w-4 text-slate-500" />
              Terminal Advisories & Alerts
            </h4>

            <div className="space-y-2">
              {mockAdvisories.map((adv) => (
                <div
                  key={adv.id}
                  className="p-3.5 rounded-xl border border-slate-200 bg-slate-50/70 text-xs space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-slate-900">{adv.title}</span>
                    <span className="text-[10px] text-slate-400">{adv.time}</span>
                  </div>
                  <p className="text-slate-600 leading-relaxed">{adv.message}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
