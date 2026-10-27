// Apple VideoToolbox 초해상도(4배) 파이프 도구.
// 사용: vtsr <width> <height>   stdin: rgb24 프레임 연속, stdout: 4배 크기 rgb24 프레임 연속
// vtsr --check : 지원 여부와 모델 상태만 출력(필요하면 모델을 내려받음)
import Accelerate
import CoreVideo
import Foundation
import VideoToolbox

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(1)
}

func makeBuffer(_ w: Int, _ h: Int, _ fmt: OSType) -> CVPixelBuffer {
    var out: CVPixelBuffer?
    let attrs: [String: Any] = [kCVPixelBufferIOSurfacePropertiesKey as String: [:]]
    guard CVPixelBufferCreate(nil, w, h, fmt, attrs as CFDictionary, &out) == kCVReturnSuccess, let b = out else {
        fail("픽셀 버퍼를 만들 수 없습니다: \(w)x\(h)")
    }
    // 모든 버퍼를 같은 BT.709로 표시해서 변환 중에 밝기 곡선이 바뀌지 않게 한다
    CVBufferSetAttachment(b, kCVImageBufferColorPrimariesKey, kCVImageBufferColorPrimaries_ITU_R_709_2, .shouldPropagate)
    CVBufferSetAttachment(b, kCVImageBufferTransferFunctionKey, kCVImageBufferTransferFunction_ITU_R_709_2, .shouldPropagate)
    CVBufferSetAttachment(b, kCVImageBufferYCbCrMatrixKey, kCVImageBufferYCbCrMatrix_ITU_R_709_2, .shouldPropagate)
    return b
}

func pixelFormat(_ attrs: [String: Any]) -> OSType {
    let v = attrs[kCVPixelBufferPixelFormatTypeKey as String]
    if let a = v as? [NSNumber], let f = a.first { return f.uint32Value }
    if let n = v as? NSNumber { return n.uint32Value }
    return kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
}

func readExactly(_ n: Int, into buf: UnsafeMutableRawPointer) -> Bool {
    var got = 0
    while got < n {
        let r = read(0, buf + got, n - got)
        if r <= 0 { return false }
        got += r
    }
    return true
}

func writeAll(_ p: UnsafeRawPointer, _ n: Int) {
    var done = 0
    while done < n {
        let r = write(1, p + done, n - done)
        if r <= 0 { exit(0) }  // 받는 쪽이 닫힘
        done += r
    }
}

@available(macOS 26.0, *)
func configuration(_ w: Int, _ h: Int) async -> VTSuperResolutionScalerConfiguration {
    guard VTSuperResolutionScalerConfiguration.isSupported else { fail("이 Mac은 VideoToolbox 초해상도를 지원하지 않습니다") }
    guard let cfg = VTSuperResolutionScalerConfiguration(
        frameWidth: w, frameHeight: h, scaleFactor: 4, inputType: .video, usePrecomputedFlow: false,
        qualityPrioritization: .normal, revision: VTSuperResolutionScalerConfiguration.defaultRevision)
    else { fail("이 크기는 초해상도를 쓸 수 없습니다: \(w)x\(h)") }
    if cfg.configurationModelStatus != .ready {
        do {
            try await withCheckedThrowingContinuation { (c: CheckedContinuation<Void, Error>) in
                cfg.downloadConfigurationModel { e in if let e { c.resume(throwing: e) } else { c.resume() } }
            }
        } catch { fail("초해상도 모델을 내려받지 못했습니다: \(error)") }
    }
    return cfg
}

