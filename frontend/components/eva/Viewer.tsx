"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { Slider } from "@/components/ui/slider";
import { api, type Clip, type Params, timecode } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Bar, Btn, Head, Seg } from "./ui";

type Mode = "split" | "compare";
type Playback =
  | { state: "idle" }
  | { state: "rendering"; progress: number }
  | { state: "error"; error: string }
  | { state: "ready"; seg: Segment; resumeAt: number };
type Segment = { start: number; dur: number; orig: string; proc: string; key: string };

const FIRST_SEG = 4; // 첫 구간(초): 짧게 만들어 빨리 재생 시작
const SEG = 10; // 이후 구간(초)

/** Mirrors backend video_io.output_fps so the stills land on the same frame grid as the render. */
function outputFps(clipFps: number, fps: string, cadence: boolean): number {
  const table: Record<string, number> = { "23.976": 24000 / 1001, "24": 24, "30": 30 };
  if (fps in table) return table[fps];
  if (cadence) return Math.abs(clipFps - 24000 / 1001) < 1e-3 ? clipFps : 24;
  return clipFps;
}

/** Keeps showing the previous image until the next one has loaded (no flicker while scrubbing). */
function usePreloaded(url: string): string {
  const [shown, setShown] = useState(url);
  useEffect(() => {
    const img = new Image();
    img.onload = () => setShown(url);
    img.src = url;
    return () => {
      img.onload = null;
    };
  }, [url]);
  return shown;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function Viewer({ clip, params, fps }: { clip: Clip; params: Params; fps: string }) {
  const { info } = clip;
  const cadence = Boolean(params.cadence_12fps);
  const ofps = outputFps(info.fps, fps, cadence);
  const frameDur = 1 / ofps;
  const maxT = Math.max(0, info.duration - frameDur);
  const totalFrames = Math.max(1, Math.floor(info.duration * ofps));

  const [t, setT] = useState(0);
  const frame = Math.min(Math.round(t * ofps), totalFrames - 1);
  const snapT = (cadence ? frame - (frame % 2) : frame) / ofps;

  const [mode, setMode] = useState<Mode>("split");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [wipe, setWipe] = useState(50);
  const [full, setFull] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  // ------------------------------------------------------------ stills
  const origSrc = usePreloaded(api.frameUrl(clip.id, snapT));
  const [procSrc, setProcSrc] = useState<string | null>(null);
  const [settledKey, setSettledKey] = useState("");
  const [procError, setProcError] = useState<string | null>(null);
  const reqId = useRef(0);
  const procUrlRef = useRef<string | null>(null);
  const paramsKey = JSON.stringify(params);
  const reqKey = `${clip.id}|${snapT}|${fps}|${paramsKey}`;
  const rendering = settledKey !== reqKey;

  useEffect(() => {
    const id = ++reqId.current;
    const timer = setTimeout(async () => {
      try {
        const blob = await api.preview(clip.id, snapT, JSON.parse(paramsKey), fps);
        if (id !== reqId.current) return; // a newer request superseded this one
        const url = URL.createObjectURL(blob);
        if (procUrlRef.current) URL.revokeObjectURL(procUrlRef.current);
        procUrlRef.current = url;
        setProcSrc(url);
        setProcError(null);
      } catch (e) {
        if (id === reqId.current) setProcError(errMsg(e));
      } finally {
        if (id === reqId.current) setSettledKey(reqKey);
      }
    }, 150);
    return () => clearTimeout(timer);
  }, [clip.id, snapT, paramsKey, fps, reqKey]);

  useEffect(
    () => () => {
      if (procUrlRef.current) URL.revokeObjectURL(procUrlRef.current);
    },
    [],
  );

  // ------------------------------------------------------------ frame stepping
  const step = useCallback((n: number) => setT((v) => Math.min(maxT, Math.max(0, (Math.round(v * ofps) + n) / ofps))), [maxT, ofps]);


  // ------------------------------------------------------------ zoom / pan / wipe
  const setZoomLevel = (z: number) => {
    setZoom(z);
    setPan((p) => clampPan(p, z));
  };
  const drag = useRef<{ kind: "pan" | "wipe"; x: number; y: number; pan: { x: number; y: number } } | null>(null);

  const wipeFromEvent = (clientX: number) => {
    const r = stageRef.current?.getBoundingClientRect();
    if (r) setWipe(Math.min(100, Math.max(0, ((clientX - r.left) / r.width) * 100)));
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const onHandle = (e.target as HTMLElement).dataset.handle === "wipe";
    const kind = mode === "compare" && (onHandle || zoom === 1) ? "wipe" : zoom > 1 ? "pan" : null;
    if (!kind) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { kind, x: e.clientX, y: e.clientY, pan };
    if (kind === "wipe") wipeFromEvent(e.clientX);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    if (d.kind === "wipe") return wipeFromEvent(e.clientX);
    // In split mode each pane is half the stage width; pan is expressed in % of a pane.
    const pane = paneSize();
    if (!pane) return;
    setPan(clampPan({ x: d.pan.x + ((e.clientX - d.x) / (pane.w * zoom)) * 100, y: d.pan.y + ((e.clientY - d.y) / (pane.h * zoom)) * 100 }, zoom));
  };

  const paneSize = () => {
    const r = stageRef.current?.getBoundingClientRect();
    if (!r) return null;
    return { w: mode === "split" ? r.width / 2 : r.width, h: r.height };
  };

  const mediaStyle: React.CSSProperties = {
    transform: `scale(${zoom}) translate(${pan.x}%, ${pan.y}%)`,
    transformOrigin: "center",
  };

  // ------------------------------------------------------------ fullscreen
  useEffect(() => {
    const on = () => setFull(document.fullscreenElement === rootRef.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  const toggleFull = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else rootRef.current?.requestFullscreen().catch(() => {});
  };

  // ------------------------------------------------------------ continuous playback (segments)
  // 클립을 구간으로 나눠 보정해 이어 재생한다. 지금 구간이 재생되는 동안 다음 구간을 미리 만든다.
  const [pb, setPb] = useState<Playback>({ state: "idle" });
  const pbToken = useRef(0);
  const origV = useRef<HTMLVideoElement>(null);
  const procV = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [pbTime, setPbTime] = useState(0);
  const [updating, setUpdating] = useState(false);
  const [buffering, setBuffering] = useState(false);
  const nextRef = useRef<{ start: number; len: number; promise: Promise<Segment | null> } | null>(null);
  const originRef = useRef(0);
  const paramsRef = useRef(params);
  useEffect(() => {
    paramsRef.current = params;
  }, [params]);

  useEffect(
    () => () => {
      pbToken.current++;
    },
    [],
  );

  const renderSeg = async (start: number, seconds: number, token: number, onProgress?: (p: number) => void): Promise<Segment> => {
    const prm = paramsRef.current;
    const key = JSON.stringify(prm);
    let job = await api.previewClip(clip.id, start, prm, seconds);
    while (job.status === "queued" || job.status === "running") {
      if (token !== pbToken.current) throw new Error("cancelled");
      onProgress?.(job.progress);
      await sleep(250);
      job = await api.previewJob(job.id);
    }
    if (job.status !== "done" || !job.original || !job.processed) throw new Error(job.error || "미리보기 구간을 만들지 못했습니다.");
    return { start: job.start, dur: job.duration, orig: api.cacheUrl(clip.id, job.original), proc: api.cacheUrl(clip.id, job.processed), key };
  };

  /** from 위치부터 재생 시작. 첫 구간은 짧게 만들어 빨리 시작한다. */
  const startPlayback = async (from = snapT) => {
    const token = ++pbToken.current;
    originRef.current = from;
    nextRef.current = null;
    setUpdating(false);
    setBuffering(false);
    setPb({ state: "rendering", progress: 0 });
    try {
      const seg = await renderSeg(from, FIRST_SEG, token, (p) => token === pbToken.current && setPb({ state: "rendering", progress: p }));
      if (token === pbToken.current) setPb({ state: "ready", seg, resumeAt: 0 });
    } catch (e) {
      if (token === pbToken.current) setPb({ state: "error", error: errMsg(e) });
    }
  };

  /** 설정이 바뀌었을 때: 재생은 그대로 두고 지금 구간을 새 설정으로 다시 만들어 같은 위치에서 이어 붙인다. */
  const refreshPlayback = async () => {
    if (pb.state !== "ready") return;
    const token = ++pbToken.current;
    const cur = pb.seg;
    nextRef.current = null;
    setUpdating(true);
    try {
      const seg = await renderSeg(cur.start, cur.dur, token);
      if (token === pbToken.current) setPb({ state: "ready", seg, resumeAt: origV.current?.currentTime ?? 0 });
    } catch (e) {
      if (token === pbToken.current) setPb({ state: "error", error: errMsg(e) });
    } finally {
      if (token === pbToken.current) setUpdating(false);
    }
  };

  const stopPlayback = () => {
    pbToken.current++;
    nextRef.current = null;
    setPb({ state: "idle" });
    setPlaying(false);
    setUpdating(false);
    setBuffering(false);
  };

  const isVideo = pb.state === "ready";
  const seg = pb.state === "ready" ? pb.seg : null;

  useEffect(() => {
    if (pb.state !== "ready") return;
    const m = origV.current;
    const s = procV.current;
    if (!m || !s) return;
    const cur = pb.seg;
    const sync = () => {
      if (Math.abs(s.currentTime - m.currentTime) > 0.05) s.currentTime = m.currentTime;
    };
    const onPlay = () => {
      sync();
      s.play().catch(() => {});
      setPlaying(true);
    };
    const onPause = () => {
      s.pause();
      sync();
      if (!m.ended) setPlaying(false);
    };
    const onTime = () => {
      sync();
      setPbTime(m.currentTime);
      // 다음 구간 미리 만들기
      const nextStart = cur.start + cur.dur;
      if (!nextRef.current && m.currentTime > 0.2 && nextStart < info.duration - 0.1) {
        const token = pbToken.current;
        // 구간을 4 → 5 → 7 → 9 → 10초로 늘려 간다. 4K 원본도 구간을 재생 시간의 약 0.7배 안에 만들므로 1.3배씩이면 끊기지 않는다.
        const len = Math.min(SEG, Math.round(cur.dur * 1.3));
        nextRef.current = { start: nextStart, len, promise: renderSeg(nextStart, len, token).catch(() => null) };
      }
    };
    const onEnded = async () => {
      const token = pbToken.current;
      const n = nextRef.current;
      nextRef.current = null;
      if (!n) {
        // 클립 끝: 재생을 시작했던 위치로 돌아가 반복
        startPlayback(originRef.current);
        return;
      }
      setBuffering(true);
      let next = await n.promise;
      if (token !== pbToken.current) return;
      if (!next || next.key !== JSON.stringify(paramsRef.current)) {
        next = await renderSeg(n.start, n.len, token).catch(() => null);
        if (token !== pbToken.current) return;
      }
      setBuffering(false);
      if (next) setPb({ state: "ready", seg: next, resumeAt: 0 });
      else setPb({ state: "error", error: "다음 구간을 만들지 못했습니다." });
    };
    m.addEventListener("play", onPlay);
    m.addEventListener("pause", onPause);
    m.addEventListener("seeked", sync);
    m.addEventListener("timeupdate", onTime);
    m.addEventListener("ended", onEnded);
    if (pb.resumeAt > 0) {
      m.currentTime = pb.resumeAt;
      s.currentTime = pb.resumeAt;
    }
    // 원본이 이미 재생 중이면 play 이벤트가 다시 오지 않으므로 직접 맞춘다
    const startBoth = () => {
      sync();
      s.play().catch(() => {});
      setPlaying(true);
    };
    m.play().then(startBoth).catch(() => {
      // Autoplay with sound can be blocked; retry muted.
      m.muted = true;
      m.play().then(startBoth).catch(() => {});
    });
    return () => {
      m.removeEventListener("play", onPlay);
      m.removeEventListener("pause", onPause);
      m.removeEventListener("seeked", sync);
      m.removeEventListener("timeupdate", onTime);
      m.removeEventListener("ended", onEnded);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pb]);

  const togglePlay = () => {
    const m = origV.current;
    if (m) (m.paused ? m.play() : Promise.resolve(m.pause())).catch(() => {});
  };

  // 재생 중 타임라인을 움직이면 그 위치부터 다시 재생
  const seekTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seekPlayback = (v: number) => {
    setT(v);
    setPbTime(0);
    if (seekTimer.current) clearTimeout(seekTimer.current);
    seekTimer.current = setTimeout(() => startPlayback(Math.min(maxT, Math.max(0, v))), 250);
  };

  const media = (which: "orig" | "proc") => {
    if (pb.state === "ready")
      return (
        <video
          ref={which === "orig" ? origV : procV}
          src={which === "orig" ? pb.seg.orig : pb.seg.proc}
          muted={which === "proc"}
          playsInline
          preload="auto"
          className="pointer-events-none size-full object-contain select-none"
          style={mediaStyle}
        />
      );
    const src = which === "orig" ? origSrc : procSrc;
    if (!src) return null;
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src} alt={which === "orig" ? "원본 프레임" : "보정 프레임"} draggable={false} className="pointer-events-none size-full object-contain select-none" style={mediaStyle} />;
  };

  const tag = (label: string, side: "left" | "right") => (
    <span className={cn("pointer-events-none absolute top-2 z-10 bg-black/70 px-1.5 py-0.5 text-[10px] tracking-[0.16em]", side === "left" ? "left-2" : "right-2")}>
      {label}
    </span>
  );

  const status = (
    <span className="pointer-events-none absolute right-2 bottom-2 z-10 flex flex-col items-end gap-1 text-[10px] tracking-[0.14em]">
      <AnimatePresence>
        {((rendering && !isVideo) || buffering) && (
          <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="bg-black/70 px-1.5 py-0.5 text-eva">
            {buffering ? "BUFFERING…" : "RENDERING…"}
          </motion.span>
        )}
      </AnimatePresence>
      {procError && !isVideo && <span className="max-w-[260px] bg-black/80 px-1.5 py-0.5 text-right tracking-normal text-[#ffb3b3]">{procError}</span>}
    </span>
  );

  const stale = pb.state === "ready" && pb.seg.key !== paramsKey;

  // 재생 중에 설정이 바뀌면 0.6초 뒤 지금 구간을 새 설정으로 다시 만든다
  useEffect(() => {
    if (!stale) return;
    const id = setTimeout(() => refreshPlayback(), 600);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stale, paramsKey]);

  // ------------------------------------------------------------ keyboard: ←/→ frame, SPACE play/pause
  const onKey = (e: KeyboardEvent) => {
    const el = e.target as HTMLElement | null;
    const inDialogOrText = el?.closest?.("textarea, select, [contenteditable=true], [role=combobox], [role=listbox], [role=dialog]");
    const inTextInput = el instanceof HTMLInputElement && el.type !== "range";
    if (inDialogOrText || inTextInput) return;
    if (e.key === " ") {
      e.preventDefault(); // no page scroll, no button "click"
      if (e.repeat) return;
      if (pb.state === "rendering") stopPlayback(); // cancel the pending auto-play
      else if (pb.state === "ready") togglePlay();
      else startPlayback();
      return;
    }
    if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !isVideo && el instanceof HTMLInputElement === false) {
      e.preventDefault();
      step((e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 10 : 1));
    }
  };
  const onKeyRef = useRef(onKey);
  useEffect(() => {
    onKeyRef.current = onKey;
  });
  useEffect(() => {
    const h = (e: KeyboardEvent) => onKeyRef.current(e);
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  return (
    <section ref={rootRef} className={cn("flex min-w-0 flex-col bg-black", full && "h-screen")}>
      <Head
        ch="CH-02"
        title="MONITOR"
        right={
          <>
            <span className="hidden sm:inline">
              {info.width}×{info.height}
            </span>
            <span>{Number(ofps.toFixed(3))} FPS</span>
            <span className={isVideo ? "text-eva" : ""}>{isVideo ? "PLAYBACK" : "STILL"}</span>
          </>
        }
      />

      {/* toolbar */}
      <div className="flex min-w-0 flex-wrap items-center gap-2 border-b border-rule px-3 py-2">
        <Seg<Mode>
          value={mode}
          onChange={setMode}
          options={[
            { value: "split", label: "SPLIT" },
            { value: "compare", label: "COMPARE" },
          ]}
          className="w-[170px]"
        />
        <Seg
          value={String(zoom)}
          onChange={(v) => setZoomLevel(Number(v))}
          options={[1, 2, 4].map((z) => ({ value: String(z), label: `${z}x` }))}
          className="w-[120px]"
        />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {pb.state === "ready" ? (
            <>
              <Btn tone="accent" onClick={togglePlay}>
                {playing ? "❚❚ PAUSE" : "▶ PLAY"}
              </Btn>
              <Btn onClick={stopPlayback}>■ STILLS</Btn>
            </>
          ) : pb.state === "rendering" ? (
            <Btn onClick={stopPlayback}>CANCEL · {Math.round(pb.progress * 100)}%</Btn>
          ) : (
            <Btn tone="accent" onClick={() => startPlayback()} title="지금 위치부터 끝까지 이어서 재생 (SPACE)">
              ▶ PLAY
            </Btn>
          )}
          <Btn onClick={toggleFull} title="전체화면">
            {full ? "EXIT FULL" : "⛶ FULL"}
          </Btn>
        </div>
      </div>
      {pb.state === "rendering" && <Bar value={Math.max(0.03, pb.progress)} />}
      {pb.state === "error" && (
        <div className="border-b border-rule px-3 py-1.5 text-xs text-[#ffb3b3]">
          {pb.error}{" "}
          <button className="ml-2 text-muted-foreground underline" onClick={() => setPb({ state: "idle" })}>
            닫기
          </button>
        </div>
      )}
      {(stale || updating) && <div className="border-b border-rule px-3 py-1.5 text-[11px] text-eva">새 설정으로 다시 렌더링 중… 끝나면 자동으로 바뀝니다.</div>}

      {/* stage */}
      <div
        ref={stageRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
        onDoubleClick={() => zoom > 1 && setPan({ x: 0, y: 0 })}
        style={full ? undefined : { aspectRatio: `${(mode === "split" ? 2 : 1) * info.width} / ${info.height}` }}
        className={cn(
          "checker relative min-h-0 touch-none overflow-hidden select-none",
          full ? "flex-1" : "max-h-[64vh] min-h-[220px] w-full",
          mode === "split" ? "grid grid-cols-2 gap-px bg-rule" : "",
          zoom > 1 ? "cursor-grab active:cursor-grabbing" : mode === "compare" ? "cursor-ew-resize" : "",
        )}
      >
        {mode === "split" ? (
          <>
            <div className="relative overflow-hidden bg-black">
              {tag("ORIGINAL", "left")}
              {media("orig")}
            </div>
            <div className="relative overflow-hidden bg-black">
              {tag("PROCESSED", "right")}
              {media("proc")}
              {status}
            </div>
          </>
        ) : (
          <>
            <div className="absolute inset-0 overflow-hidden bg-black">{media("orig")}</div>
            <div className="absolute inset-0 overflow-hidden" style={{ clipPath: `inset(0 0 0 ${wipe}%)` }}>
              {media("proc")}
            </div>
            {tag("ORIGINAL", "left")}
            {tag("PROCESSED", "right")}
            <div className="absolute inset-y-0 z-20 w-px bg-eva" style={{ left: `${wipe}%` }}>
              <span
                data-handle="wipe"
                className="absolute top-1/2 left-1/2 flex h-10 w-4 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize items-center justify-center border border-eva bg-black text-[9px] text-eva"
              >
                ⇔
              </span>
            </div>
            {status}
          </>
        )}
        {zoom > 1 && (
          <span className="pointer-events-none absolute bottom-2 left-2 z-10 bg-black/70 px-1.5 py-0.5 text-[10px] tracking-[0.14em] text-muted-foreground">
            ZOOM {zoom}x · DRAG TO PAN · DBL-CLICK CENTER
          </span>
        )}
      </div>

      {/* transport */}
      <div className="border-t border-rule px-3 pt-3 pb-2">
        {isVideo && seg ? (
          <>
            <Slider value={[Math.min(maxT, seg.start + pbTime)]} min={0} max={maxT || frameDur} step={frameDur} onValueChange={(v) => seekPlayback(Array.isArray(v) ? v[0] : v)} aria-label="타임라인" />
            <div className="tick-bg mt-1 h-2" />
            <div className="mt-2 flex min-w-0 flex-wrap items-center gap-3 text-[11px] tracking-[0.12em] text-muted-foreground">
              <span className={playing ? "text-eva" : ""}>{playing ? "PLAYING" : "PAUSED"}</span>
              <span className="text-sm text-foreground tabular-nums">{timecode(seg.start + pbTime, ofps)}</span>
              <span className="tabular-nums">/ {timecode(info.duration, ofps)}</span>
              <span className="ml-auto">SPACE: PLAY/PAUSE · 원본 소리 재생 · 보정본 음소거</span>
            </div>
          </>
        ) : (
          <>
            <Slider value={[t]} min={0} max={maxT || frameDur} step={frameDur} onValueChange={(v) => setT(Array.isArray(v) ? v[0] : v)} aria-label="타임라인" />
            <div className="tick-bg mt-1 h-2" />
            <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2">
              <Btn onClick={() => step(-1)} title="이전 프레임 (←)">
                ◀ 1F
              </Btn>
              <Btn onClick={() => step(1)} title="다음 프레임 (→)">
                1F ▶
              </Btn>
              <span className="ml-2 text-sm tabular-nums">{timecode(snapT, ofps)}</span>
              <span className="text-[11px] tracking-[0.12em] text-muted-foreground tabular-nums">
                F {String(frame).padStart(5, "0")} / {String(totalFrames - 1).padStart(5, "0")}
              </span>
              <span className="ml-auto text-[10px] tracking-[0.12em] text-muted-foreground">SPACE: PLAY/PAUSE · ←/→: FRAME · SHIFT ×10</span>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function clampPan(p: { x: number; y: number }, z: number) {
  const m = ((z - 1) / (2 * z)) * 100;
  const c = (v: number) => Math.max(-m, Math.min(m, v));
  return { x: c(p.x), y: c(p.y) };
}
