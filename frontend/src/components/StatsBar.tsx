import { Package, Truck, AlertCircle, Clock } from "lucide-react";
import type { ShippingResult } from "../types";

interface StatsBarProps {
  totalOrders: number;
  shippingResults: Record<string, ShippingResult>;
  processingCount: number;
}

export default function StatsBar({ totalOrders, shippingResults, processingCount }: StatsBarProps) {
  const results = Object.values(shippingResults);
  const completedCount = results.filter((r) => r.status === "completed").length;
  const failedCount = results.filter((r) => r.status === "failed").length;
  const pendingCount = totalOrders - completedCount - failedCount - processingCount;

  const stats = [
    { label: "未処理", value: pendingCount, icon: Clock, color: "text-gray-600", bg: "bg-gray-100" },
    { label: "処理中", value: processingCount, icon: Package, color: "text-blue-600", bg: "bg-blue-100" },
    { label: "発送済み", value: completedCount, icon: Truck, color: "text-green-600", bg: "bg-green-100" },
    { label: "エラー", value: failedCount, icon: AlertCircle, color: "text-red-600", bg: "bg-red-100" },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {stats.map((stat) => (
        <div key={stat.label} className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${stat.bg}`}>
              <stat.icon className={stat.color} size={20} />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{stat.value}</p>
              <p className="text-xs text-gray-500">{stat.label}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
