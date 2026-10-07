import Foundation
import CoreGraphics
import AppKit

let args = CommandLine.arguments
guard args.count >= 3 else {
    print("Usage: swift compile_pdf.swift <output.pdf> <img1> <img2> ...")
    exit(1)
}

let outputPath = args[1]
let imagePaths = Array(args[2...])

let pdfData = NSMutableData()
guard let consumer = CGDataConsumer(data: pdfData as CFMutableData) else {
    print("Failed to create CGDataConsumer")
    exit(1)
}

var mediaBox = CGRect(x: 0, y: 0, width: 1600, height: 900)
guard let context = CGContext(consumer: consumer, mediaBox: &mediaBox, nil) else {
    print("Failed to create CGContext")
    exit(1)
}

for path in imagePaths {
    guard let image = NSImage(contentsOfFile: path),
          let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        print("Failed to load image: \(path)")
        continue
    }
    
    context.beginPDFPage(nil)
    context.draw(cgImage, in: mediaBox)
    context.endPDFPage()
}

context.closePDF()
pdfData.write(toFile: outputPath, atomically: true)
print("PDF successfully written to \(outputPath)")
