import { useState, useEffect, useCallback } from "react";
import Header from "./components/Header";
import StatsBar from "./components/StatsBar";
import OrderTable from "./components/OrderTable";
import { fetchUnfulfilledOrders, processShipment, checkHealth } from "./api";
import type { ShopifyOrder, ShippingResult } from "./types";

function App() {
  const [orders, setOrders] = useState<ShopifyOrder[]>([]);
  const [shippingResults, setShippingResults] = useState<Record<string, ShippingResult>>({});
  const [processingOrders, setProcessingOrders] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadOrders = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchUnfulfilledOrders();
      setOrders(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "注文の取得に失敗しました");
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleProcess = useCallback(async (order: ShopifyOrder) => {
    setProcessingOrders((prev) => new Set(prev).add(order.order_id));
    try {
      const result = await processShipment(order);
      setShippingResults((prev) => ({ ...prev, [order.order_id]: result }));
    } catch (e) {
      setShippingResults((prev) => ({
        ...prev,
        [order.order_id]: {
          order_id: order.order_id,
          order_number: order.order_number,
          status: "failed" as const,
          qr_code_path: "",
          error_message: e instanceof Error ? e.message : "処理に失敗しました",
        },
      }));
    } finally {
      setProcessingOrders((prev) => {
        const next = new Set(prev);
        next.delete(order.order_id);
        return next;
      });
    }
  }, []);

  useEffect(() => {
    checkHealth().then(setIsConnected);
    loadOrders();
  }, [loadOrders]);

  return (
    <div className="min-h-screen bg-gray-50">
      <Header isConnected={isConnected} onRefresh={loadOrders} isLoading={isLoading} />
      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        <StatsBar
          totalOrders={orders.length}
          shippingResults={shippingResults}
          processingCount={processingOrders.size}
        />

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
            {error}
          </div>
        )}

        <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
          <div className="px-4 py-3 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">未発送注文一覧</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Shopifyの未発送注文を表示しています。「発送する」ボタンでヤマト「スマホで送る」に自動入力します。
            </p>
          </div>
          <OrderTable
            orders={orders}
            shippingResults={shippingResults}
            processingOrders={processingOrders}
            onProcess={handleProcess}
          />
        </div>
      </main>
    </div>
  );
}

export default App;
