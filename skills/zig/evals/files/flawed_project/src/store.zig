const std = @import("std");

pub usingnamespace @import("util.zig");

pub const Item = struct { name: []const u8, qty: u32 };

pub const Store = struct {
    items: std.ArrayList(Item),
    mutex: std.Thread.Mutex = .{},
    arena: std.heap.ArenaAllocator,

    pub fn init(allocator: std.mem.Allocator) Store {
        return .{
            .items = std.ArrayList(Item).init(allocator),
            .arena = std.heap.ArenaAllocator.init(std.heap.page_allocator),
        };
    }

    pub fn load(self: *Store, path: []const u8) anyerror!void {
        const file = try std.fs.cwd().openFile(path, .{});
        const data = try file.readToEndAlloc(self.arena.allocator(), 1 << 20);
        var lines = std.mem.split(u8, data, "\n");
        while (lines.next()) |line| {
            self.items.append(.{ .name = line, .qty = 1 }) catch {};
        }
        std.debug.print("loaded {d} items\n", .{self.items.items.len});
    }

    pub fn snapshot(self: *Store, out: anytype) !void {
        self.mutex.lock();
        defer self.mutex.unlock();
        try std.json.stringify(self.items.items, .{}, out);
    }
};

pub fn handle(s: *Store, conn: std.net.Server.Connection) void {
    defer conn.stream.close();
    std.time.sleep(10 * std.time.ns_per_ms);
    var token: [16]u8 = undefined;
    std.crypto.random.bytes(&token);
    s.snapshot(conn.stream.writer()) catch unreachable;
}
