export type Dataset = 'demo' | 'live';
export type Review = { status: 'proposed' | 'reviewed' | 'rejected'; reviewer: string | null; reviewed_at: string | null; note: string };
export type Source = { url: string; title: string; publisher: string; retrieved_at: string; sha256: string | null; license_note: string };
export type Span = { page: number; line_start: number; line_end: number; quote: string };
export type Leaf = { id: string; text: string; reference: Span };
export type TreeNode = { id: string; title: string; children: TreeNode[]; leaf_ids: string[] };
export type Party = { id: string; name: string; short_name: string; color: string; website: string };
export type Base = { id: string; dataset: Dataset; schema_version: string; review: Review };
export type Program = Base & {
  party_id: string; election_year: number; title: string; published_at: string;
  period_start: string; period_end: string | null; source: Source; markdown_path: string;
  leaves: Leaf[]; tree: TreeNode;
  pdf_url?: string | null; textless_pages?: number[]; transcription_note?: string;
  criteria_extraction?: { leaf_id: string; criterion_ids: string[]; abstention_reason: string | null }[];
};
export type AssessmentStatus = 'unassessed' | 'partial' | 'fulfilled' | 'contradicted' | 'mixed';
export type Criterion = Base & {
  program_id: string; party_id: string; leaf_id: string; title: string; description: string; test: string;
  tags: string[]; keywords: string[]; reference: Span; deadline: string | null;
  assessment: { status: AssessmentStatus; rationale: string; reviewer: string | null; assessed_at: string | null; evidence_ids: string[];
    method?: 'editorial' | 'agent'; score?: -2 | -1 | 0 | 1 | 2 | null; generation?: { model: string; input_sha256: string; prompt_version: string } | null; input_sha256?: string | null };
};
export type Law = Base & {
  title: string; official_title: string; published_at: string; status: 'promulgated'; kind: string;
  citation: string; source: Source; pdf_url: string | null; markdown_path: string | null;
  text_status: 'available' | 'needs_ocr'; passages: Leaf[]; tags: string[]; summary: string;
  matching: { status: string; candidate_ids: string[]; eligible_count: number; omitted_count: number; note: string; retrieval_version: string };
};
export type Impact = Base & {
  criterion_id: string; law_id: string; score: -2 | -1 | 0 | 1 | 2; confidence: number;
  rationale: string; law_passage_id: string; law_quote: string; criterion_quote: string;
  caveats: string[]; verification: 'passed' | 'needs_review';
  evaluation?: { status: 'accepted' | 'rejected' | 'missing_context'; model: string; method: string; input_sha256: string; decided_at: string } | null;
};
export type GroupVote = { group: string; party_id: string | null; yes: number; no: number; abstain: number; absent: number };
export type Vote = Base & { law_id: string; date: string; motion: string; type: string; source: Source; groups: GroupVote[] };
export type Data = { dataset: Dataset; parties: Party[]; programs: Program[]; criteria: Criterion[]; laws: Law[]; impacts: Impact[]; votes: Vote[] };
