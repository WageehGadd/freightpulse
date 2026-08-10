import { getCarrierAdvisories } from "@/lib/api";
import CarriersClient from "@/components/carriers/CarriersClient";

export default async function CarriersPage() {
  const advisories = await getCarrierAdvisories();

  return <CarriersClient initialAdvisories={advisories} />;
}
