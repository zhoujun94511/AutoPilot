// ios-avf-capture: native macOS iOS-screen capture helper.
//
// Enables the hidden CoreMediaIO screen-capture devices (the same source
// QuickTime uses), captures the connected iPhone screen via AVFoundation, encodes
// it with the hardware H.264 encoder (VideoToolbox) and writes an Annex-B H.264
// elementary stream to stdout:
//
//     magic "AVFH" (4 bytes, once)
//     then a continuous Annex-B H.264 stream (00 00 00 01 start-code delimited
//     NAL units; SPS/PPS are re-emitted before every IDR).
//
// H.264 (vs the old per-frame JPEG) is why this can be smooth like QuickTime:
// hardware temporal compression easily sustains 60fps, the pipe carries ~10-50KB
// per frame instead of hundreds of KB, and the parent decodes with VideoToolbox
// via PyAV. This does NOT fight the system for the raw USB interface (which the
// com.apple.cmio DriverKit extension owns exclusively on modern macOS); it
// consumes the OS-provided capture device instead.
//
// Usage:
//   ios-avf-capture --list                 # print devices as JSON to stdout
//   ios-avf-capture [--index N] [--unique-id ID] [--bitrate BPS] [--fps N]
//
// Diagnostics go to stderr; only the H.264 stream goes to stdout.

import AVFoundation
import CoreMediaIO
import Foundation
import VideoToolbox

// MARK: - stderr logging

func elog(_ s: String) {
    FileHandle.standardError.write((s + "\n").data(using: .utf8)!)
}

// MARK: - Enable hidden iOS screen-capture DAL devices

func enableScreenCaptureDevices() {
    func setAllow(_ selector: Int) {
        var prop = CMIOObjectPropertyAddress(
            mSelector: CMIOObjectPropertySelector(selector),
            mScope: CMIOObjectPropertyScope(kCMIOObjectPropertyScopeGlobal),
            mElement: CMIOObjectPropertyElement(kCMIOObjectPropertyElementMain))
        var allow: UInt32 = 1
        _ = CMIOObjectSetPropertyData(
            CMIOObjectID(kCMIOObjectSystemObject), &prop, 0, nil,
            UInt32(MemoryLayout<UInt32>.size), &allow)
    }
    setAllow(kCMIOHardwarePropertyAllowScreenCaptureDevices)
    setAllow(kCMIOHardwarePropertyAllowWirelessScreenCaptureDevices)
}

// MARK: - Camera permission (blocking)

func ensureCameraAccess() -> Bool {
    switch AVCaptureDevice.authorizationStatus(for: .video) {
    case .authorized:
        return true
    case .notDetermined:
        let sem = DispatchSemaphore(value: 0)
        var granted = false
        AVCaptureDevice.requestAccess(for: .video) { g in
            granted = g
            sem.signal()
        }
        sem.wait()
        return granted
    default:
        return false
    }
}

// MARK: - Device discovery

// The iPhone *screen* capture source is a MUXED (audio+video) device, distinct from
// the Continuity Camera (a plain .video device that captures the rear camera). Both
// QuickTime and every working USB screen-recorder select the screen by filtering on
// AVMediaType.muxed. Filtering by nil media type returns the Continuity Camera → the
// black webcam picture we were seeing.
func screenDevices() -> [AVCaptureDevice] {
    let s = AVCaptureDevice.DiscoverySession(
        deviceTypes: [.external], mediaType: .muxed, position: .unspecified)
    return s.devices
}

func normUDID(_ s: String) -> String {
    return s.lowercased().replacingOccurrences(of: "-", with: "")
}

// Pick the iOS screen device: exact/normalized uniqueID == requested UDID, else the
// first muxed device, else index. (All candidates here are already muxed = screen.)
func pickDevice(_ devs: [AVCaptureDevice], uniqueID: String?, index: Int) -> AVCaptureDevice? {
    if let uid = uniqueID, !uid.isEmpty {
        let want = normUDID(uid)
        if let m = devs.first(where: { normUDID($0.uniqueID) == want }) { return m }
        if let m = devs.first(where: {
            let u = normUDID($0.uniqueID); return u.hasPrefix(want) || want.hasPrefix(u)
        }) { return m }
    }
    if index < devs.count { return devs[index] }
    return devs.first
}

