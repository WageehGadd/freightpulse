import { LaneSummary, RateLaneDetail, RateCompareData } from "@/lib/types";

import ratesAllMock from "@/mocks/rates-all.json";
import ratesLaneMock from "@/mocks/rates-lane.json";
import ratesCompareMock from "@/mocks/rates-compare.json";
import { ports } from "./mock/ports";
import carriersAdvisoriesMock from "@/mocks/carriers-advisories.json";
import { CarrierAdvisory } from "@/lib/types";
const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "dev-api-key";
const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS !== "false";

const headers = {
  "Content-Type": "application/json",
  "X-API-Key": API_KEY,
};

export async function getRatesAll(): Promise<LaneSummary[]> {
  if (USE_MOCKS) {
    return ratesAllMock.lanes as LaneSummary[];
  }

  try {
    const res = await fetch(`${API_BASE}/rates/all`, {
      headers,
      next: { revalidate: 60 },
    });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    const data = await res.json();
    return data.lanes || data;
  } catch (error) {
    console.warn(
      "Failed to fetch live /rates/all, falling back to mock data:",
      error,
    );
    return ratesAllMock.lanes as LaneSummary[];
  }
}

export async function getRateLane(
  lane: string,
  containerType: string = "40ft",
): Promise<RateLaneDetail> {
  if (USE_MOCKS) {
    const decodedLane = decodeURIComponent(lane);
    const mockMap = ratesLaneMock as Record<string, any>;
    const mockData = mockMap[decodedLane] || mockMap.default;
    return { ...mockData, container_type: containerType } as RateLaneDetail;
  }

  try {
    const encoded = encodeURIComponent(lane);
    const res = await fetch(
      `${API_BASE}/rates/${encoded}?container_type=${containerType}`,
      {
        headers,
        next: { revalidate: 60 },
      },
    );
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    return await res.json();
  } catch (error) {
    console.warn(
      `Failed to fetch live /rates/${lane}, falling back to mock data:`,
      error,
    );
    const decodedLane = decodeURIComponent(lane);
    const mockMap = ratesLaneMock as Record<string, any>;
    const mockData = mockMap[decodedLane] || mockMap.default;
    return { ...mockData, container_type: containerType } as RateLaneDetail;
  }
}

export async function getRateCompare(
  lane: string,
  containerType: string = "40ft",
): Promise<RateCompareData> {
  if (USE_MOCKS) {
    const decodedLane = decodeURIComponent(lane);
    const mockMap = ratesCompareMock as Record<string, any>;
    const mockData = mockMap[decodedLane] || mockMap.default;
    return {
      ...mockData,
      trade_lane: decodedLane,
      container_type: containerType,
    } as RateCompareData;
  }

  try {
    const encoded = encodeURIComponent(lane);
    const res = await fetch(
      `${API_BASE}/rates/compare?trade_lane=${encoded}&container_type=${containerType}`,
      { headers, next: { revalidate: 60 } },
    );
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    return await res.json();
  } catch (error) {
    console.warn(
      `Failed to fetch live /rates/compare, falling back to mock data:`,
      error,
    );
    const decodedLane = decodeURIComponent(lane);
    const mockMap = ratesCompareMock as Record<string, any>;
    const mockData = mockMap[decodedLane] || mockMap.default;
    return {
      ...mockData,
      trade_lane: decodedLane,
      container_type: containerType,
    } as RateCompareData;
  }
}

// Backward compatibility helper
export async function getRates(): Promise<LaneSummary[]> {
  return getRatesAll();
}
export async function getPorts() {
  return Promise.resolve(ports);
}
export async function getCarrierAdvisories(): Promise<CarrierAdvisory[]> {
  if (USE_MOCKS) {
    return carriersAdvisoriesMock as CarrierAdvisory[];
  }

  try {
    const res = await fetch(`${API_BASE}/carriers/advisories`, {
      headers,
      next: { revalidate: 300 },
    });

    if (!res.ok) {
      throw new Error(`HTTP error ${res.status}`);
    }

    return await res.json();
  } catch (error) {
    console.warn(
      "Failed to fetch live /carriers/advisories, falling back to mock data:",
      error,
    );

    return carriersAdvisoriesMock as CarrierAdvisory[];
  }
}
