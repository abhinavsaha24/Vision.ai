"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { 
  LayoutDashboard, 
  LineChart, 
  ActivitySquare, 
  BrainCircuit, 
  Wallet,
  Settings
} from "lucide-react";
import { cn } from "@/utils/cn";

const navigation = [
  { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { name: "Charts", href: "/charts", icon: LineChart },
  { name: "Signals", href: "/signals", icon: ActivitySquare },
  { name: "Predictions", href: "/predictions", icon: BrainCircuit },
  { name: "Portfolio", href: "/portfolio", icon: Wallet },
  { name: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <div className="flex w-64 flex-col border-r border-slate-800 bg-slate-950 px-4 py-6 min-h-screen">
      <div className="flex items-center gap-2 px-2 mb-8">
        <div className="h-8 w-8 rounded-lg bg-indigo-500 flex items-center justify-center">
          <BrainCircuit className="h-5 w-5 text-white" />
        </div>
        <span className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-cyan-400">
          Vision AI
        </span>
      </div>

      <nav className="flex flex-1 flex-col gap-2">
        {navigation.map((item) => {
          const isActive = pathname === item.href || (pathname === '/' && item.href === '/dashboard');
          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200",
                isActive 
                  ? "bg-indigo-500/10 text-indigo-400" 
                  : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
              )}
            >
              <item.icon className="h-5 w-5" />
              {item.name}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto px-2 py-4 border-t border-slate-800">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center">
            <span className="text-sm font-medium text-slate-300">A</span>
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-medium text-slate-200">Abhinav Saha</span>
            <span className="text-xs text-indigo-400 font-semibold tracking-wider uppercase">Admin</span>
          </div>
        </div>
      </div>
    </div>
  );
}