// MARK: - Args

struct Args {
    var list = false
    var index = 0
    var uniqueID: String? = nil
    var bitrate: Int = 12_000_000   // ~12 Mbps; plenty for a phone screen at native res
    var fps: Int = 60
}

func parseArgs() -> Args {
    var a = Args()
    var it = CommandLine.arguments.dropFirst().makeIterator()
    while let arg = it.next() {
        switch arg {
        case "--list": a.list = true
        case "--index": if let v = it.next() { a.index = Int(v) ?? 0 }
        case "--unique-id": a.uniqueID = it.next()
        case "--bitrate": if let v = it.next() { a.bitrate = Int(v) ?? 12_000_000 }
        case "--fps": if let v = it.next() { a.fps = Int(v) ?? 60 }
        // Back-compat: older callers may still pass these; downscaling/quality now
        // live on the decode side (PyAV reformat) / are controlled via --bitrate.
        case "--quality": _ = it.next()
        case "--max-width": _ = it.next()
        default: break
        }
    }
    return a
}

// MARK: - Elementary-stream writer (serialized stdout)

final class StreamWriter {
    private let q = DispatchQueue(label: "avf.stdout")
    private let out = FileHandle.standardOutput
    private var wroteMagic = false
    private(set) var failed = false
    private let lock = NSLock()
    private var inFlight = 0

    // Accept a new input frame for encoding only when the previous access unit has
    // been fully written. Bounds end-to-end latency to ~1 frame: if the consumer
    // (pipe → PyAV decode → GUI) stalls, we skip *input* frames — which is safe for
    // H.264 (the stream stays valid, just lower fps) — instead of piling up a growing
    // backlog. This is what keeps the mirror feeling real-time like QuickTime.
    func canAccept() -> Bool {
        lock.lock(); defer { lock.unlock() }
        return !failed && inFlight == 0
    }

    func write(_ data: Data) {
        lock.lock(); inFlight += 1; lock.unlock()
        q.async {
            defer { self.lock.lock(); self.inFlight = max(0, self.inFlight - 1); self.lock.unlock() }
            if self.failed { return }
            var buf = Data()
            if !self.wroteMagic {
                buf.append(contentsOf: Array("AVFH".utf8))
                self.wroteMagic = true
            }
            buf.append(data)
            do {
                try self.out.write(contentsOf: buf)
            } catch {
                // stdout pipe closed by the parent → time to shut down.
                self.failed = true
                elog("stdout closed, exiting")
                exit(0)
            }
        }
    }
}

// MARK: - H.264 hardware encoder (VideoToolbox)

private let kAnnexBStartCode: [UInt8] = [0, 0, 0, 1]

// C-style VideoToolbox output callback → routes to the owning H264Encoder instance.
private func vtOutputCallback(
    _ refcon: UnsafeMutableRawPointer?,
    _ sourceFrameRefcon: UnsafeMutableRawPointer?,
    _ status: OSStatus,
    _ infoFlags: VTEncodeInfoFlags,
    _ sampleBuffer: CMSampleBuffer?
) {
    guard status == noErr, let sb = sampleBuffer, CMSampleBufferDataIsReady(sb),
          let refcon = refcon else { return }
    Unmanaged<H264Encoder>.fromOpaque(refcon).takeUnretainedValue().handleEncoded(sb)
}

final class H264Encoder {
    private var session: VTCompressionSession?
    private var width = 0
    private var height = 0
    private let bitrate: Int
    private let fps: Int
    private let writer: StreamWriter

    init(bitrate: Int, fps: Int, writer: StreamWriter) {
        self.bitrate = bitrate
        self.fps = fps
        self.writer = writer
    }

