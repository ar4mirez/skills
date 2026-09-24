//! Build graph for tally: a library module, a CLI, an HTTP service, a C static
//! library, and every test suite behind `zig build test`.
//!
//!   zig build                                   # Debug build of everything into zig-out/
//!   zig build test                              # all tests (Debug)
//!   zig build test -Doptimize=ReleaseSafe       # the same tests with release codegen
//!   zig build -Dtarget=x86_64-linux-musl -Doptimize=ReleaseSafe   # static Linux binaries
//!   zig build run -- -n 5 README.md             # run the CLI
const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const strip = b.option(bool, "strip", "Strip debug info from binaries (default: false)") orelse false;

    // The reusable library. `addModule` (not `createModule`) exposes it to
    // packages that depend on this one: `dep.module("tally")`.
    const tally = b.addModule("tally", .{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
        .optimize = optimize,
    });

    const cli = b.addExecutable(.{
        .name = "tally",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .strip = strip,
            .imports = &.{.{ .name = "tally", .module = tally }},
        }),
    });
    b.installArtifact(cli);

    const service = b.addExecutable(.{
        .name = "tallyd",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/server.zig"),
            .target = target,
            .optimize = optimize,
            .strip = strip,
            .imports = &.{.{ .name = "tally", .module = tally }},
        }),
    });
    b.installArtifact(service);

    // C ABI: static library + header for C/C++ callers.
    const c_lib = b.addLibrary(.{
        .name = "tally",
        .linkage = .static,
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/c_api.zig"),
            .target = target,
            .optimize = optimize,
            .link_libc = true,
            .imports = &.{.{ .name = "tally", .module = tally }},
        }),
    });
    c_lib.installHeader(b.path("include/tally.h"), "tally.h");
    b.installArtifact(c_lib);

    const run_cli = b.addRunArtifact(cli);
    if (b.args) |args| run_cli.addArgs(args);
    b.step("run", "Run the tally CLI").dependOn(&run_cli.step);

    const run_service = b.addRunArtifact(service);
    b.step("serve", "Run the tallyd service").dependOn(&run_service.step);

    // Every module with `test` blocks gets its own test artifact. `addTest`
    // only builds; `addRunArtifact` runs.
    const test_step = b.step("test", "Run all tests");
    for ([_]*std.Build.Module{ tally, cli.root_module, service.root_module, c_lib.root_module }) |m| {
        const t = b.addTest(.{ .root_module = m });
        test_step.dependOn(&b.addRunArtifact(t).step);
    }

    // C interop smoke test: a C program linked against the Zig static library.
    // Only run it when the target is the host (cross builds cannot execute it).
    const c_example = b.addExecutable(.{
        .name = "use_tally",
        .root_module = b.createModule(.{ .target = target, .optimize = optimize, .link_libc = true }),
    });
    c_example.root_module.addCSourceFile(.{ .file = b.path("examples/use_tally.c"), .flags = &.{ "-Wall", "-Wextra", "-Werror" } });
    c_example.root_module.addIncludePath(b.path("include"));
    c_example.root_module.linkLibrary(c_lib);
    const run_c_example = b.addRunArtifact(c_example);
    run_c_example.expectExitCode(0);
    if (target.query.isNative()) test_step.dependOn(&run_c_example.step);

    // `zig build fmt` rewrites; CI runs `zig fmt --check .` instead.
    const fmt = b.addFmt(.{ .paths = &.{ "build.zig", "build.zig.zon", "src" } });
    b.step("fmt", "Format all Zig sources").dependOn(&fmt.step);
}
