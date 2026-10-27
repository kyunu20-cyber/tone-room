"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { api, type Job } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Bar, Btn, ErrorLine, Head } from "./ui";

const STATUS_COLOR: Record<Job["status"], string> = {
  queued: "text-muted-foreground",
  running: "text-eva",
  done: "text-white",
  failed: "text-destructive",
  cancelled: "text-muted-foreground",
};

const eta = (s: number | null) => (s == null ? "--:--" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`);

export function JobQueue({ jobs, refresh }: { jobs: Job[]; refresh: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const act = (fn: () => Promise<unknown>) => async () => {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    refresh();
  };
  const active = jobs.filter((j) => j.status === "running" || j.status === "queued").length;

  return (
    <section className="flex min-h-0 min-w-0 flex-col">
      <Head ch="CH-05" title="RENDER QUEUE" right={<span className={active ? "text-eva" : ""}>{active ? `ACTIVE ${active}` : "IDLE"}</span>} />
      <div className="px-3 pt-2">
        <ErrorLine message={error} onClose={() => setError(null)} />
      </div>
      {!jobs.length ? (
        <p className="p-3 text-xs text-muted-foreground">내보내기 작업이 없습니다.</p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto">
          <AnimatePresence initial={false}>
            {jobs.map((j) => (
              <motion.li key={j.id} layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-1.5 border-b border-rule px-3 py-2.5">
                <div className="flex min-w-0 items-center gap-2 text-[11px]">
                  <span className={cn("w-[74px] shrink-0 tracking-[0.14em]", STATUS_COLOR[j.status])}>{j.status.toUpperCase()}</span>
                  <span className="min-w-0 truncate" title={j.name}>
                    {j.name}
                  </span>
                  <span className="ml-auto shrink-0 tabular-nums">{Math.round(j.progress * 100)}%</span>
                </div>
                <Bar value={j.progress} tone={j.status === "failed" ? "danger" : j.status === "running" || j.status === "done" ? "accent" : "muted"} />
                <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[10px] tracking-[0.1em] text-muted-foreground tabular-nums">
                  <span>
                    F {j.frames_done}/{j.frames_total || "—"}
                  </span>
                  {j.status === "running" && (
                    <>
                      <span>{j.speed_fps.toFixed(1)} FPS</span>
                      <span>ETA {eta(j.eta_s)}</span>
                    </>
                  )}
                  <span className="ml-auto flex gap-1.5">
                    {(j.status === "queued" || j.status === "running") && (
                      <Btn className="h-6 px-2" tone="danger" onClick={act(() => api.cancelJob(j.id))}>
                        CANCEL
                      </Btn>
                    )}
                    {(j.status === "failed" || j.status === "cancelled") && (
                      <Btn className="h-6 px-2" onClick={act(() => api.retryJob(j.id))}>
                        RETRY
                      </Btn>
                    )}
                    {j.status === "done" && j.output && (
                      <Btn className="h-6 px-2" tone="accent" onClick={act(() => api.reveal(j.output!))}>
                        SHOW IN FINDER
                      </Btn>
                    )}
                    {j.status !== "running" && (
                      <Btn className="h-6 px-2" tone="danger" onClick={act(() => api.removeJob(j.id))}>
                        REMOVE
                      </Btn>
                    )}
                  </span>
                </div>
                {j.output && <p className="text-[10px] break-all text-muted-foreground">→ {j.output}</p>}
                {j.error && <p className="text-xs break-words text-[#ffb3b3]">{j.error}</p>}
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </section>
  );
}