    func encode(_ pb: CVPixelBuffer, pts: CMTime) {
        let w = CVPixelBufferGetWidth(pb)
        let h = CVPixelBufferGetHeight(pb)
        // The iPhone screen device may deliver a placeholder size first and then switch
        // to the real native resolution/orientation; recreate the session on any change.
        if session == nil || w != width || h != height {
            recreate(w, h)
        }
        guard let s = session else { return }
        VTCompressionSessionEncodeFrame(
            s, imageBuffer: pb, presentationTimeStamp: pts, duration: .invalid,
            frameProperties: nil, sourceFrameRefcon: nil, infoFlagsOut: nil)
    }

    private func recreate(_ w: Int, _ h: Int) {
        if let s = session {
            VTCompressionSessionInvalidate(s)
            session = nil
        }
        width = w; height = h
        var s: VTCompressionSession?
        let st = VTCompressionSessionCreate(
            allocator: kCFAllocatorDefault,
            width: Int32(w), height: Int32(h),
            codecType: kCMVideoCodecType_H264,
            encoderSpecification: nil, imageBufferAttributes: nil,
            compressedDataAllocator: nil,
            outputCallback: vtOutputCallback,
            refcon: Unmanaged.passUnretained(self).toOpaque(),
            compressionSessionOut: &s)
        guard st == noErr, let sess = s else {
            elog("ERROR: VTCompressionSessionCreate failed status=\(st)")
            return
        }
        session = sess
        // Low-latency real-time config: no frame reordering (no B-frames → every input
        // frame maps to one output access unit with no lookahead delay), bounded key
        // frame interval so a decoder that joins/recovers re-syncs within ~2s.
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_RealTime, value: kCFBooleanTrue)
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_AllowFrameReordering, value: kCFBooleanFalse)
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_ProfileLevel,
                             value: kVTProfileLevel_H264_High_AutoLevel)
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_AverageBitRate,
                             value: NSNumber(value: bitrate))
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_ExpectedFrameRate,
                             value: NSNumber(value: fps))
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_MaxKeyFrameInterval,
                             value: NSNumber(value: fps * 2))
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_MaxKeyFrameIntervalDuration,
                             value: NSNumber(value: 2.0))
        VTCompressionSessionPrepareToEncodeFrames(sess)
        elog("h264 session \(w)x\(h) bitrate=\(bitrate) fps=\(fps)")
    }

    // Called from vtOutputCallback: build an Annex-B access unit and hand to the writer.
    func handleEncoded(_ sb: CMSampleBuffer) {
        var au = Data()
        if Self.isKeyframe(sb), let fmt = CMSampleBufferGetFormatDescription(sb) {
            au.append(Self.parameterSetsAnnexB(fmt))   // re-emit SPS/PPS before each IDR
        }
        if let bb = CMSampleBufferGetDataBuffer(sb) {
            au.append(Self.avccToAnnexB(bb))
        }
        if !au.isEmpty { writer.write(au) }
    }

    private static func isKeyframe(_ sb: CMSampleBuffer) -> Bool {
        guard let arr = CMSampleBufferGetSampleAttachmentsArray(sb, createIfNecessary: false)
                as? [[CFString: Any]], let first = arr.first else { return true }
        if let notSync = first[kCMSampleAttachmentKey_NotSync] as? Bool { return !notSync }
        return true   // absence of NotSync means this IS a sync (key) frame
    }

    private static func parameterSetsAnnexB(_ fmt: CMFormatDescription) -> Data {
        var out = Data()
        var count = 0
        CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
            fmt, parameterSetIndex: 0, parameterSetPointerOut: nil,
            parameterSetSizeOut: nil, parameterSetCountOut: &count, nalUnitHeaderLengthOut: nil)
        for i in 0..<count {
            var ptr: UnsafePointer<UInt8>?
            var size = 0
            if CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
                fmt, parameterSetIndex: i, parameterSetPointerOut: &ptr,
                parameterSetSizeOut: &size, parameterSetCountOut: nil,
                nalUnitHeaderLengthOut: nil) == noErr, let p = ptr {
                out.append(contentsOf: kAnnexBStartCode)
                out.append(p, count: size)
            }
        }
        return out
    }

    private static func avccToAnnexB(_ bb: CMBlockBuffer) -> Data {
        var out = Data()
        var total = 0
        var dataPtr: UnsafeMutablePointer<Int8>?
        guard CMBlockBufferGetDataPointer(
            bb, atOffset: 0, lengthAtOffsetOut: nil,
            totalLengthOut: &total, dataPointerOut: &dataPtr) == noErr,
            let base = dataPtr else { return out }
        let bytes = UnsafeRawPointer(base).assumingMemoryBound(to: UInt8.self)
        var offset = 0
        // VideoToolbox emits AVCC: each NAL is prefixed with a 4-byte big-endian length.
        while offset + 4 <= total {
            let nalLen = (Int(bytes[offset]) << 24) | (Int(bytes[offset + 1]) << 16)
                       | (Int(bytes[offset + 2]) << 8) | Int(bytes[offset + 3])
            offset += 4
            if nalLen <= 0 || offset + nalLen > total { break }
            out.append(contentsOf: kAnnexBStartCode)
            out.append(bytes + offset, count: nalLen)
            offset += nalLen
        }
        return out
    }
}

