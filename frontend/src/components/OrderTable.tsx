import { Package, Truck, AlertCircle, Loader2 } from "lucide-react";
import type { ShopifyOrder, ShippingResult, ShippingStatusType } from "../types";

interface OrderTableProps {
  orders: ShopifyOrder[];
  shippingResults: Record<string, ShippingResult>;
  processingOrders: Set<string>;
  onProcess: (order: ShopifyOrder) => void;
}

const SIZE_LABELS: Record<string, string> = {
  S: "60cm",
  M: "80cm",
  L: "100cm",
  LL: "120cm",
};

function StatusBadge({ status }: { status: ShippingStatusType }) {
  const styles: Record<ShippingStatusType, string> = {
    pending: "bg-gray-100 text-gray-700",
    processing: "bg-blue-100 text-blue-700",
    completed: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
  };
  const labels: Record<ShippingStatusType, string> = {
    pending: "未処理",
    processing: "処理中",
    completed: "完了",
    failed: "エラー",
  };
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${styles[status]}`}>
      {labels[status]}
    </span>
  );
}

export default function OrderTable({ orders, shippingResults, processingOrders, onProcess }: OrderTableProps) {
  if (orders.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <Package className="mx-auto mb-3 text-gray-300" size={48} />
        <p className="text-lg font-medium">未発送の注文はありません</p>
        <p className="text-sm mt-1">Shopifyに新しい注文が入ると、ここに表示されます</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">注文番号</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">お届け先</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">商品</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">サイズ</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ステータス</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">操作</th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {orders.map((order) => {
            const result = shippingResults[order.order_id];
            const isProcessing = processingOrders.has(order.order_id);
            const status: ShippingStatusType = isProcessing
              ? "processing"
              : result?.status ?? "pending";

            return (
              <tr key={order.order_id} className="hover:bg-gray-50 transition-colors">
                <td className="px-4 py-4 whitespace-nowrap">
                  <span className="text-sm font-medium text-gray-900">{order.order_number}</span>
                </td>
                <td className="px-4 py-4">
                  <div className="text-sm text-gray-900">{order.shipping_address.name}</div>
                  <div className="text-xs text-gray-500">
                    〒{order.shipping_address.postal_code} {order.shipping_address.province}
                    {order.shipping_address.city}
                  </div>
                  <div className="text-xs text-gray-500">{order.shipping_address.address1}</div>
                </td>
                <td className="px-4 py-4">
                  {order.items.map((item, i) => (
                    <div key={i} className="text-sm text-gray-900">
                      {item.title} x{item.quantity}
                    </div>
                  ))}
                </td>
                <td className="px-4 py-4 whitespace-nowrap">
                  <span className="text-sm text-gray-700">
                    {order.package_size} ({SIZE_LABELS[order.package_size] ?? ""})
                  </span>
                </td>
                <td className="px-4 py-4 whitespace-nowrap">
                  <StatusBadge status={status} />
                  {result?.error_message && (
                    <div className="mt-1 flex items-center text-xs text-red-600">
                      <AlertCircle size={12} className="mr-1" />
                      {result.error_message}
                    </div>
                  )}
                </td>
                <td className="px-4 py-4 whitespace-nowrap">
                  <button
                    onClick={() => onProcess(order)}
                    disabled={isProcessing || status === "completed"}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md
                      bg-blue-600 text-white hover:bg-blue-700
                      disabled:bg-gray-300 disabled:cursor-not-allowed
                      transition-colors"
                  >
                    {isProcessing ? (
                      <>
                        <Loader2 size={14} className="animate-spin" />
                        処理中...
                      </>
                    ) : status === "completed" ? (
                      <>
                        <Truck size={14} />
                        発送済み
                      </>
                    ) : (
                      <>
                        <Truck size={14} />
                        発送する
                      </>
                    )}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
