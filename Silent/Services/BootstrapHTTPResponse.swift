import Foundation

enum BootstrapHTTPResponse {
    /// HTTP/1.0 requests receive a fixed length or close-delimited response.
    static func parse(_ data: Data, complete: Bool) throws -> (Int, Data)? {
        guard let boundary = data.range(of: Data([13, 10, 13, 10])) else {
            if complete || data.count >= 16 * 1024 { throw URLError(.badServerResponse) }
            return nil
        }
        let header = data[..<boundary.lowerBound]
        guard header.count < 16 * 1024, let text = String(data: header, encoding: .utf8) else {
            throw URLError(.badServerResponse)
        }
        let lines = text.components(separatedBy: "\r\n")
        let statusLine = lines[0].split(separator: " ", maxSplits: 2)
        guard statusLine.count >= 2, statusLine[0].hasPrefix("HTTP/1."),
              let status = Int(statusLine[1]), (200...599).contains(status) else { throw URLError(.badServerResponse) }
        var length: Int?
        for line in lines.dropFirst() {
            let pair = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
            guard pair.count == 2 else { throw URLError(.badServerResponse) }
            switch pair[0].lowercased() {
            case "transfer-encoding": throw URLError(.badServerResponse)
            case "content-length":
                guard length == nil, let value = Int(pair[1].trimmingCharacters(in: .whitespaces)),
                      (0...256 * 1024).contains(value) else { throw URLError(.badServerResponse) }
                length = value
            default: break
            }
        }
        let body = data[boundary.upperBound...]
        if let length {
            if body.count == length { return (status, Data(body)) }
            if body.count > length || complete { throw URLError(.badServerResponse) }
        } else if complete {
            return (status, Data(body))
        }
        return nil
    }
}
