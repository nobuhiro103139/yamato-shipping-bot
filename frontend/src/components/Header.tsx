import { Truck, RefreshCw, Settings } from "lucide-react";

interface HeaderProps {
  isConnected: boolean;
  onRefresh: () => void;
  isLoading: boolean;
}

export default function Header({ isConnected, onRefresh, isLoading }: HeaderProps) {
  return (
    <header className="bg-white border-b border-gray-200 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="bg-blue-600 p-2 rounded-lg">
            <Truck className="text-white" size={24} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Yamato Shipping Bot</h1>
            <p className="text-xs text-gray-500">TechRental 配送自動化ダッシュボード</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${isConnected ? "bg-green-500" : "bg-red-500"}`} />
            <span className="text-xs text-gray-500">
              {isConnected ? "API接続中" : "API未接続"}
            </span>
          </div>
          <button
            onClick={onRefresh}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md
              border border-gray-300 bg-white text-gray-700 hover:bg-gray-50
              disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <RefreshCw size={14} className={isLoading ? "animate-spin" : ""} />
            更新
          </button>
          <button className="p-2 text-gray-400 hover:text-gray-600 transition-colors">
            <Settings size={18} />
          </button>
        </div>
      </div>
    </header>
  );
}
