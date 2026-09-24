//! tally: count word frequencies in UTF-8 text.
//!
//! Library root module. It never touches stdin, stdout, the environment, or a
//! global allocator: callers pass an `Allocator` and an `*Io.Reader` or
//! `*Io.Writer`. That keeps it testable with `std.testing.allocator` and
//! `Io.Reader.fixed`, and reusable from the CLI, the service, and the C ABI.
const std = @import("std");
const Allocator = std.mem.Allocator;
const Io = std.Io;

pub const Options = struct {
    /// Words longer than this are rejected with `error.WordTooLong`, which
    /// bounds per-word memory for untrusted input. At most `max_word_cap`.
    max_word_len: usize = 64,
    /// Fold ASCII letters to lowercase before counting.
    fold_case: bool = true,
};

/// Upper bound for `Options.max_word_len` (size of the case-folding buffer).
pub const max_word_cap = 256;

pub const Entry = struct {
    word: []const u8,
    count: u32,

    fn greater(_: void, a: Entry, b: Entry) bool {
        if (a.count != b.count) return a.count > b.count;
        return std.mem.order(u8, a.word, b.word) == .lt;
    }
};

pub const AddError = error{WordTooLong} || Allocator.Error;
pub const CountError = AddError || error{ ReadFailed, StreamTooLong };

/// Word counts. Owns every key it stores; free with `deinit` using the same
/// allocator passed to `add`.
pub const Tally = struct {
    map: std.StringHashMapUnmanaged(u32) = .empty,
    total: u64 = 0,

    pub const empty: Tally = .{};

    pub fn deinit(t: *Tally, gpa: Allocator) void {
        var it = t.map.keyIterator();
        while (it.next()) |key| gpa.free(key.*);
        t.map.deinit(gpa);
        t.* = undefined;
    }

    /// Counts one word. The word is copied; the caller keeps ownership of `word`.
    pub fn add(t: *Tally, gpa: Allocator, word: []const u8, opts: Options) AddError!void {
        std.debug.assert(opts.max_word_len <= max_word_cap);
        if (word.len == 0) return;
        if (word.len > opts.max_word_len) return error.WordTooLong;

        var buf: [max_word_cap]u8 = undefined;
        const key = if (opts.fold_case) std.ascii.lowerString(&buf, word) else word;

        const gop = try t.map.getOrPut(gpa, key);
        if (!gop.found_existing) {
            // If dupe fails, remove the half-inserted entry so deinit never
            // frees a key we do not own.
            gop.key_ptr.* = gpa.dupe(u8, key) catch |err| {
                t.map.removeByPtr(gop.key_ptr);
                return err;
            };
            gop.value_ptr.* = 0;
        }
        gop.value_ptr.* += 1;
        t.total += 1;
    }

    pub fn count(t: *const Tally, word: []const u8) u32 {
        return t.map.get(word) orelse 0;
    }

    pub fn distinct(t: *const Tally) usize {
        return t.map.count();
    }

    /// Returns up to `n` entries, most frequent first (ties sorted by word).
    /// Caller owns the returned slice (free with `gpa.free`); the `word`
    /// fields borrow from `t` and are valid until `t.deinit`.
    pub fn top(t: *const Tally, gpa: Allocator, n: usize) Allocator.Error![]Entry {
        const all = try gpa.alloc(Entry, t.map.count());
        var it = t.map.iterator();
        var i: usize = 0;
        while (it.next()) |kv| : (i += 1) {
            all[i] = .{ .word = kv.key_ptr.*, .count = kv.value_ptr.* };
        }
        std.mem.sort(Entry, all, {}, Entry.greater);
        if (n >= all.len) return all;
        // Shrink in place; if the allocator cannot, copy into a right-sized slice.
        if (gpa.resize(all, n)) return all[0..n];
        defer gpa.free(all);
        return gpa.dupe(Entry, all[0..n]);
    }

    /// Writes `{"total":N,"distinct":N,"top":[{"word":"..","count":N},...]}`.
    pub fn writeJson(t: *const Tally, gpa: Allocator, w: *Io.Writer, n: usize) (Allocator.Error || Io.Writer.Error)!void {
        const entries = try t.top(gpa, n);
        defer gpa.free(entries);
        try std.json.Stringify.value(.{
            .total = t.total,
            .distinct = t.distinct(),
            .top = entries,
        }, .{}, w);
    }
};

