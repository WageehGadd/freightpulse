import { getPorts } from "@/lib/api";
import PortsClient from "@/components/ports/PortsClient";

export default async function PortsPage() {
  const ports = await getPorts();

  return (
    <main>
      <PortsClient initialPorts={ports} />
    </main>
  );
}
