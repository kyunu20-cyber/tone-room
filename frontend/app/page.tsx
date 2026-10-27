import { readFile } from "node:fs/promises";
import path from "node:path";
import { App } from "@/components/eva/App";

// The manual is read from the repo file at build time, so editing ../사용설명서.md
// and rebuilding updates the in-app manual (no copy of the text lives in the code).
async function getManual(): Promise<string> {
  "use cache";
  return readFile(path.join(process.cwd(), "..", "사용설명서.md"), "utf-8").catch(
    () => "# 사용 설명서\n\n설명서 파일(사용설명서.md)을 찾을 수 없습니다.",
  );
}

export default async function Page() {
  return <App manual={await getManual()} />;
}