/// Reads `r` to the end, splitting on ASCII whitespace. Lines must fit in the
/// reader's buffer (`error.StreamTooLong` otherwise). Caller owns the result.
pub fn countWords(gpa: Allocator, r: *Io.Reader, opts: Options) CountError!Tally {
    var t: Tally = .empty;
    errdefer t.deinit(gpa);
    while (try r.takeDelimiter('\n')) |line| {
        var words = std.mem.tokenizeAny(u8, line, " \t\r\x0b\x0c");
        while (words.next()) |word| try t.add(gpa, word, opts);
    }
    return t;
}

test "counts words case-insensitively" {
    const gpa = std.testing.allocator;
    var r: Io.Reader = .fixed("The cat\nthe HAT the\n\ncat");
    var t = try countWords(gpa, &r, .{});
    defer t.deinit(gpa);

    try std.testing.expectEqual(@as(u32, 3), t.count("the"));
    try std.testing.expectEqual(@as(u32, 2), t.count("cat"));
    try std.testing.expectEqual(@as(u64, 6), t.total);
    try std.testing.expectEqual(@as(usize, 3), t.distinct());
}

test "top orders by count then word" {
    const gpa = std.testing.allocator;
    var r: Io.Reader = .fixed("b a c b a b");
    var t = try countWords(gpa, &r, .{});
    defer t.deinit(gpa);

    const best = try t.top(gpa, 2);
    defer gpa.free(best);
    try std.testing.expectEqual(@as(usize, 2), best.len);
    try std.testing.expectEqualStrings("b", best[0].word);
    try std.testing.expectEqualStrings("a", best[1].word);
}

test "rejects oversized words" {
    const gpa = std.testing.allocator;
    var r: Io.Reader = .fixed("ok toolongword");
    try std.testing.expectError(error.WordTooLong, countWords(gpa, &r, .{ .max_word_len = 4 }));
}

test "writeJson renders a stable document" {
    const gpa = std.testing.allocator;
    var r: Io.Reader = .fixed("go zig zig");
    var t = try countWords(gpa, &r, .{});
    defer t.deinit(gpa);

    var out: Io.Writer.Allocating = .init(gpa);
    defer out.deinit();
    try t.writeJson(gpa, &out.writer, 10);
    try std.testing.expectEqualStrings(
        \\{"total":3,"distinct":2,"top":[{"word":"zig","count":2},{"word":"go","count":1}]}
    , out.written());
}

fn countAllocFail(gpa: Allocator, text: []const u8) !void {
    var r: Io.Reader = .fixed(text);
    var t = try countWords(gpa, &r, .{});
    defer t.deinit(gpa);
    const best = try t.top(gpa, 1);
    gpa.free(best);
}

test "no leaks on any allocation failure" {
    try std.testing.checkAllAllocationFailures(std.testing.allocator, countAllocFail, .{"a b c a b a"});
}

test "fuzz: counts always sum to total" {
    try std.testing.fuzz({}, fuzzCount, .{ .corpus = &.{ "hello world", "a\nb\tc  a" } });
}

fn fuzzCount(_: void, smith: *std.testing.Smith) !void {
    const gpa = std.testing.allocator;
    var buf: [512]u8 = undefined;
    const len = smith.slice(&buf);
    var r: Io.Reader = .fixed(buf[0..len]);
    var t = countWords(gpa, &r, .{ .max_word_len = max_word_cap }) catch |err| switch (err) {
        error.WordTooLong => return, // expected for long random runs
        error.StreamTooLong => unreachable, // fixed readers hold the whole input
        else => |e| return e,
    };
    defer t.deinit(gpa);
    var sum: u64 = 0;
    var it = t.map.valueIterator();
    while (it.next()) |v| sum += v.*;
    try std.testing.expectEqual(t.total, sum);
}
