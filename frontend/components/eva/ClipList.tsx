"use client";

import { AnimatePresence, motion } from "framer-motion";
import { type Clip, duration } from "@/lib/api";
import { cn } from "@/lib/utils";
import { type Upload, UploadList, useFilePicker } from "./Dropzone";
import { Btn, Head } from "./ui";

interface Props {
  clips: Clip[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
  onFiles: (f: File[]) => void;
  uploads: Upload[];
  onDismissUpload: (key: string) => void;
}

export function ClipList({ clips, activeId, onSelect, onRemove, onFiles, uploads, onDismissUpload }: Props) {
  const picker = useFilePicker(onFiles);
  return (
    <section className="flex min-h-0 min-w-0 flex-col border-rule">
      <Head
        ch="CH-01"
        title="CLIP QUEUE"
        right={<span>{String(clips.length).padStart(2, "0")}</span>}
      />
      <ul className="min-h-0 flex-1 overflow-y-auto">
        <AnimatePresence initial={false}>
          {clips.map((c, i) => {
            const active = c.id === activeId;
            const { info } = c;
            return (
              <motion.li
                key={c.id}
                layout
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className={cn("group relative border-b border-rule", active && "bg-[#0b0b0b]")}
              >
                {active && <span className="absolute inset-y-0 left-0 w-[2px] bg-eva" />}
                <button type="button" onClick={() => onSelect(c.id)} className="block w-full min-w-0 px-3 py-2.5 text-left outline-none focus-visible:bg-[#111]">
                  <div className="flex min-w-0 items-center gap-2 text-[10px] tracking-[0.14em] text-muted-foreground">
                    <span>#{String(i + 1).padStart(2, "0")}</span>
                    {info.hdr && <span className="border border-[#ffcc66] px-1 text-[#ffcc66]">HDR {info.hdr.toUpperCase()}</span>}
                    {info.is_vfr && <span className="border border-rule-2 px-1">VFR</span>}
                    <span className="ml-auto">{info.has_audio ? "AUDIO" : "NO AUDIO"}</span>
                  </div>
                  <div className={cn("mt-1 truncate text-[13px]", active && "text-white")} title={c.name}>
                    {c.name}
                  </div>
                  <div className="mt-1 flex gap-3 text-[10px] tracking-[0.1em] text-muted-foreground">
                    <span>
                      {info.width}×{info.height}
                    </span>
                    <span>{Number(info.fps.toFixed(3))} FPS</span>
                    <span>{duration(info.duration)}</span>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => onRemove(c.id)}
                  className="absolute right-2 bottom-2 hidden bg-black px-1 text-[10px] tracking-[0.12em] text-muted-foreground group-hover:block hover:text-destructive focus-visible:block"
                  aria-label={`${c.name} 제거`}
                >
                  [ DEL ]
                </button>
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ul>
      <UploadList uploads={uploads} onDismiss={onDismissUpload} />
      <div className="border-t border-rule p-3">
        {picker.input}
        <Btn className="w-full" onClick={picker.open}>
          + ADD CLIPS
        </Btn>
        <p className="mt-2 text-[10px] text-muted-foreground">화면 어디에든 파일을 끌어다 놓아도 추가됩니다.</p>
      </div>
    </section>
  );
}
