"use client";

import { useCallback, useRef } from "react";
import { ACCEPT } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface Upload {
  key: string;
  name: string;
  progress: number;
  status: "uploading" | "probing" | "error";
  error?: string;
}

/** Hidden multi-file input; returns the element to render and an open() trigger. */
export function useFilePicker(onFiles: (f: File[]) => void) {
  const ref = useRef<HTMLInputElement>(null);
  const open = useCallback(() => ref.current?.click(), []);
  const input = (
    <input
      ref={ref}
      type="file"
      multiple
      accept={ACCEPT.join(",")}
      className="hidden"
      onChange={(e) => {
        onFiles(Array.from(e.target.files ?? []));
        e.target.value = "";
      }}
    />
  );
  return { input, open };
}

export function Dropzone({ onFiles, dragging }: { onFiles: (f: File[]) => void; dragging: boolean }) {
  const { input, open } = useFilePicker(onFiles);
  return (
    <>
      {input}
      <button
        type="button"
        onClick={open}
        className={cn(
          "group relative flex min-h-[420px] w-full flex-col items-center justify-center gap-5 border border-dashed transition-colors outline-none focus-visible:border-eva",
          dragging ? "border-eva bg-eva/5" : "border-rule-2 hover:border-white",
        )}
      >
        <Corners active={dragging} />
        <span className={cn("text-2xl tracking-[0.3em] md:text-4xl", dragging && "text-eva")}>[ DROP VIDEO HERE ]</span>
        <span className="text-[11px] tracking-[0.2em] text-muted-foreground">MP4 · MOV · MKV · WEBM — MULTIPLE FILES OK</span>
        <span className="text-xs text-muted-foreground">영상 파일을 끌어다 놓거나 클릭해서 고르세요.</span>
      </button>
    </>
  );
}

function Corners({ active }: { active: boolean }) {
  const c = cn("absolute size-4 border-white", active && "border-eva");
  return (
    <>
      <span className={cn(c, "top-3 left-3 border-t border-l")} />
      <span className={cn(c, "top-3 right-3 border-t border-r")} />
      <span className={cn(c, "bottom-3 left-3 border-b border-l")} />
      <span className={cn(c, "right-3 bottom-3 border-r border-b")} />
    </>
  );
}

export function UploadList({ uploads, onDismiss }: { uploads: Upload[]; onDismiss: (key: string) => void }) {
  if (!uploads.length) return null;
  return (
    <ul className="divide-y divide-rule border-t border-rule">
      {uploads.map((u) => (
        <li key={u.key} className="space-y-1 px-3 py-2 text-[11px]">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate">{u.name}</span>
            <span className={cn("ml-auto shrink-0 tracking-[0.12em]", u.status === "error" ? "text-destructive" : "text-eva")}>
              {u.status === "uploading" ? `UPLOAD ${Math.round(u.progress * 100)}%` : u.status === "probing" ? "PROBING…" : "FAILED"}
            </span>
            {u.status === "error" && (
              <button className="shrink-0 text-muted-foreground hover:text-white" onClick={() => onDismiss(u.key)} aria-label="닫기">
                ×
              </button>
            )}
          </div>
          {u.status === "error" ? (
            <p className="break-words text-[#ffb3b3]">{u.error}</p>
          ) : (
            <div className="h-[3px] bg-[#1a1a1a]">
              <div className="h-full bg-eva transition-[width]" style={{ width: `${u.progress * 100}%` }} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
