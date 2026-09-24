//! C ABI for tally. Header: include/tally.h. Build: `zig build` -> zig-out/lib/libtally.a.
//!
//! Rules at the boundary: only extern-compatible types (pointers + lengths, fixed
//! ints, `extern struct`), no Zig errors or slices cross it, and the C caller
//! never frees Zig memory with `free()`.
const std = @import("std");
const tally = @import("tally");

/// Status codes returned to C. Keep in sync with include/tally.h.
pub const Status = enum(c_int) { ok = 0, out_of_memory = 1, word_too_long = 2 };

/// Counts whitespace-separated words in `text[0..len]`.
/// Writes the total to `out_total` and the number of distinct words to `out_distinct`.
export fn tally_count(text: [*]const u8, len: usize, out_total: *u64, out_distinct: *usize) Status {
    const gpa = std.heap.c_allocator; // C callers link libc anyway; malloc is the right default here.
    var r: std.Io.Reader = .fixed(text[0..len]);
    var t = tally.countWords(gpa, &r, .{}) catch |err| return switch (err) {
        error.OutOfMemory => .out_of_memory,
        error.WordTooLong => .word_too_long,
        error.ReadFailed, error.StreamTooLong => unreachable, // fixed reader over the whole input
    };
    defer t.deinit(gpa);
    out_total.* = t.total;
    out_distinct.* = t.distinct();
    return .ok;
}

test "tally_count" {
    var total: u64 = 0;
    var distinct: usize = 0;
    const text = "a b a";
    try std.testing.expectEqual(Status.ok, tally_count(text.ptr, text.len, &total, &distinct));
    try std.testing.expectEqual(@as(u64, 3), total);
    try std.testing.expectEqual(@as(usize, 2), distinct);
}
