export interface ShippingAddress {
  last_name: string;
  first_name: string;
  postal_code: string;
  province: string;
  city: string;
  address1: string;
  address2: string;
  phone: string;
}

export interface OrderItem {
  title: string;
  quantity: number;
}

export type PackageSize = "S" | "M" | "L" | "LL";

export interface ShopifyOrder {
  order_id: string;
  order_number: string;
  shipping_address: ShippingAddress;
  items: OrderItem[];
  package_size: PackageSize;
}

export type ShippingStatusType = "pending" | "processing" | "completed" | "failed";

export interface ShippingResult {
  order_id: string;
  order_number: string;
  status: ShippingStatusType;
  qr_code_path: string;
  error_message: string;
}
