import Link from "next/link";
import { ArrowLeft, Calendar, Database, Container } from "lucide-react";
import { getRateLane, getRateCompare } from "@/lib/api";
import TrendBadge from "@/components/rates/TrendBadge";
import RateTrendChart from "@/components/rates/RateTrendChart";
import RateCompareCard from "@/components/rates/RateCompareCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Metadata } from "next";

interface Props {
  params: Promise<{
    lane: string;
  }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { lane } = await params;
  const decodedLane = decodeURIComponent(lane);
  return {
    title: `${decodedLane} Rate Trend | FreightPulse`,
    description: `Detailed rate trend analysis and benchmarks for ${decodedLane} trade route.`,
  };
}

export default async function RateDetailPage({ params }: Props) {
  const { lane } = await params;
  const decodedLane = decodeURIComponent(lane);

  const [detail, compare] = await Promise.all([
    getRateLane(decodedLane),
    getRateCompare(decodedLane),
  ]);

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/rates"
          className="inline-flex items-center text-sm font-medium text-muted-foreground hover:text-foreground transition-colors mb-3"
        >
          <ArrowLeft className="h-4 w-4 mr-1" /> Back to Freight Rates
        </Link>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b pb-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold tracking-tight">{decodedLane}</h1>
              <TrendBadge trend={detail.trend} />
            </div>
            <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground mt-2">
              <span className="inline-flex items-center gap-1">
                <Container className="h-3.5 w-3.5" /> Container: {detail.container_type}
              </span>
              <span className="inline-flex items-center gap-1">
                <Database className="h-3.5 w-3.5" /> Source: {detail.source}
              </span>
              <span className="inline-flex items-center gap-1">
                <Calendar className="h-3.5 w-3.5" /> Last updated: August 2026
              </span>
            </div>
          </div>

          <div className="flex items-baseline gap-2 bg-muted/40 px-4 py-2 rounded-lg border">
            <span className="text-xs text-muted-foreground">Current Rate:</span>
            <span className="text-2xl font-bold font-mono text-primary">
              ${detail.current_rate_usd.toLocaleString()}
            </span>
            <span className="text-xs font-semibold text-muted-foreground">USD / FEU</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <RateTrendChart
            data={detail.history}
            lane={decodedLane}
            containerType={detail.container_type}
          />
        </div>
        <div className="lg:col-span-1">
          <RateCompareCard data={compare} lane={decodedLane} />
        </div>
      </div>

      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-lg font-bold">Historical Rate Series</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border overflow-hidden">
            <Table>
              <TableHeader className="bg-muted/50">
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead className="text-right">Spot Rate (USD)</TableHead>
                  <TableHead className="text-right">Variance vs Current</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detail.history
                  .slice()
                  .reverse()
                  .map((point) => {
                    const diff = point.rate_usd - detail.current_rate_usd;
                    const diffPct = ((diff / detail.current_rate_usd) * 100).toFixed(1);
                    return (
                      <TableRow key={point.date}>
                        <TableCell className="font-medium">{point.date}</TableCell>
                        <TableCell className="text-right font-mono font-semibold">
                          ${point.rate_usd.toLocaleString()}
                        </TableCell>
                        <TableCell
                          className={`text-right font-mono text-xs font-semibold ${
                            diff > 0
                              ? "text-red-600"
                              : diff < 0
                              ? "text-green-600"
                              : "text-muted-foreground"
                          }`}
                        >
                          {diff === 0 ? "Current" : `${diff > 0 ? "+" : ""}${diffPct}%`}
                        </TableCell>
                      </TableRow>
                    );
                  })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
