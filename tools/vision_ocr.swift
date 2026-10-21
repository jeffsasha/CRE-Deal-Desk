// macOS Vision OCR helper for SKW DealDesk.
// Usage: vision_ocr <file.pdf|image>  -> JSON array of page texts on stdout.
// PDF pages are rendered with PDFKit at 2x and recognized with VNRecognizeTextRequest
// (accurate mode). Runs fully offline.
import Foundation
import PDFKit
import Vision
import AppKit

func recognize(_ cg: CGImage) -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["en-US"]
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do { try handler.perform([request]) } catch { return "" }
    let observations = (request.results ?? [])
    // Sort top-to-bottom, then left-to-right (Vision uses a bottom-left origin).
    let sorted = observations.sorted { a, b in
        let dy = a.boundingBox.midY - b.boundingBox.midY
        if abs(dy) > 0.01 { return dy > 0 }
        return a.boundingBox.minX < b.boundingBox.minX
    }
    return sorted.compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

func renderPage(_ page: PDFPage, scale: CGFloat) -> CGImage? {
    let bounds = page.bounds(for: .mediaBox)
    let width = Int(bounds.width * scale), height = Int(bounds.height * scale)
    guard let ctx = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
    ctx.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: ctx)
    return ctx.makeImage()
}

let args = CommandLine.arguments
guard args.count >= 2 else { FileHandle.standardError.write("usage: vision_ocr <file> [pages]\n".data(using: .utf8)!); exit(2) }
let url = URL(fileURLWithPath: args[1])
var wanted: Set<Int>? = nil
if args.count >= 3 { wanted = Set(args[2].split(separator: ",").compactMap { Int($0) }) }
var pages: [String] = []
if url.pathExtension.lowercased() == "pdf" {
    guard let doc = PDFDocument(url: url) else { FileHandle.standardError.write("cannot open pdf\n".data(using: .utf8)!); exit(1) }
    for i in 0..<doc.pageCount {
        if let w = wanted, !w.contains(i + 1) { pages.append(""); continue }
        if let page = doc.page(at: i), let cg = renderPage(page, scale: 2.0) { pages.append(recognize(cg)) } else { pages.append("") }
    }
} else {
    guard let img = NSImage(contentsOf: url), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        FileHandle.standardError.write("cannot open image\n".data(using: .utf8)!); exit(1)
    }
    pages.append(recognize(cg))
}
let data = try! JSONSerialization.data(withJSONObject: pages, options: [])
FileHandle.standardOutput.write(data)
