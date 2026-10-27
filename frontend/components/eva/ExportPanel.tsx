"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import type { ExportSettings } from "@/lib/api";
import { FPS_OPTIONS } from "./Controls";
import { Btn, ErrorLine, Field, Head, Seg } from "./ui";

interface Props {
  settings: ExportSettings;
  onChange: (s: ExportSettings) => void;
  clipCount: number;
  hasActive: boolean;
  encoders: Record<string, boolean>;
  onExport: (all: boolean) => Promise<void>;
}

export function ExportPanel({ settings, onChange, clipCount, hasActive, encoders, onExport }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof ExportSettings>(k: K, v: ExportSettings[K]) => onChange({ ...settings, [k]: v });
  const hw = settings.codec === "h264" ? encoders.h264_videotoolbox : encoders.hevc_videotoolbox;

  const submit = async (all: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await onExport(all);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="min-w-0">
      <Head ch="CH-04" title="EXPORT" right={<span>{hw ? "HW ENCODE" : "SW ENCODE"}</span>} />
      <div className="grid min-w-0 gap-3 p-3">
        <Field label="RESOLUTION">
          <Seg
            value={settings.resolution}
            onChange={(v) => set("resolution", v)}
            options={[
              { value: "original", label: "ORIGINAL" },
              { value: "1080p", label: "1080P" },
              { value: "4k", label: "4K" },
            ]}
          />
        </Field>
        <Field label="UPSCALE (원본보다 크게 내보낼 때)">
          <Seg
            value={settings.upscale}
            onChange={(v) => set("upscale", v)}
            options={[
              { value: "standard", label: "STANDARD" },
              { value: "sharp", label: "SHARP" },
              { value: "ai", label: "AI (APPLE)" },
            ]}
          />
          <p className="mt-1 text-[10px] text-muted-foreground">
            {settings.upscale === "ai"
              ? "애플 초해상도로 4배 복원합니다. 1/4 크기에서 보정한 뒤 키우며, 4K 기준 프레임당 약 0.2~0.3초 걸립니다."
              : settings.upscale === "sharp"
                ? "고품질 확대 + 대비 적응 선명화. 빠르고 질감이 바뀌지 않습니다."
                : "고품질 확대만 합니다."}
          </p>
        </Field>
        <Field label="FRAME RATE (= MOTION)">
          <Seg value={settings.fps} onChange={(v) => set("fps", v)} options={FPS_OPTIONS} />
        </Field>
        <Field label="CODEC">
          <Seg
            value={settings.codec}
            onChange={(v) => set("codec", v)}
            options={[
              { value: "h264", label: "H.264" },
              { value: "h265", label: "H.265" },
            ]}
          />
        </Field>
        <Field label="QUALITY">
          <Seg
            value={settings.quality}
            onChange={(v) => set("quality", v)}
            options={[
              { value: "standard", label: "STANDARD" },
              { value: "high", label: "HIGH" },
              { value: "maximum", label: "MAXIMUM" },
            ]}
          />
        </Field>
        <Field label="OUTPUT FOLDER" >
          <Input value={settings.output_dir} onChange={(e) => set("output_dir", e.target.value)} spellCheck={false} className="h-8 rounded-none border-rule-2 text-[12px]" />
        </Field>
        <div className="flex min-w-0 flex-wrap gap-2">
          <Btn tone="accent" className="h-9 flex-1" disabled={!hasActive || busy} onClick={() => submit(false)}>
            EXPORT THIS CLIP
          </Btn>
          <Btn className="h-9 flex-1" disabled={!clipCount || busy} onClick={() => submit(true)}>
            BATCH EXPORT ALL ({clipCount})
          </Btn>
        </div>
        <div>
          <ErrorLine message={error} onClose={() => setError(null)} />
          <p className="text-[10px] text-muted-foreground">현재 보정 설정으로 내보냅니다. 파일명은 원본명_EVA95.mp4이고, 원본 오디오는 AAC로 함께 담깁니다.</p>
        </div>
      </div>
    </section>
  );
}
