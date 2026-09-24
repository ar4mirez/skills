const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const exe = b.addExecutable(.{
        .name = "inventory",
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    b.installArtifact(exe);

    const lib = b.addStaticLibrary(.{
        .name = "inventory",
        .root_source_file = b.path("src/store.zig"),
        .target = target,
        .optimize = optimize,
    });
    b.installArtifact(lib);
}
