export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}


export interface ApiError {
  code: number;
  error_code?: string | null;
  message: string;
  detail: string | null;
}



export interface User {

  id: string;

  email: string;

  plan: string;

}



export interface LoginResponse {

  access_token: string;

  token_type: string;

  user: User;

}



export interface Project {

  id: string;

  name: string;

  description?: string | null;

  platform: string;

  market: string;

  status?: string;

  product_count?: number;

  created_at: string;

}



export interface ProjectProductSummary {

  id: string;

  name: string;

  category: string | null;

  platform: string;

  market: string;

  generations_count: number;

  created_at: string;

}



export interface ProjectDetail extends Project {

  updated_at?: string;

  products: ProjectProductSummary[];

}



export interface Product {

  id: string;

  name: string;

  category: string | null;

  platform: string;

  market: string;

  target_customer?: string | null;

  advantages?: string[] | null;

  created_at: string;

  generations_count?: number;

}



export interface Generation {

  id: string;

  type: string;

  project_id?: string;

  product_id?: string;

  input: Record<string, unknown>;

  output: Record<string, unknown>;

  tokens_used: number;

  created_at: string;

}



export interface ProductStats {

  total_generations: number;

  last_generated: string | null;

  generation_types: Record<string, number>;

}



export interface ListingScore {

  overall: number;

  title_seo: number;

  keyword_coverage: number;

  benefit_clarity: number;

  conversion_potential: number;

}



export interface NextAction {

  title: string;

  reason: string;

}



export interface ProductDetail extends Product {

  project: { id: string; name: string } | null;

  stats: ProductStats;

  score: ListingScore | null;

  next_actions: NextAction[];

  generations: Generation[];

}



export interface ListingResult {

  project_id?: string;

  product_id: string;

  title: string;

  bullets: string[];

  description: string;

  keywords: string[];

  score?: ListingScore;

  tokens_used: number;

}



export interface AnalyzeResult {

  project_id?: string;

  strengths: string[];

  weaknesses: string[];

  opportunities: string[];

  tokens_used: number;

}



export interface GenerateFormData {

  project_id?: string;

  product_id?: string;

  name: string;

  category: string;

  market: string;

  platform: string;

  target_customer?: string;

  advantages?: string[];

}



export interface AnalyzeFormData {

  project_id?: string;

  title: string;

  reviews: number;

  rating: number;

  description: string;

}