// MARK: - Capture delegate → feeds the encoder

final class Delegate: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    let writer: StreamWriter
    let encoder: H264Encoder
    var lastDims = (w: 0, h: 0)

    init(writer: StreamWriter, encoder: H264Encoder) {
        self.writer = writer
        self.encoder = encoder
    }

    func captureOutput(_ output: AVCaptureOutput,
                       didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        // Skip this input frame if the previous access unit is still being written —
        // keeps latency at ~1 frame (the H.264 stream stays valid; we just encode fewer).
        guard writer.canAccept() else { return }
        guard let pb = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let dims = (w: CVPixelBufferGetWidth(pb), h: CVPixelBufferGetHeight(pb))
        if dims.w != lastDims.w || dims.h != lastDims.h {
            // Placeholder→real-screen transition (e.g. stuck at landscape 1920x1080 =
            // stream never came up) is diagnosable from this line.
            elog("frame \(dims.w)x\(dims.h)")
            lastDims = dims
        }
        var pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        if !pts.isValid { pts = CMClockGetTime(CMClockGetHostTimeClock()) }
        encoder.encode(pb, pts: pts)
    }
}

// MARK: - Main

let args = parseArgs()
elog("start: authStatus=\(AVCaptureDevice.authorizationStatus(for: .video).rawValue)")
enableScreenCaptureDevices()

if args.list {
    if !ensureCameraAccess() {
        elog("camera permission denied")
    }
    // Warm-up + settle: the muxed screen device appears a few seconds after enabling.
    for _ in 0..<20 { if !screenDevices().isEmpty { break }; Thread.sleep(forTimeInterval: 0.25) }
    let devs = screenDevices()
    var arr: [[String: String]] = []
    for d in devs {
        arr.append(["name": d.localizedName, "uniqueID": d.uniqueID, "modelID": d.modelID])
    }
    let data = try! JSONSerialization.data(withJSONObject: arr, options: [])
    FileHandle.standardOutput.write(data)
    exit(0)
}

if !ensureCameraAccess() {
    elog("ERROR: camera permission not granted (System Settings > Privacy > Camera)")
    exit(2)
}

// MARK: Event-driven screen-device wait + capture
//
// CRITICAL (macOS 14/15): the muxed iOS *screen* device registers ASYNCHRONOUSLY after
// enabling kCMIOHardwarePropertyAllowScreenCaptureDevices. It only shows up if:
//   (a) we run at least one DiscoverySession as a "warm-up" (done below), AND
//   (b) the main run loop is actually running so CoreMediaIO can deliver the
//       AVCaptureDeviceWasConnected notification.
// Our previous version blocked the main thread with Thread.sleep BEFORE dispatchMain(),
// so the run loop never ran and the device never appeared (only the Continuity Camera).
// Here we warm up, observe the connection notification, AND poll on the live run loop.

// Retained globals so ARC keeps session/writer/encoder/delegate alive for the lifetime.
var gSession: AVCaptureSession? = nil
var gWriter: StreamWriter? = nil
var gEncoder: H264Encoder? = nil
var gDelegate: Delegate? = nil
var started = false
var loggedDevs = Set<String>()
let selectDeadline = Date().addingTimeInterval(25)

