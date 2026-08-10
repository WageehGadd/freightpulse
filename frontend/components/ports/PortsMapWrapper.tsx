"use client";

import dynamic from "next/dynamic";
import { Port } from "@/lib/types";

const PortCongestionMap = dynamic(() => import("./PortCongestionMap"), {
  ssr: false,
  loading: () => (
    <div className="h-[460px] w-full rounded-2xl bg-slate-900 animate-pulse flex items-center justify-center text-slate-400 text-sm font-medium">
      Loading Interactive Port Congestion Map...
    </div>
  ),
});

type Props = {
  ports: Port[];
  selectedPort?: Port | null;
  onSelectPort?: (port: Port) => void;
};

export default function PortsMapWrapper({
  ports,
  selectedPort,
  onSelectPort,
}: Props) {
  return (
    <PortCongestionMap
      ports={ports}
      selectedPort={selectedPort}
      onSelectPort={onSelectPort}
    />
  );
}
