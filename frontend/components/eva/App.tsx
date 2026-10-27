"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { ClipList } from "@/components/eva/ClipList";
import { Controls } from "@/components/eva/Controls";
import { Dropzone, type Upload, UploadList } from "@/components/eva/Dropzone";
import { ExportPanel } from "@/components/eva/ExportPanel";
import { JobQueue } from "@/components/eva/JobQueue";
import { ManualDrawer } from "@/components/eva/ManualDrawer";
import { ErrorLine } from "@/components/eva/ui";
import { Viewer } from "@/components/eva/Viewer";
import { API, api, type Clip, type ExportSettings, type Health, isVideoFile, type Job, type Params, type Preset, type Schema, uploadClip } from "@/lib/api";
import { cn } from "@/lib/utils";

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function App({ manual }: { manual: string }) {
  const [manualOpen, setManualOpen] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [connError, setConnError] = useState<string | null>(null);
  const [schema, setSchema] = useState<Schema | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetId, setPresetId] = useState("");
  const [params, setParams] = useState<Params>({});
  const [clips, setClips] = useState<Clip[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [exp, setExp] = useState<ExportSettings>({ resolution: "original", fps: "original", codec: "h264", quality: "high", output_dir: "", upscale: "sharp" });

  // ------------------------------------------------------------ boot
  const load = useCallback(
    () =>
      Promise.all([api.health(), api.schema(), api.presets(), api.clips(), api.jobs()]).then(
        ([h, s, p, c, j]) => {
          setHealth(h);
          setSchema(s);
          setPresets(p);
          setClips(c);
          setJobs(j);
          setActiveId((a) => a ?? c[0]?.id ?? null);
          const def = p.find((x) => x.id === s.default_preset) ?? p[0];
          const saved = loadLastSettings();
          const savedPreset = saved && p.find((x) => x.id === saved.presetId);
          if (savedPreset && saved) {
            // 마지막으로 쓰던 설정 복원(새 파라미터가 생겼으면 프리셋 값으로 채움)
            setPresetId(savedPreset.id);
            setParams({ ...savedPreset.params, ...saved.params });
          } else if (def) {
            setPresetId(def.id);
            setParams({ ...def.params });
          }
          setExp((e) => ({ ...e, output_dir: e.output_dir || h.default_output }));
          setConnError(null);
        },
        (e) => setConnError(msg(e)),
      ),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  // ------------------------------------------------------------ jobs polling
  const refreshJobs = useCallback(() => {
    api.jobs().then(setJobs).catch(() => {});
  }, []);
  const anyActive = jobs.some((j) => j.status === "queued" || j.status === "running");
  useEffect(() => {
    if (!anyActive) return;
    const id = setInterval(refreshJobs, 1000);
    return () => clearInterval(id);
  }, [anyActive, refreshJobs]);

  // ------------------------------------------------------------ uploads
  const patchUpload = (key: string, patch: Partial<Upload>) => setUploads((u) => u.map((x) => (x.key === key ? { ...x, ...patch } : x)));
  const keySeq = useRef(0);

  const addFiles = async (files: File[]) => {
    const entries = files.map((f) => ({ f, key: `u${++keySeq.current}` }));
    setUploads((u) => [
      ...u,
      ...entries.map(({ f, key }) =>
        isVideoFile(f)
          ? { key, name: f.name, progress: 0, status: "uploading" as const }
          : { key, name: f.name, progress: 0, status: "error" as const, error: "지원하지 않는 형식입니다. MP4, MOV, MKV, WEBM만 올릴 수 있습니다." },
      ),
    ]);
    for (const { f, key } of entries.filter((e) => isVideoFile(e.f))) {
      try {
        const clip = await uploadClip(f, (p) => patchUpload(key, { progress: p, status: p >= 1 ? "probing" : "uploading" }));
        setClips((c) => [...c, clip]);
        setActiveId((a) => a ?? clip.id);
        setUploads((u) => u.filter((x) => x.key !== key));
      } catch (e) {
        patchUpload(key, { status: "error", error: msg(e) });
      }
    }
  };

  // Drop anywhere on the page.
  const addFilesRef = useRef(addFiles);
  useEffect(() => {
    addFilesRef.current = addFiles;
  });
  const dragDepth = useRef(0);
  useEffect(() => {
    const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragDepth.current++;
      setDragging(true);
    };
    const over = (e: DragEvent) => hasFiles(e) && e.preventDefault();
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (!dragDepth.current) setDragging(false);
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragDepth.current = 0;
      setDragging(false);
      addFilesRef.current(Array.from(e.dataTransfer?.files ?? []));
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, []);

  const removeClip = async (id: string) => {
    try {
      await api.deleteClip(id);
      const next = clips.filter((x) => x.id !== id);
      setClips(next);
      if (activeId === id) setActiveId(next[0]?.id ?? null);
    } catch (e) {
      setError(msg(e));
    }
  };

  // ------------------------------------------------------------ undo / redo
  // 슬라이더를 끄는 동안의 연속 변경은 한 단계로 묶는다(마지막 변경 후 0.7초가 지나면 한 단계 끝).
  type Snap = { presetId: string; params: Params };
  const hist = useRef<{ past: Snap[]; future: Snap[] }>({ past: [], future: [] });
  const [canUndoRedo, setCanUndoRedo] = useState({ undo: false, redo: false });
  const syncHist = () => setCanUndoRedo({ undo: hist.current.past.length > 0, redo: hist.current.future.length > 0 });
  const cur = useRef<Snap>({ presetId: "", params: {} });
  const editing = useRef<ReturnType<typeof setTimeout> | null>(null);
  // ------------------------------------------------------------ 클립별 설정
  // 설정·되돌리기 기록은 클립마다 따로 둔다. 새 클립은 지금 보던 클립의 설정을 이어받는다.
  const perClip = useRef<Record<string, Snap>>(loadPerClip());
  const histMap = useRef<Record<string, { past: Snap[]; future: Snap[] }>>({});
  const prevActive = useRef<string | null>(null);

  useEffect(() => {
    const prev = prevActive.current;
    if (prev === activeId || !presets.length) return;
    if (prev) {
      perClip.current[prev] = cur.current;
      histMap.current[prev] = hist.current;
    }
    prevActive.current = activeId;
    if (!activeId) return;
    hist.current = histMap.current[activeId] ?? { past: [], future: [] };
    if (editing.current) clearTimeout(editing.current);
    editing.current = null;
    const snap = perClip.current[activeId];
    const preset = snap && presets.find((x) => x.id === snap.presetId);
    if (snap && preset) {
      setPresetId(snap.presetId);
      setParams({ ...preset.params, ...snap.params });
    }
    syncHist();
     
  }, [activeId, presets]);

  useEffect(() => {
    cur.current = { presetId, params };
    if (!presetId) return;
    saveLastSettings(cur.current);
    if (activeId && prevActive.current === activeId) {
      perClip.current[activeId] = cur.current;
      savePerClip(perClip.current);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presetId, params]);

  /** 지금 클립의 설정을 모든 클립에 복사(되돌리기 가능하도록 각 클립 기록에 남김). */
  const applyToAll = () => {
    for (const c of clips) {
      if (c.id === activeId) continue;
      const before = perClip.current[c.id] ?? cur.current;
      const h = (histMap.current[c.id] ??= { past: [], future: [] });
      h.past.push(before);
      h.future = [];
      perClip.current[c.id] = { ...cur.current };
    }
    savePerClip(perClip.current);
  };
  const settingsFor = (id: string): Snap => (id === activeId ? cur.current : (perClip.current[id] ?? cur.current));

  const record = useCallback((coalesce: boolean) => {
    if (!(coalesce && editing.current)) {
      hist.current.past.push(cur.current);
      if (hist.current.past.length > 100) hist.current.past.shift();
      hist.current.future = [];
      syncHist();
    }
    if (editing.current) clearTimeout(editing.current);
    editing.current = coalesce ? setTimeout(() => (editing.current = null), 700) : null;
  }, []);

  const undo = useCallback(() => {
    const prev = hist.current.past.pop();
    if (!prev) return;
    hist.current.future.push(cur.current);
    if (editing.current) clearTimeout(editing.current);
    editing.current = null;
    setPresetId(prev.presetId);
    setParams(prev.params);
    syncHist();
  }, []);
  const redo = useCallback(() => {
    const next = hist.current.future.pop();
    if (!next) return;
    hist.current.past.push(cur.current);
    setPresetId(next.presetId);
    setParams(next.params);
    syncHist();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
      const el = e.target as HTMLElement | null;
      if (el?.closest?.("textarea, [contenteditable=true]") || (el instanceof HTMLInputElement && el.type !== "range")) return;
      const k = e.key.toLowerCase();
      if (k === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if ((k === "z" && e.shiftKey) || k === "y") {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  // ------------------------------------------------------------ presets
  const selectPreset = (id: string) => {
    const p = presets.find((x) => x.id === id);
    if (!p) return;
    record(false);
    setPresetId(id);
    setParams({ ...p.params });
  };
  const setParam = useCallback(
    (k: string, v: number | boolean) => {
      record(true);
      setParams((p) => ({ ...p, [k]: v }));
    },
    [record],
  );
  const saveAs = async (name: string) => {
    const saved = await api.savePreset(name, params);
    setPresets(await api.presets());
    setPresetId(saved.id);
  };
  const deletePreset = async () => {
    await api.deletePreset(presetId);
    const list = await api.presets();
    setPresets(list);
    setPresetId(schema?.default_preset ?? list[0]?.id ?? "");
  };

  const exportClips = async (all: boolean) => {
    const ids = all ? clips.map((c) => c.id) : activeId ? [activeId] : [];
    // 클립마다 자기 설정으로 내보낸다
    for (const id of ids) await api.submitJobs([id], settingsFor(id).params, exp);
    refreshJobs();
  };

  const active = clips.find((c) => c.id === activeId) ?? null;
  const booted = !!schema && !!health;
  const encs = health?.encoders ?? {};

  return (
    <div className="flex min-h-screen flex-col xl:h-screen">
      {/* header */}
      <header className="flex min-w-0 shrink-0 items-stretch border-b border-rule">
        <div className="flex shrink-0 flex-col justify-center border-r border-rule px-4 py-2">
          <span className="text-xl leading-none font-bold tracking-[0.18em]">TONE ROOM</span>
        </div>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-5 gap-y-1 px-4 py-2 text-[10px] tracking-[0.16em] text-muted-foreground">
          <span>
            SYS:{" "}
            <span className={connError ? "text-destructive" : booted ? "text-eva" : ""}>{connError ? "OFFLINE" : booted ? "READY" : "BOOT…"}</span>
          </span>
          <span>
            FFMPEG: <span className={health?.ffmpeg === false ? "text-destructive" : "text-white"}>{health ? (health.ffmpeg ? "OK" : "MISSING") : "—"}</span>
          </span>
          <span className="hidden md:inline">
            ENC:{" "}
            {["h264_videotoolbox", "hevc_videotoolbox", "libx264", "libx265"]
              .filter((k) => encs[k])
              .map((k) => k.replace("_videotoolbox", "/VT").toUpperCase())
              .join(" ") || "—"}
          </span>
          <span>CLIPS: {String(clips.length).padStart(2, "0")}</span>
          <span className="hidden lg:inline">LINK: {API.replace(/^https?:\/\//, "")}</span>
          <span className="ml-auto hidden sm:inline">LOCAL PROCESSING ONLY</span>
        </div>
        <button
          type="button"
          onClick={() => setManualOpen(true)}
          className="shrink-0 border-l border-rule px-4 text-[11px] tracking-[0.16em] text-white outline-none hover:bg-eva hover:text-black focus-visible:bg-eva focus-visible:text-black"
        >
          ? MANUAL
        </button>
      </header>

      <div className="space-y-2 empty:hidden">
        {connError && (
          <div className="flex flex-wrap items-center gap-3 border-b border-destructive/60 bg-destructive/10 px-4 py-3 text-sm text-[#ffb3b3]">
            <span className="tracking-[0.14em] text-destructive">LINK DOWN</span>
            <span className="min-w-0 flex-1">{connError}</span>
            <button className="border border-rule-2 px-2 py-1 text-[11px] tracking-[0.12em] text-white hover:border-white" onClick={load}>
              RETRY
            </button>
          </div>
        )}
        {health && !health.ffmpeg && (
          <div className="border-b border-destructive/60 bg-destructive/10 px-4 py-3 text-sm text-[#ffb3b3]">
            <span className="mr-3 tracking-[0.14em] text-destructive">FFMPEG MISSING</span>
            {health.error ?? "ffmpeg를 찾을 수 없습니다."}
          </div>
        )}
        {error && (
          <div className="px-4 pt-2">
            <ErrorLine message={error} onClose={() => setError(null)} />
          </div>
        )}
      </div>

      <main className="min-w-0 xl:min-h-0 xl:flex-1">
        {!booted ? (
          <div className="flex h-[60vh] items-center justify-center text-xs tracking-[0.3em] text-muted-foreground">{connError ? "[ NO SIGNAL ]" : "[ SYS: BOOTING… ]"}</div>
        ) : !clips.length ? (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mx-auto w-full max-w-5xl p-4 md:p-8">
            <Dropzone onFiles={addFiles} dragging={dragging} />
            <p className="mt-3 text-center text-xs text-muted-foreground">
              처음이라면{" "}
              <button type="button" onClick={() => setManualOpen(true)} className="text-eva underline underline-offset-4">
                MANUAL
              </button>
              을 먼저 보세요.
            </p>
            <div className="mt-4">
              <UploadList uploads={uploads} onDismiss={(k) => setUploads((u) => u.filter((x) => x.key !== k))} />
            </div>
          </motion.div>
        ) : (
          <div className="grid min-w-0 grid-cols-1 xl:h-full xl:grid-cols-[264px_minmax(0,1fr)_360px]">
            <aside className="min-w-0 border-b border-rule xl:flex xl:min-h-0 xl:flex-col xl:border-r xl:border-b-0">
              <ClipList
                clips={clips}
                activeId={activeId}
                onSelect={setActiveId}
                onRemove={removeClip}
                onFiles={addFiles}
                uploads={uploads}
                onDismissUpload={(k) => setUploads((u) => u.filter((x) => x.key !== k))}
              />
            </aside>
            <div className="min-w-0 xl:min-h-0 xl:overflow-y-auto">
              {active ? <Viewer key={active.id} clip={active} params={params} fps={exp.fps} /> : <div className="p-6 text-xs text-muted-foreground">왼쪽 목록에서 클립을 고르세요.</div>}
              <div className="grid min-w-0 border-t border-rule lg:grid-cols-2">
                <div className="min-w-0 border-b border-rule lg:border-r lg:border-b-0">
                  <ExportPanel settings={exp} onChange={setExp} clipCount={clips.length} hasActive={!!active} encoders={encs} onExport={exportClips} />
                </div>
                <JobQueue jobs={jobs} refresh={refreshJobs} />
              </div>
            </div>
            <aside className="min-w-0 border-t border-rule xl:flex xl:min-h-0 xl:flex-col xl:border-t-0 xl:border-l">
              <Controls
                defs={schema.params}
                presets={presets}
                presetId={presetId}
                params={params}
                clipId={activeId}
                fps={exp.fps}
                onFps={(v) => setExp((e) => ({ ...e, fps: v }))}
                onPreset={selectPreset}
                setParam={setParam}
                onReset={() => selectPreset(presetId)}
                onUndo={undo}
                onApplyAll={clips.length > 1 ? applyToAll : undefined}
                onRedo={redo}
                canUndo={canUndoRedo.undo}
                canRedo={canUndoRedo.redo}
                onSaveAs={saveAs}
                onDelete={deletePreset}
              />
            </aside>
          </div>
        )}
      </main>

      <footer className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-rule px-4 py-2 text-[11px] text-muted-foreground">
        <span className="tracking-[0.16em]">[ NOTE ]</span>
        <span className="min-w-0">색·톤·필름 질감 보정 도구입니다. 실사 영상을 그림으로 바꾸지 않습니다. 모든 처리는 이 컴퓨터 안에서만 이뤄집니다.</span>
      </footer>

      <ManualDrawer markdown={manual} open={manualOpen} onClose={() => setManualOpen(false)} />

      <AnimatePresence>
        {dragging && clips.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className={cn("pointer-events-none fixed inset-3 z-50 flex items-center justify-center border border-dashed border-eva bg-black/80")}
          >
            <span className="text-2xl tracking-[0.3em] text-eva">[ DROP TO ADD ]</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ------------------------------------------------------------ 설정 기억(이 브라우저에만 저장)
const LAST_KEY = "eva95.lastSettings.v1";
const CLIPS_KEY = "eva95.clipSettings.v1";
function loadPerClip(): Record<string, { presetId: string; params: Params }> {
  try {
    return JSON.parse(localStorage.getItem(CLIPS_KEY) || "{}");
  } catch {
    return {};
  }
}
function savePerClip(v: Record<string, { presetId: string; params: Params }>) {
  try {
    localStorage.setItem(CLIPS_KEY, JSON.stringify(v));
  } catch {
    // 저장 불가면 무시
  }
}
function loadLastSettings(): { presetId: string; params: Params } | null {
  try {
    const raw = localStorage.getItem(LAST_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
function saveLastSettings(v: { presetId: string; params: Params }) {
  try {
    localStorage.setItem(LAST_KEY, JSON.stringify(v));
  } catch {
    // 저장 불가(사생활 보호 모드 등)면 무시
  }
}
