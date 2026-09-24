//! tally CLI: print the most frequent words of a file (or stdin).
//!
//!   tally [-n COUNT] [--json] [FILE]
//!
//! Exit codes: 0 ok, 1 runtime failure (I/O, bad input), 2 usage error.
const std = @import("std");
const Io = std.Io;
const tally = @import("tally");

const usage =
    \\Usage: tally [-n COUNT] [--json] [FILE]
    \\Print the COUNT (default 10) most frequent words of FILE, or stdin.
    \\
;

const Args = struct {
    n: usize = 10,
    json: bool = false,
    path: ?[]const u8 = null,
};

const ParseError = error{ Help, Usage };

/// Pure argument parsing, so it is unit-testable without a process.
fn parseArgs(argv: []const []const u8) ParseError!Args {
    var out: Args = .{};
    var i: usize = 1;
    while (i < argv.len) : (i += 1) {
        const arg = argv[i];
        if (std.mem.eql(u8, arg, "-h") or std.mem.eql(u8, arg, "--help")) return error.Help;
        if (std.mem.eql(u8, arg, "--json")) {
            out.json = true;
        } else if (std.mem.eql(u8, arg, "-n")) {
            i += 1;
            if (i == argv.len) return error.Usage;
            out.n = std.fmt.parseUnsigned(usize, argv[i], 10) catch return error.Usage;
        } else if (arg.len > 1 and arg[0] == '-') {
            return error.Usage;
        } else if (out.path == null) {
            out.path = arg;
        } else return error.Usage;
    }
    return out;
}

pub fn main(init: std.process.Init) !u8 {
    const gpa = init.gpa;
    const io = init.io;
    const argv = try init.minimal.args.toSlice(init.arena.allocator());

    var stdout_buf: [4096]u8 = undefined;
    var stdout_fw: Io.File.Writer = .init(.stdout(), io, &stdout_buf);
    const stdout = &stdout_fw.interface;

    const args = parseArgs(argv) catch |err| switch (err) {
        error.Help => {
            try stdout.writeAll(usage);
            try stdout.flush();
            return 0;
        },
        error.Usage => {
            std.debug.print("{s}", .{usage});
            return 2;
        },
    };

    const file: Io.File = if (args.path) |p|
        Io.Dir.cwd().openFile(io, p, .{}) catch |err| {
            std.log.err("cannot open '{s}': {t}", .{ p, err });
            return 1;
        }
    else
        .stdin();
    defer if (args.path != null) file.close(io);

    // The reader buffer bounds the longest line we accept.
    var in_buf: [64 * 1024]u8 = undefined;
    var fr = file.reader(io, &in_buf);

    var t = tally.countWords(gpa, &fr.interface, .{}) catch |err| switch (err) {
        error.ReadFailed => {
            std.log.err("read failed: {t}", .{fr.err.?});
            return 1;
        },
        error.StreamTooLong => {
            std.log.err("line longer than {d} bytes", .{in_buf.len});
            return 1;
        },
        else => |e| return e,
    };
    defer t.deinit(gpa);

    if (args.json) {
        try t.writeJson(gpa, stdout, args.n);
        try stdout.writeByte('\n');
    } else {
        const best = try t.top(gpa, args.n);
        defer gpa.free(best);
        for (best) |e| try stdout.print("{d:>8} {s}\n", .{ e.count, e.word });
    }
    try stdout.flush(); // Buffered writers do nothing until flushed.
    return 0;
}

test "parseArgs" {
    const a = try parseArgs(&.{ "tally", "-n", "3", "--json", "in.txt" });
    try std.testing.expectEqual(@as(usize, 3), a.n);
    try std.testing.expect(a.json);
    try std.testing.expectEqualStrings("in.txt", a.path.?);

    try std.testing.expectError(error.Usage, parseArgs(&.{ "tally", "-n" }));
    try std.testing.expectError(error.Usage, parseArgs(&.{ "tally", "--bogus" }));
    try std.testing.expectError(error.Help, parseArgs(&.{ "tally", "-h" }));
}
