const std = @import("std");
const store = @import("store.zig");

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    const allocator = gpa.allocator();

    const args = try std.process.argsAlloc(allocator);
    const port_text = std.os.getenv("PORT") orelse "8080";
    const port = std.fmt.parseInt(u16, port_text, 10) catch unreachable;

    var s = store.Store.init(allocator);
    try s.load(args[1]);

    const stdout = std.io.getStdOut().writer();
    try stdout.print("listening on {d}\n", .{port});

    const address = try std.net.Address.parseIp("0.0.0.0", port);
    var server = try address.listen(.{});
    while (true) {
        const conn = try server.accept();
        const thread = try std.Thread.spawn(.{}, store.handle, .{ &s, conn });
        thread.detach();
    }
}
