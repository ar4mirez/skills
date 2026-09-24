const std = @import("std");

pub fn Pair(comptime A: type, comptime B: type) type {
    return @Type(.{ .@"struct" = .{
        .layout = .auto,
        .fields = &.{
            .{ .name = "a", .type = A, .default_value_ptr = null, .is_comptime = false, .alignment = @alignOf(A) },
            .{ .name = "b", .type = B, .default_value_ptr = null, .is_comptime = false, .alignment = @alignOf(B) },
        },
        .decls = &.{},
        .is_tuple = false,
    } });
}

pub fn fetchAll(urls: []const []const u8) void {
    for (urls) |u| {
        var frame = async fetchOne(u);
        _ = await frame;
    }
}

fn fetchOne(url: []const u8) usize {
    return url.len;
}
