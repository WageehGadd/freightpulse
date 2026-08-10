"use client";

import { useEffect } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";

import { Port } from "@/lib/types";

type Props = {
  ports: Port[];
  selectedPort?: Port | null;
  onSelectPort?: (port: Port) => void;
};

// Component to dynamically pan map when selectedPort changes
function MapCenterController({ selectedPort }: { selectedPort?: Port | null }) {
  const map = useMap();

  useEffect(() => {
    if (selectedPort) {
      map.flyTo([selectedPort.latitude, selectedPort.longitude], 7, {
        duration: 1.2,
      });
    }
  }, [selectedPort, map]);

  return null;
}

export default function PortCongestionMap({
  ports,
  selectedPort,
  onSelectPort,
}: Props) {
  return (
    <div className="relative rounded-2xl overflow-hidden border border-slate-200 shadow-sm bg-slate-900">
      <MapContainer
        center={[25, 55]}
        zoom={4}
        scrollWheelZoom={false}
        className="h-[460px] w-full z-0"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        <MapCenterController selectedPort={selectedPort} />

        {ports.map((port) => {
          const isCritical =
            port.congestion_level === "critical" || port.congestion_pct >= 80;
          const isElevated =
            !isCritical &&
            (port.congestion_level === "elevated" ||
              port.congestion_level === "high" ||
              port.congestion_pct >= 50);

          const isSelected = selectedPort?.id === port.id;

          const color = isCritical
            ? "#ef4444"
            : isElevated
            ? "#f59e0b"
            : "#10b981";

          const radius = Math.max(10, Math.min(24, port.congestion_pct / 4));

          const code = (
            port.code ||
            port.id ||
            port.name.slice(0, 3)
          ).toUpperCase();

          return (
            <CircleMarker
              key={port.id}
              center={[port.latitude, port.longitude]}
              radius={isSelected ? radius + 4 : radius}
              pathOptions={{
                color: isSelected ? "#090d16" : color,
                fillColor: color,
                fillOpacity: isSelected ? 0.9 : 0.7,
                weight: isSelected ? 3 : 2,
              }}
              eventHandlers={{
                click: () => onSelectPort?.(port),
              }}
            >
              <Popup className="custom-port-popup">
                <div className="p-1 min-w-[180px] space-y-2">
                  <div className="flex items-center gap-2">
                    <div
                      className="h-6 w-6 rounded-md flex items-center justify-center font-bold text-[10px] text-white"
                      style={{ backgroundColor: color }}
                    >
                      {code}
                    </div>
                    <div>
                      <h4 className="font-bold text-slate-900 text-sm leading-tight">
                        {port.name}
                      </h4>
                      <p className="text-xs text-slate-500">{port.country}</p>
                    </div>
                  </div>

                  <div className="text-xs space-y-1 border-t border-slate-100 pt-2">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Congestion Index:</span>
                      <span className="font-bold text-slate-900">
                        {port.congestion_pct}/100
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Vessels Waiting:</span>
                      <span className="font-bold text-slate-900">
                        {port.vessels_waiting}
                      </span>
                    </div>
                  </div>

                  {onSelectPort && (
                    <button
                      onClick={() => onSelectPort(port)}
                      className="w-full mt-2 rounded-lg bg-slate-900 py-1.5 text-center text-xs font-semibold text-white hover:bg-slate-800 transition-colors cursor-pointer"
                    >
                      Inspect Port Details
                    </button>
                  )}
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>

      {/* Legend Badge Overlay */}
      <div className="absolute bottom-4 left-4 z-10 flex items-center gap-3 rounded-xl border border-slate-200/80 bg-white/90 px-3.5 py-2 text-xs font-medium backdrop-blur-md shadow-xs">
        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-red-500 inline-block" />
          <span className="text-slate-700">Critical (&gt;80%)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-amber-500 inline-block" />
          <span className="text-slate-700">Elevated (50-79%)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-500 inline-block" />
          <span className="text-slate-700">Normal (&lt;50%)</span>
        </div>
      </div>
    </div>
  );
}
