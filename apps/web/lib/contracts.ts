export interface WorkerStatus {
  model: string;
  seen: string;
  online: boolean;
}
export interface Attachment {
  id: string;
  name: string;
  size: number;
}
export interface Task {
  title: string;
  text: string;
  city: string;
  address: string;
  deadline: string;
  budget: number | null;
  file_ids: string[];
}
export interface Offer {
  id: string;
  supplier: string;
  url: string;
  product_name: string;
  source_status: string;
  price_source_url?: string | null;
  price_region?: string | null;
  availability: string;
  unit_price: string;
  goods_total: string;
  purchase_quantity: string;
  excess_quantity?: string;
  packs?: number;
  cart_url?: string;
  delivery_cost: string | null;
  delivery_date: string | null;
  reason: string;
  fits: boolean;
}
export interface Material {
  id: string;
  name: string;
  quantity: string;
  unit: string;
  requirements: string;
  selected: Offer | null;
  offers: Offer[];
}
export interface Estimate {
  items: Material[];
  questions: { title: string; detail: string; url?: string }[];
  goods_total: string | null;
  delivery_total: string | null;
  complete: boolean;
  checked_at: string;
  model: string;
  summary: string;
  selection_reason: string;
  quotes_checked: number;
  quotes_verified: number;
}
export interface Job {
  id: string;
  created: string;
  title: string;
  state: string;
  note: string;
}
export interface Detail extends Job {
  payload: Task;
  result: Estimate | null;
}
export interface Bootstrap {
  user: { name: string; email: string };
  jobs: Job[];
  worker: WorkerStatus | null;
}
export interface SpeechInput {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: (event: {
    resultIndex: number;
    results: ArrayLike<ArrayLike<{ transcript: string }>>;
  }) => void;
  onerror: () => void;
  onend: () => void;
  stop: () => void;
  start: () => void;
}
declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechInput;
    webkitSpeechRecognition?: new () => SpeechInput;
  }
}
