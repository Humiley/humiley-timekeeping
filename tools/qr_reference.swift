import CoreImage
import Foundation

let text = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "HELLO"
let f = CIFilter(name: "CIQRCodeGenerator")!
f.setValue(text.data(using: .utf8), forKey: "inputMessage")
f.setValue("M", forKey: "inputCorrectionLevel")
let img = f.outputImage!
let ctx = CIContext()
let w = Int(img.extent.width), h = Int(img.extent.height)
let cg = ctx.createCGImage(img, from: img.extent)!
var bytes = [UInt8](repeating: 0, count: w * h * 4)
let space = CGColorSpaceCreateDeviceRGB()
let bctx = CGContext(data: &bytes, width: w, height: h, bitsPerComponent: 8,
                     bytesPerRow: w * 4, space: space,
                     bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
bctx.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
print("size \(w)x\(h)")
for y in 0..<h {
    var line = ""
    for x in 0..<w {
        line += bytes[(y * w + x) * 4] < 128 ? "1" : "0"
    }
    print(line)
}