@available(macOS 26.0, *)
func run(_ w: Int, _ h: Int) async {
    let cfg = await configuration(w, h)
    let proc = VTFrameProcessor()
    do { try proc.startSession(configuration: cfg) } catch { fail("초해상도 세션 시작 실패: \(error)") }
    var xfer: VTPixelTransferSession?
    VTPixelTransferSessionCreate(allocator: nil, pixelTransferSessionOut: &xfer)
    guard let xfer else { fail("픽셀 변환 세션을 만들 수 없습니다") }

    let ow = w * 4, oh = h * 4
    let srcFmt = pixelFormat(cfg.sourcePixelBufferAttributes as? [String: Any] ?? [:])
    let dstFmt = pixelFormat(cfg.destinationPixelBufferAttributes as? [String: Any] ?? [:])
    let inBGRA = makeBuffer(w, h, kCVPixelFormatType_32BGRA)
    let outBGRA = makeBuffer(ow, oh, kCVPixelFormatType_32BGRA)
    let inRGB = UnsafeMutableRawPointer.allocate(byteCount: w * h * 3, alignment: 16)
    let outRGB = UnsafeMutableRawPointer.allocate(byteCount: ow * oh * 3, alignment: 16)
    // 초해상도 모델은 출력 밝기를 약 3.5% 낮춘다(평평한 회색 측정값). 그 역함수 표로 되돌린다.
    let measured: [(Double, Double)] = [(0, 0), (29.9, 32), (61.9, 64), (123.3, 128), (183.4, 192), (231.3, 240), (246.5, 255)]
    var lut = [UInt8](repeating: 255, count: 256)
    for v in 0..<256 {
        let x = Double(v)
        if let k = measured.indices.dropFirst().first(where: { measured[$0].0 >= x }) {
            let (x0, y0) = measured[k - 1], (x1, y1) = measured[k]
            lut[v] = UInt8(min(255, max(0, (y0 + (x - x0) / (x1 - x0) * (y1 - y0)).rounded())))
        }
    }
    let alphaLut = [UInt8](0...255)
    var prevIn: VTFrameProcessorFrame?, prevOut: VTFrameProcessorFrame?
    var i: Int64 = 0

    while readExactly(w * h * 3, into: inRGB) {
        // rgb24 → BGRA (vImage)
        CVPixelBufferLockBaseAddress(inBGRA, [])
        var sbuf = vImage_Buffer(data: inRGB, height: vImagePixelCount(h), width: vImagePixelCount(w), rowBytes: w * 3)
        var dbuf = vImage_Buffer(data: CVPixelBufferGetBaseAddress(inBGRA)!, height: vImagePixelCount(h),
                                 width: vImagePixelCount(w), rowBytes: CVPixelBufferGetBytesPerRow(inBGRA))
        vImageConvert_RGB888toBGRA8888(&sbuf, nil, 255, &dbuf, false, vImage_Flags(kvImageNoFlags))
        CVPixelBufferUnlockBaseAddress(inBGRA, [])

        let src = makeBuffer(w, h, srcFmt), dst = makeBuffer(ow, oh, dstFmt)
        VTPixelTransferSessionTransferImage(xfer, from: inBGRA, to: src)
        let ts = CMTime(value: i, timescale: 30)
        guard let sf = VTFrameProcessorFrame(buffer: src, presentationTimeStamp: ts),
              let df = VTFrameProcessorFrame(buffer: dst, presentationTimeStamp: ts),
              let params = VTSuperResolutionScalerParameters(
                sourceFrame: sf, previousFrame: prevIn, previousOutputFrame: prevOut, opticalFlow: nil,
                submissionMode: .sequential, destinationFrame: df)
        else { fail("초해상도 입력을 만들 수 없습니다") }
        do { try await proc.process(parameters: params) } catch { fail("초해상도 처리 실패: \(error)") }
        prevIn = sf; prevOut = df

        // 결과 → BGRA → rgb24
        VTPixelTransferSessionTransferImage(xfer, from: dst, to: outBGRA)
        CVPixelBufferLockBaseAddress(outBGRA, .readOnly)
        var obuf = vImage_Buffer(data: CVPixelBufferGetBaseAddress(outBGRA)!, height: vImagePixelCount(oh),
                                 width: vImagePixelCount(ow), rowBytes: CVPixelBufferGetBytesPerRow(outBGRA))
        var rbuf = vImage_Buffer(data: outRGB, height: vImagePixelCount(oh), width: vImagePixelCount(ow), rowBytes: ow * 3)
        vImageTableLookUp_ARGB8888(&obuf, &obuf, lut, lut, lut, alphaLut, vImage_Flags(kvImageNoFlags))  // 메모리 순서 B,G,R,A — 알파는 그대로
        vImageConvert_BGRA8888toRGB888(&obuf, &rbuf, vImage_Flags(kvImageNoFlags))
        CVPixelBufferUnlockBaseAddress(outBGRA, .readOnly)
        writeAll(outRGB, ow * oh * 3)
        i += 1
    }
    proc.endSession()
}

guard #available(macOS 26.0, *) else { fail("macOS 26 이상이 필요합니다") }
let args = CommandLine.arguments
let sem = DispatchSemaphore(value: 0)
if args.count == 2 && args[1] == "--check" {
    // 위 guard는 Task 클로저 안까지 전해지지 않아서 macOS 14 대상으로 빌드할 때 다시 확인한다
    Task { if #available(macOS 26.0, *) { _ = await configuration(480, 270); print("ok") }; sem.signal() }
} else if args.count == 3, let w = Int(args[1]), let h = Int(args[2]) {
    Task { if #available(macOS 26.0, *) { await run(w, h) }; sem.signal() }
} else {
    fail("사용: vtsr <width> <height> | vtsr --check")
}
sem.wait()
