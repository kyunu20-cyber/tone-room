"use client";

import { useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { ParamDef, Params, Preset } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ShotMatchPanel } from "./ShotMatchPanel";
import { Btn, ErrorLine, Head, Seg } from "./ui";

const GROUPS = ["MASTER", "IPHONE LOOK", "COLOR", "TEXTURE", "ANALOG", "MOTION", "SHOT MATCHING", "MISC"];
const IN_SHOT_PANEL = new Set(["shot_matching", "shot_match_strength"]);
export const FPS_OPTIONS = [
  { value: "original", label: "ORIGINAL" },
  { value: "23.976", label: "23.976" },
  { value: "24", label: "24" },
  { value: "30", label: "30" },
];

const decimals = (step: number) => (step >= 1 ? 0 : step >= 0.1 ? 1 : 2);

/** One schema-driven control. Double-click the label to restore the preset value. */
export function ParamRow({
  def,
  value,
  base,
  onChange,
  disabled,
  label,
}: {
  def: ParamDef;
  value: number | boolean | undefined;
  base: number | boolean | undefined;
  onChange: (k: string, v: number | boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  const v = value ?? def.neutral;
  const changed = base !== undefined && v !== base;
  const name = (
    <span
      className={cn("min-w-0 truncate text-[11px] tracking-[0.1em] uppercase", def.hint && "cursor-help decoration-dotted underline-offset-4 hover:underline")}
      onDoubleClick={() => base !== undefined && onChange(def.key, base)}
    >
      {label ?? def.label}
    </span>
  );
  const labelEl = def.hint ? (
    <Tooltip>
      <TooltipTrigger render={name} />
      <TooltipContent side="left" className="rounded-none border border-rule-2 bg-black text-white">
        {def.hint}
      </TooltipContent>
    </Tooltip>
  ) : (
    name
  );

  if (def.kind === "bool")
    return (
      <div className={cn("flex min-w-0 items-center gap-2 py-1", disabled && "opacity-45")}>
        <span className={cn("size-1 shrink-0", changed ? "bg-eva" : "bg-transparent")} />
        {labelEl}
        <Switch className="ml-auto data-checked:bg-eva" checked={Boolean(v)} onCheckedChange={(c) => onChange(def.key, c)} disabled={disabled} />
      </div>
    );

  const num = Number(v);
  return (
    <div className={cn("min-w-0 py-1", disabled && "pointer-events-none opacity-45")}>
      <div className="flex min-w-0 items-center gap-2">
        <span className={cn("size-1 shrink-0", changed ? "bg-eva" : "bg-transparent")} />
        {labelEl}
        <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">{num.toFixed(decimals(def.step))}</span>
      </div>
      <Slider
        className="mt-1.5 pl-3"
        value={[num]}
        min={def.min}
        max={def.max}
        step={def.step}
        disabled={disabled}
        onValueChange={(x) => onChange(def.key, Array.isArray(x) ? x[0] : x)}
        aria-label={def.label}
      />
    </div>
  );
}

interface Props {
  defs: ParamDef[];
  presets: Preset[];
  presetId: string;
  params: Params;
  clipId: string | null;
  fps: string;
  onFps: (v: string) => void;
  onPreset: (id: string) => void;
  setParam: (k: string, v: number | boolean) => void;
  onReset: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onApplyAll?: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onSaveAs: (name: string) => Promise<void>;
  onDelete: () => Promise<void>;
}

export function Controls({ defs, presets, presetId, params, clipId, fps, onFps, onPreset, setParam, onReset, onUndo, onRedo, onApplyAll, canUndo, canRedo, onSaveAs, onDelete }: Props) {
  const [appliedAll, setAppliedAll] = useState(false);
  const preset = presets.find((p) => p.id === presetId);
  const base: Params = { ...Object.fromEntries(defs.map((d) => [d.key, d.neutral])), ...preset?.params };
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({ MISC: true });
  const [saveOpen, setSaveOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = defs.some((d) => (params[d.key] ?? d.neutral) !== base[d.key]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex min-h-0 min-w-0 flex-col">
      <Head ch="CH-03" title="GRADE CONTROLS" right={dirty ? <span className="text-eva">MODIFIED</span> : <span>PRESET</span>} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* preset */}
        <div className="space-y-2 border-b border-rule p-3">
          <Select
            value={presetId}
            items={presets.map((p) => ({ value: p.id, label: p.name }))}
            onValueChange={(v) => v && onPreset(String(v))}
          >
            <SelectTrigger className="h-8 w-full rounded-none border-rule-2 text-[12px] tracking-[0.08em]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="rounded-none border border-rule-2 bg-black">
              {presets.map((p) => (
                <SelectItem key={p.id} value={p.id} className="rounded-none text-[12px]">
                  {p.name}
                  {!p.builtin && <span className="text-[10px] text-muted-foreground">USER</span>}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {preset?.description && <p className="text-[11px] leading-relaxed text-muted-foreground">{preset.description}</p>}
          <div className="flex gap-2">
            <Btn className="flex-1" onClick={onUndo} disabled={!canUndo} title="이전 설정으로 되돌리기 (⌘Z)">
              ↶ UNDO
            </Btn>
            <Btn className="flex-1" onClick={onRedo} disabled={!canRedo} title="되돌린 것을 다시 적용 (⇧⌘Z)">
              REDO ↷
            </Btn>
          </div>
          <p className="text-[11px] leading-relaxed text-muted-foreground">설정은 클립마다 따로 저장됩니다. RESET·UNDO는 지금 클립에만 적용됩니다.</p>
          {onApplyAll && (
            <Btn
              onClick={() => {
                onApplyAll();
                setAppliedAll(true);
                setTimeout(() => setAppliedAll(false), 1500);
              }}
              title="지금 클립의 설정을 다른 모든 클립에 똑같이 적용"
            >
              {appliedAll ? "APPLIED ✓" : "APPLY TO ALL CLIPS"}
            </Btn>
          )}
          <div className="flex gap-2">
            <Btn className="flex-1" onClick={onReset} disabled={!dirty} title="이 프리셋의 원래 값으로 한 번에 되돌리기">
              RESET
            </Btn>
            <Btn
              className="flex-1"
              onClick={() => {
                setName(preset && !preset.builtin ? preset.name : "");
                setSaveOpen(true);
              }}
            >
              SAVE AS
            </Btn>
            <Btn className="flex-1" tone="danger" disabled={!preset || preset.builtin || busy} onClick={() => run(onDelete)} title={preset?.builtin ? "내장 프리셋은 지울 수 없습니다" : undefined}>
              DELETE
            </Btn>
          </div>
          <ErrorLine message={error} onClose={() => setError(null)} />
        </div>

        <ShotMatchPanel clipId={clipId} params={params} defs={defs} base={base} setParam={setParam} />

        {GROUPS.map((g, gi) => {
          const items = defs.filter((d) => d.group === g && !IN_SHOT_PANEL.has(d.key));
          if (!items.length && g !== "MOTION") return null;
          const closed = collapsed[g];
          return (
            <div key={g} className="border-b border-rule">
              <button
                type="button"
                onClick={() => setCollapsed((c) => ({ ...c, [g]: !c[g] }))}
                className="flex h-8 w-full items-center gap-2 px-3 text-[11px] tracking-[0.14em] outline-none hover:bg-[#0b0b0b] focus-visible:bg-[#0b0b0b]"
              >
                <span className="text-muted-foreground">[ {String(gi + 1).padStart(2, "0")} ]</span>
                <span>{g === "SHOT MATCHING" ? "SHOT MATCH TARGETS" : g}</span>
                <span className="ml-auto text-muted-foreground">{closed ? "+" : "−"}</span>
              </button>
              {!closed && (
                <div className="space-y-1.5 px-3 pb-3">
                  {g === "MOTION" && (
                    <div className="space-y-1 py-1">
                      <span className="text-[11px] tracking-[0.1em]">FRAME RATE</span>
                      <Seg value={fps} onChange={onFps} options={FPS_OPTIONS} />
                    </div>
                  )}
                  {items.map((d) => (
                    <ParamRow
                      key={d.key}
                      def={d}
                      value={params[d.key]}
                      base={base[d.key]}
                      onChange={setParam}
                      label={d.key === "cadence_12fps" ? "12 FPS ANIMATION SIMULATION" : undefined}
                      disabled={g === "SHOT MATCHING" && !params.shot_matching}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
        <p className="p-3 text-[10px] leading-relaxed text-muted-foreground">라벨을 더블클릭하면 해당 값만 프리셋 값으로 돌아갑니다. 초록 점은 프리셋에서 바뀐 값입니다.</p>
      </div>

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent className="rounded-none border border-rule-2 bg-black ring-0">
          <DialogHeader>
            <DialogTitle className="text-[13px] tracking-[0.14em]">SAVE PRESET</DialogTitle>
            <DialogDescription className="text-xs">현재 설정을 사용자 프리셋으로 저장합니다. 같은 이름이면 덮어씁니다.</DialogDescription>
          </DialogHeader>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (!name.trim()) return;
              if (await run(() => onSaveAs(name.trim()))) setSaveOpen(false);
            }}
            className="space-y-3"
          >
            <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="프리셋 이름" className="rounded-none border-rule-2" maxLength={60} />
            <ErrorLine message={error} />
            <DialogFooter className="border-none bg-transparent">
              <Btn onClick={() => setSaveOpen(false)}>CANCEL</Btn>
              <button type="submit" disabled={!name.trim() || busy} className="h-7 border border-eva bg-eva px-3 text-[11px] tracking-[0.12em] text-black disabled:opacity-40">
                SAVE
              </button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
