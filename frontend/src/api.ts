import type { ShopifyOrder, ShippingResult } from "./types";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function fetchUnfulfilledOrders(): Promise<ShopifyOrder[]> {
  const res = await fetch(`${API_URL}/api/orders/unfulfilled`);
  if (!res.ok) throw new Error(`Failed to fetch orders: ${res.statusText}`);
  return res.json();
}

export async function processShipment(order: ShopifyOrder): Promise<ShippingResult> {
  const res = await fetch(`${API_URL}/api/shipping/process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(order),
  });
  if (!res.ok) throw new Error(`Failed to process shipment: ${res.statusText}`);
  return res.json();
}

export async function initializeAuth(): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${API_URL}/api/shipping/init-auth`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to initialize auth: ${res.statusText}`);
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/healthz`);
    return res.ok;
  } catch {
    return false;
  }
}
