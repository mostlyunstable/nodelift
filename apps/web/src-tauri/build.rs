fn main() {
    // The web UI is embedded into the binary at compile time. Without this line cargo does not notice a
    // changed `dist/` and can ship an old interface inside a new build.
    println!("cargo:rerun-if-changed=../dist");
    tauri_build::build()
}