func startCapture(_ dev: AVCaptureDevice) {
    elog("using screen device name=\(dev.localizedName) uniqueID=\(dev.uniqueID) modelID=\(dev.modelID)")
    let session = AVCaptureSession()
    session.beginConfiguration()
    // Do NOT set sessionPreset or activeFormat: forcing them yields the black 1920x1080
    // landscape placeholder. Leaving both alone delivers the phone's native screen.
    do {
        let input = try AVCaptureDeviceInput(device: dev)
        if session.canAddInput(input) { session.addInput(input) }
        else { elog("ERROR: cannot add input"); exit(4) }
    } catch {
        elog("ERROR: AVCaptureDeviceInput: \(error)")
        exit(4)
    }
    let writer = StreamWriter()
    let encoder = H264Encoder(bitrate: args.bitrate, fps: args.fps, writer: writer)
    let delegate = Delegate(writer: writer, encoder: encoder)
    let vout = AVCaptureVideoDataOutput()
    vout.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
    vout.alwaysDiscardsLateVideoFrames = true
    vout.setSampleBufferDelegate(delegate, queue: DispatchQueue(label: "avf.samples"))
    if session.canAddOutput(vout) { session.addOutput(vout) }
    else { elog("ERROR: cannot add output"); exit(5) }
    session.commitConfiguration()

    NotificationCenter.default.addObserver(
        forName: .AVCaptureDeviceWasDisconnected, object: nil, queue: nil) { note in
        if let d = note.object as? AVCaptureDevice, d.uniqueID == dev.uniqueID {
            elog("device disconnected, exiting")
            exit(0)
        }
    }
    session.startRunning()
    elog("session started")
    gSession = session; gWriter = writer; gEncoder = encoder; gDelegate = delegate
}

// Attempt selection from the currently-visible muxed devices; start capture if found.
func trySelectAndStart() {
    if started { return }
    let devs = screenDevices()
    for d in devs where !loggedDevs.contains(d.uniqueID) {
        loggedDevs.insert(d.uniqueID)
        elog("device[muxed] name=\(d.localizedName) uniqueID=\(d.uniqueID) modelID=\(d.modelID)")
    }
    guard let dev = pickDevice(devs, uniqueID: args.uniqueID, index: args.index) else { return }
    started = true
    startCapture(dev)
}

// (a) Warm-up DiscoverySession — REQUIRED to prime CoreMediaIO device registration.
_ = screenDevices()

// (b) Observe async device connection on the main run loop.
NotificationCenter.default.addObserver(
    forName: .AVCaptureDeviceWasConnected, object: nil, queue: .main) { _ in
    trySelectAndStart()
}

// (c) Belt-and-suspenders: poll on the *running* run loop until found or timeout.
let poll = Timer(timeInterval: 0.5, repeats: true) { t in
    // Once capture started, keep the timer alive as a harmless heartbeat so the run
    // loop never returns (do NOT invalidate — that could let RunLoop.main.run() exit
    // and tear down the capture session).
    if started { return }
    trySelectAndStart()
    if !started && Date() > selectDeadline {
        t.invalidate()
        elog("ERROR: no iOS screen (muxed) capture device found. The iPhone only exposed a "
             + "camera (Continuity Camera). Try: unplug/replug the USB cable, unlock the phone "
             + "and confirm 'Trust This Computer', make sure it is NOT being used as a "
             + "Continuity Camera by another app, or open QuickTime > New Movie Recording and "
             + "pick the iPhone once to prime the screen device.")
        exit(3)
    }
}
RunLoop.main.add(poll, forMode: .common)
trySelectAndStart()   // immediate first attempt

// Run the main run loop (NOT dispatchMain): CoreMediaIO device registration and the
// AVCaptureDeviceWasConnected notification, plus our Timer, all require a live run loop.
// Frame delivery happens on the separate `avf.samples` dispatch queue, unaffected.
RunLoop.main.run()
