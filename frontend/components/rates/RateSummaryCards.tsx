import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LaneSummary } from "@/lib/types";
import { DollarSign, Route, TrendingUp } from "lucide-react";

interface RateSummaryCardsProps {
  lanes?: LaneSummary[];
}

export default function RateSummaryCards({ lanes = [] }: RateSummaryCardsProps) {
  const totalLanes = lanes.length;

  const averageRate =
    totalLanes > 0
      ? Math.round(lanes.reduce((sum, l) => sum + l.current_rate_usd, 0) / totalLanes)
      : 0;

  const risingLanesCount = lanes.filter((l) => l.trend === "rising").length;

  const highestLane = lanes.reduce(
    (max, l) => (l.current_rate_usd > (max?.current_rate_usd || 0) ? l : max),
    lanes[0]
  );

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Card className="shadow-xs">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Average Benchmark Rate
          </CardTitle>
          <DollarSign className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold font-mono">
            ${averageRate > 0 ? averageRate.toLocaleString() : "—"}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Across {totalLanes} tracked trade routes
          </p>
        </CardContent>
      </Card>

      <Card className="shadow-xs">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Active Trade Lanes
          </CardTitle>
          <Route className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold font-mono">{totalLanes}</div>
          <p className="text-xs text-muted-foreground mt-1">
            <span className="text-red-600 font-semibold">{risingLanesCount}</span> lanes currently rising
          </p>
        </CardContent>
      </Card>

      <Card className="shadow-xs">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Highest Spot Rate
          </CardTitle>
          <TrendingUp className="h-4 w-4 text-red-500" />
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold font-mono text-red-600 dark:text-red-400">
            ${highestLane ? highestLane.current_rate_usd.toLocaleString() : "—"}
          </div>
          <p className="text-xs text-muted-foreground mt-1 truncate">
            {highestLane ? `${highestLane.trade_lane} (${highestLane.container_type})` : "—"}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

export { RateSummaryCards };
