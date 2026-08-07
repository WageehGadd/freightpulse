"use client";

import Link from "next/link";
import {
  LayoutDashboard,
  TrendingUp,
  Anchor,
  Truck,
  Route,
  Bell,
} from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
} from "@/components/ui/sidebar";

const items = [
  {
    title: "Dashboard",
    href: "/",
    icon: LayoutDashboard,
  },
  {
    title: "Rates",
    href: "/rates",
    icon: TrendingUp,
  },
  {
    title: "Ports",
    href: "/ports",
    icon: Anchor,
  },
  {
    title: "Carriers",
    href: "/carriers",
    icon: Truck,
  },
  {
    title: "Route Brief",
    href: "/route-brief",
    icon: Route,
  },
  {
    title: "Alerts",
    href: "/alerts",
    icon: Bell,
  },
];

export function AppSidebar() {
  return (
    <Sidebar>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>FreightPulse</SidebarGroupLabel>

          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton render={<Link href={item.href} />}>
                    <item.icon className="h-4 w-4" />
                    <span>{item.title}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
