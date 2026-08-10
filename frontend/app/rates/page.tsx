import RatesClient from "@/components/rates/RatesClient";
import { getRatesAll } from "@/lib/api";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Rates | FreightPulse Intelligence",
  description: "Real-time rate tracking and trend analysis for all shipping lanes.",
};

export default async function RatesPage() {
  const rates = await getRatesAll();

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
          Rates
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          Real-time rate tracking and trend analysis for all shipping lanes
        </p>
      </div>

      <RatesClient initialLanes={rates} />
    </div>
  );
}
