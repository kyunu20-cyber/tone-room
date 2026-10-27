// Typed client for the EVA-95 FastAPI backend. Calls the backend directly (no Next proxy).
export const API = process.env.NEXT_PUBLIC_API ?? "http://127.0.0.1:8095";

export type Params = Record<string, number | boolean>;

export interface ClipInfo {
  width: number;
  height: number;
  fps: number;
  fps_str: string;
  duration: number;
  frame_count: number;
  codec: string;
  pix_fmt: string;
  is_vfr: boolean;
  has_audio: boolean;
  audio_codec: string | null;
  hdr: string | null;
  rotation: number;
}

export interface Clip {
  id: string;
  name: string;
  path: string;
  owned: boolean;
  info: ClipInfo;
}

export interface ParamDef {
  key: string;
  group: string;
  label: string;
  kind: "float" | "int" | "bool";
  neutral: number | boolean;
  min: number;
  max: number;
  step: number;
  hint: string;
}

export interface Schema {
  params: ParamDef[];
  default_preset: string;
  export: { resolution: string[]; fps: string[]; codec: string[]; quality: string[] };
}

export interface Preset {
  id: string;
  name: string;
  description: string;
  builtin: boolean;
  params: Params;
}

export interface Health {
  ffmpeg: boolean;
  error?: string;
  encoders: Record<string, boolean>;
  default_output: string;
}

export interface Correction {
  gains: number[];
  contrast: number;
  saturation: number;
  pivot: number;
  exposure_ev: number;
  wb: number[];
  notes: string[];
}

export interface Analysis {
  stats: Record<string, unknown>;
  correction: Correction;
}

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface Job {
  id: string;
  clip_id: string;
  name: string;
  status: JobStatus;
  progress: number;
  frames_done: number;
  frames_total: number;
  speed_fps: number;
  eta_s: number | null;
  output: string | null;
  error: string | null;
}

export interface PreviewJob {
  id: string;
  status: JobStatus;
  progress: number;
  original: string | null;
  processed: string | null;
  error: string | null;
  start: number;
  duration: number;
}

export interface ExportSettings {
  resolution: string;
  fps: string;
  codec: string;
  quality: string;
  output_dir: string;
  upscale: string;
}

/** Turns a FastAPI error body into a readable (Korean, from the backend) message. */
function detailOf(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? JSON.stringify(x)).join(", ");
  return `요청이 실패했습니다 (HTTP ${status})`;
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(API + path, init);
  } catch {
    throw new Error(`백엔드 서버(${API})에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.`);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(detailOf(body, res.status));
  }
  return res;
}

const json = <T,>(path: string, init?: RequestInit) => request(path, init).then((r) => r.json() as Promise<T>);
const post = <T,>(path: string, body?: unknown) =>
  json<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

export const api = {
  health: () => json<Health>("/api/health"),
  schema: () => json<Schema>("/api/schema"),
  clips: () => json<Clip[]>("/api/clips"),
  deleteClip: (id: string) => json<{ ok: boolean }>(`/api/clips/${id}`, { method: "DELETE" }),
  frameUrl: (id: string, t: number) => `${API}/api/clips/${id}/frame?t=${t.toFixed(3)}`,
  preview: (id: string, t: number, params: Params, fps: string, signal?: AbortSignal) =>
    request(`/api/clips/${id}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ t, params, fps }),
      signal,
    }).then((r) => r.blob()),
  analyze: (id: string, params: Params) => post<Analysis>(`/api/clips/${id}/analyze`, { t: 0, params }),
  previewClip: (id: string, start: number, params: Params, seconds = 10) =>
    post<PreviewJob>(`/api/clips/${id}/preview-clip`, { start, seconds, params }),
  previewJob: (id: string) => json<PreviewJob>(`/api/preview-jobs/${encodeURIComponent(id)}`),
  cacheUrl: (clipId: string, name: string) => `${API}/api/cache/${clipId}/${encodeURIComponent(name)}`,
  presets: () => json<Preset[]>("/api/presets"),
  savePreset: (name: string, params: Params) => post<Preset>("/api/presets", { name, params }),
  deletePreset: (id: string) => json<{ ok: boolean }>(`/api/presets/${encodeURIComponent(id)}`, { method: "DELETE" }),
  jobs: () => json<Job[]>("/api/jobs"),
  submitJobs: (clip_ids: string[], params: Params, exp: ExportSettings) =>
    post<Job[]>("/api/jobs", { clip_ids, params, export: exp }),
  cancelJob: (id: string) => post<Job>(`/api/jobs/${id}/cancel`),
  retryJob: (id: string) => post<Job>(`/api/jobs/${id}/retry`),
  removeJob: (id: string) => json<{ ok: boolean }>(`/api/jobs/${id}`, { method: "DELETE" }),
  reveal: (path: string) => post<{ ok: boolean }>("/api/reveal", { path }),
};

/** Raw-body upload via XHR so we get upload progress. */
export function uploadClip(file: File, onProgress: (p: number) => void): Promise<Clip> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/api/clips?filename=${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Clip);
      else reject(new Error(detailOf(body, xhr.status)));
    };
    xhr.onerror = () => reject(new Error(`백엔드 서버(${API})에 업로드할 수 없습니다.`));
    xhr.send(file);
  });
}

// ---------------------------------------------------------------- formatting helpers

export function timecode(t: number, fps: number): string {
  const f = Math.max(0, Math.round(t * fps));
  const r = Math.round(fps);
  const s = Math.floor(f / r);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}:${pad(f % r)}`;
}

export function duration(s: number): string {
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

export const ACCEPT = [".mp4", ".mov", ".mkv", ".webm"];
export const isVideoFile = (f: File) => ACCEPT.some((ext) => f.name.toLowerCase().endsWith(ext));
