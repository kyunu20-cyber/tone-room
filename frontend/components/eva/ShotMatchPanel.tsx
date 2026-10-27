"use client";

import { useEffect, useState } from "react";
import { type Analysis, api, type ParamDef, type Params } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ParamRow } from "./Controls";
import { Head } from "./ui";

const TARGETS = ["target_exposure", "target_contrast", "target_saturation"] as const;

export function ShotMatchPanel({
  clipId,
  params,
  defs,
  base,
  setParam,
}: {
  clipId: string | null;
  params: Params;
  defs: ParamDef[];
  base: Params;
  setParam: (k: string, v: number | boolean) => void;
}) {
  const on = Boolean(params.shot_matching);
  const strengthDef = defs.find((d) => d.key === "shot_match_strength");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [doneKey, setDoneKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Correction depends only on the clip and the preset's target stats.
  const targetKey = JSON.stringify(TARGETS.map((k) => params[k]));
  const reqKey = `${clipId}|${targetKey}`;
  const loading = !!clipId && doneKey !== reqKey;
  useEffect(() => {
    if (!clipId) return;
    let alive = true;
    const timer = setTimeout(() => {
      const targets = Object.fromEntries(TARGETS.map((k, i) => [k, JSON.parse(targetKey)[i]]));
      api
        .analyze(clipId, targets)
        .then((a) => alive && (setAnalysis(a), setError(null)))
        .catch((e: Error) => alive && setError(e.message))
        .finally(() => alive && setDoneKey(reqKey));
    }, 300);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [clipId, targetKey, reqKey]);

  const c = analysis?.correction;
  const strength = Number(params.shot_match_strength ?? 0);

  return (
    <div className="border-b border-rule">
      <Head ch="SM" title="AUTO SHOT MATCHING" right={loading ? <span className="text-eva">ANALYZING…</span> : null} />
      <div className="space-y-3 p-3">
        <button
          type="button"
          onClick={() => setParam("shot_matching", !on)}
          aria-pressed={on}
          className={cn(
            "flex h-10 w-full items-center justify-between border px-3 text-[12px] tracking-[0.16em] outline-none focus-visible:ring-1 focus-visible:ring-eva",
            on ? "border-eva text-eva" : "border-rule-2 text-muted-foreground hover:border-white",
          )}
        >
          <span>AUTO SHOT MATCHING</span>
          <span className={cn("px-2 py-0.5", on ? "bg-eva text-black" : "border border-rule-2")}>{on ? "ON" : "OFF"}</span>
        </button>
        {strengthDef && <ParamRow def={strengthDef} value={params.shot_match_strength} base={base.shot_match_strength} onChange={setParam} disabled={!on} />}

        <div className={cn("border border-rule text-[11px]", !on && "opacity-45")}>
          <div className="grid grid-cols-2 divide-x divide-rule border-b border-rule">
            <Stat label="EXPOSURE" value={c ? `${c.exposure_ev >= 0 ? "+" : ""}${c.exposure_ev.toFixed(2)} EV` : "—"} />
            <Stat label="CONTRAST" value={c ? `×${c.contrast.toFixed(2)}` : "—"} />
          </div>
          <div className="grid grid-cols-2 divide-x divide-rule border-b border-rule">
            <Stat label="SATURATION" value={c ? `×${c.saturation.toFixed(2)}` : "—"} />
            <Stat label="STRENGTH" value={`${Math.round(strength * 100)}%`} />
          </div>
          <div className="grid grid-cols-3 divide-x divide-rule">
            {["R", "G", "B"].map((ch, i) => (
              <Stat key={ch} label={`WB ${ch}`} value={c ? c.wb[i].toFixed(3) : "—"} color={["#ff7a7a", "#7aff9c", "#7ab8ff"][i]} />
            ))}
          </div>
        </div>
        {error && <p className="text-xs break-words text-[#ffb3b3]">{error}</p>}
        {c && (
          <ul className="space-y-0.5 text-[11px] text-muted-foreground">
            {c.notes.length ? c.notes.map((n) => <li key={n}>· {n}</li>) : <li>· 보호 제한 없이 목표값에 맞췄습니다.</li>}
          </ul>
        )}
        <p className="text-[10px] leading-relaxed text-muted-foreground">클립 전체에서 고른 대표 프레임을 분석해 클립마다 고정 보정값 하나를 씁니다. 표시값은 강도 적용 전 기준입니다.</p>
      </div>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="min-w-0 px-2 py-1.5">
      <div className="text-[9px] tracking-[0.16em] text-muted-foreground" style={color ? { color } : undefined}>
        {label}
      </div>
      <div className="truncate tabular-nums">{value}</div>
    </div>
  );
}
