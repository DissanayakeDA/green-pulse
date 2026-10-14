import { BellRing, ChartLine, Cpu, Droplets, LayoutDashboard, Leaf, Sparkles, type LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Monitor",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/readings", label: "Readings", icon: ChartLine },
      { href: "/watering", label: "Watering", icon: Droplets },
    ],
  },
  {
    group: "Insights",
    items: [{ href: "/assistant", label: "AI Assistant", icon: Sparkles }],
  },
  {
    group: "Setup",
    items: [
      { href: "/plants", label: "Plant profiles", icon: Leaf },
      { href: "/plant", label: "Plant & device", icon: Cpu },
      { href: "/alerts", label: "Email alerts", icon: BellRing },
    ],
  },
];

export function navItem(pathname: string): NavItem {
  return NAV.flatMap((g) => g.items).find((item) => item.href === pathname) ?? NAV[0].items[0];
}
