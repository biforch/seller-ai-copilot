export interface PaginationMeta {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface PaginatedResponse<T> {
  items: T[];
  pagination: PaginationMeta;
}

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

export type FieldDecisionValue = 'accept' | 'reject' | 'pending';

export type ProposalStatus = 'reviewing' | 'approved' | 'rejected' | 'superseded';

export type ProposalListStatus = ProposalStatus | 'all';

export interface FieldDecisions {
  title: FieldDecisionValue;
  bullets: FieldDecisionValue;
  description: FieldDecisionValue;
  backend_keywords: FieldDecisionValue;
}

export interface ListingSnapshot {
  title: string;
  bullets: string[];
  description: string;
  backend_keywords: string[];
}

export interface ListingVersionSummary {
  id: string;
  product_id: string;
  version_number: number;
  source: string;
  title: string;
  bullets: string[];
  description: string;
  backend_keywords: string[];
  marketplace: string;
  language: string;
  generation_id: string | null;
  parent_version_id: string | null;
  created_by: string | null;
  created_at: string;
  is_current: boolean;
}

export interface ListingFieldDiffEntry {
  base: string | string[] | null;
  candidate: string | string[];
  changed: boolean;
}

export interface ListingProposalDiff {
  title: ListingFieldDiffEntry;
  bullets: ListingFieldDiffEntry;
  description: ListingFieldDiffEntry;
  backend_keywords: ListingFieldDiffEntry;
}

export interface ListingProposalSummary {
  id: string;
  status: ProposalStatus;
  revision: number;
  base_version_id: string | null;
}

export interface ListingProposalListItem {
  id: string;
  product_id: string;
  base_version_id: string | null;
  approved_version_id: string | null;
  status: ProposalStatus;
  revision: number;
  candidate_title: string;
  generation_request_id: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ListingProposal {
  id: string;
  product_id: string;
  base_version_id: string | null;
  candidate_snapshot: ListingSnapshot;
  field_decisions: FieldDecisions;
  status: ProposalStatus;
  revision: number;
  generation_request_id: string | null;
  approved_version_id: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ListingProposalDetail {
  proposal: ListingProposal;
  base_version: ListingVersionSummary | null;
  approved_version: ListingVersionSummary | null;
  diff: ListingProposalDiff;
}

export interface PatchProposalDecisionsResponse {
  proposal: ListingProposal;
}

export interface ApproveProposalResponse {
  proposal: ListingProposal;
  approved_version: ListingVersionSummary;
  replay: boolean;
}

export interface RejectProposalResponse {
  proposal: ListingProposal;
  replay: boolean;
}

export interface ListListingProposalsParams {
  page?: number;
  page_size?: number;
  status?: ProposalListStatus;
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

  generation_count?: number;

  updated_at?: string;

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

  products: PaginatedResponse<ProjectProductSummary>;

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

  proposal?: ListingProposalSummary;

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