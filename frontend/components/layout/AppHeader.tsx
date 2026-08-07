"use client";

import { SidebarTrigger } from "@/components/ui/sidebar";
import { Bell } from "lucide-react";

export default function AppHeader() {
  return (
    <header className="flex h-16 items-center justify-between border-b bg-background px-6">
      <div className="flex items-center gap-3">
        <SidebarTrigger />
        <h1 className="text-xl font-semibold">FreightPulse</h1>
      </div>

      <button className="rounded-lg p-2 hover:bg-muted">
        <Bell className="h-5 w-5" />
      </button>
    </header>
  );
}
