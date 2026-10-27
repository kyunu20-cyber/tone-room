"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

type Tag = "h1" | "h2" | "h3" | "p" | "ul" | "ol" | "strong" | "blockquote" | "pre" | "th" | "td";

/** Styled element that drops react-markdown's `node` prop so it never reaches the DOM. */
function styled(T: Tag, className: string) {
  function Styled({ node, ...props }: { node?: unknown } & React.HTMLAttributes<HTMLElement>) {
    void node;
    return <T className={className} {...props} />;
  }
  return Styled;
}

const md: Components = {
  h1: styled("h1", "mt-2 mb-4 text-xl font-bold tracking-[0.06em] text-eva"),
  h2: styled("h2", "mt-8 mb-3 border-b border-rule pb-1.5 text-base font-bold text-eva"),
  h3: styled("h3", "mt-5 mb-2 text-sm font-bold text-white"),
  p: styled("p", "my-2.5 leading-relaxed"),
  ul: styled("ul", "my-2.5 list-disc space-y-1 pl-5"),
  ol: styled("ol", "my-2.5 list-decimal space-y-1 pl-5"),
  strong: styled("strong", "font-bold text-white"),
  blockquote: styled("blockquote", "my-3 border-l-2 border-eva pl-3 text-muted-foreground"),
  pre: styled("pre", "my-3 overflow-x-auto border border-rule-2 bg-[#0a0a0a] p-3 font-mono text-[12px]"),
  th: styled("th", "border border-[#333] bg-[#0d0d0d] px-2 py-1.5 text-left font-medium tracking-[0.06em]"),
  td: styled("td", "border border-[#333] px-2 py-1.5 align-top"),
  hr: () => <hr className="my-6 border-rule" />,
  a: ({ node, ...p }) => {
    void node;
    return <a className="text-eva underline underline-offset-4" target="_blank" rel="noreferrer" {...p} />;
  },
  code: ({ node, className, ...p }) => {
    void node;
    return <code className={className ? `${className} font-mono` : "border border-rule-2 bg-[#0d0d0d] px-1 font-mono text-[0.92em]"} {...p} />;
  },
  table: ({ node, ...p }) => {
    void node;
    return (
      <div className="my-3 overflow-x-auto">
        <table className="w-full border-collapse text-[12.5px]" {...p} />
      </div>
    );
  },
};

export function ManualDrawer({ markdown, open, onClose }: { markdown: string; open: boolean; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[60] flex justify-end" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <button type="button" aria-label="설명서 닫기" className="absolute inset-0 cursor-default bg-black/70" onClick={onClose} />
          <motion.aside
            role="dialog"
            aria-modal="true"
            aria-label="사용 설명서"
            initial={{ x: 40 }}
            animate={{ x: 0 }}
            exit={{ x: 40 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="relative flex h-full w-full max-w-[760px] flex-col border-l border-rule-2 bg-black"
          >
            <div className="flex h-10 shrink-0 items-center gap-2 border-b border-rule px-4 text-[11px] tracking-[0.14em]">
              <span className="text-muted-foreground">[ DOC ]</span>
              <span>MANUAL</span>
              <span className="ml-auto text-muted-foreground">ESC</span>
              <button ref={closeRef} type="button" onClick={onClose} className="border border-rule-2 px-2 py-0.5 outline-none hover:border-white focus-visible:border-eva" aria-label="닫기">
                ✕
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 text-[13px] text-[#ddd] md:px-8">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={md}>
                {markdown}
              </ReactMarkdown>
            </div>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
