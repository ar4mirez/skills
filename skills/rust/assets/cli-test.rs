//! End-to-end: run the real binary. Cargo builds it and exposes its path to integration tests.
use std::process::Command;

fn acme() -> Command {
    Command::new(env!("CARGO_BIN_EXE_acme"))
}

#[test]
fn encode_prints_code() {
    let out = acme().args(["encode", "125"]).output().unwrap();
    assert!(out.status.success());
    assert_eq!(String::from_utf8_lossy(&out.stdout), "21\n");
}

#[test]
fn bad_code_exits_1_with_context() {
    let out = acme().args(["decode", "a-b"]).output().unwrap();
    assert_eq!(out.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("decoding \"a-b\""), "{stderr}");
}

#[test]
fn usage_error_exits_2() {
    let out = acme().arg("frobnicate").output().unwrap();
    assert_eq!(out.status.code(), Some(2));
}
