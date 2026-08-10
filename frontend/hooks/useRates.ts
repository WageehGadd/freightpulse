"use client";

import { useEffect, useState, useMemo } from "react";
import { LaneSummary, RateLaneDetail, RateCompareData } from "@/lib/types";
import { getRatesAll, getRateLane, getRateCompare } from "@/lib/api";

export function useRates() {
  const [lanes, setLanes] = useState<LaneSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState<string>("");
  const [containerType, setContainerType] = useState<string>("all");

  const refreshRates = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getRatesAll();
      setLanes(data);
    } catch (err: any) {
      setError(err.message || "Failed to load freight rates");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshRates();
  }, []);

  const filteredLanes = useMemo(() => {
    return lanes.filter((lane) => {
      const matchesSearch =
        search === "" ||
        lane.trade_lane.toLowerCase().includes(search.toLowerCase()) ||
        lane.source.toLowerCase().includes(search.toLowerCase());

      const matchesContainer =
        containerType === "all" || lane.container_type === containerType;

      return matchesSearch && matchesContainer;
    });
  }, [lanes, search, containerType]);

  return {
    lanes,
    filteredLanes,
    loading,
    error,
    search,
    setSearch,
    containerType,
    setContainerType,
    refreshRates,
  };
}

export function useRateDetail(lane: string, containerType: string = "40ft") {
  const [detail, setDetail] = useState<RateLaneDetail | null>(null);
  const [compare, setCompare] = useState<RateCompareData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    async function loadData() {
      try {
        setLoading(true);
        setError(null);
        const [detailData, compareData] = await Promise.all([
          getRateLane(lane, containerType),
          getRateCompare(lane, containerType),
        ]);
        if (isMounted) {
          setDetail(detailData);
          setCompare(compareData);
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err.message || "Failed to load rate details");
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    if (lane) {
      loadData();
    }

    return () => {
      isMounted = false;
    };
  }, [lane, containerType]);

  return { detail, compare, loading, error };
}
