//! The handshake the server checks at start: version, formula version and the source digest.
use std::fs;
use std::path::Path;

/// FNV-1a 64 over the normalised sources, as the build computes it (the specification of `core_hash`).
fn digest_of_sources() -> String {
    // The manifest directory as cargo gives it to the running test (not as compiled in: a build reused from another
    // mount point would read nothing and hash nothing).
    let manifest = std::env::var("CARGO_MANIFEST_DIR").unwrap_or_else(|_| env!("CARGO_MANIFEST_DIR").to_owned());
    let source = Path::new(&manifest).join("src");
    let mut names: Vec<String> = fs::read_dir(&source)
        .map(|entries| {
            entries
                .filter_map(|e| e.ok())
                .map(|e| e.file_name().to_string_lossy().into_owned())
                .collect()
        })
        .unwrap_or_default();
    names.sort();
    assert!(
        names.iter().any(|name| name == "lib.rs"),
        "the sources were not found in {}",
        source.display()
    );
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    let mut feed = |bytes: &[u8]| {
        for &byte in bytes {
            hash ^= u64::from(byte);
            hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
        }
    };
    for name in &names {
        let text = fs::read(source.join(name)).unwrap_or_default();
        let text: Vec<u8> = text.into_iter().filter(|&b| b != b'\r').collect();
        feed(name.as_bytes());
        feed(b"\n");
        feed(&text);
        feed(b"\n");
    }
    format!("{hash:016x}")
}

#[test]
fn the_hash_is_the_digest_of_every_source_file() {
    assert_eq!(chemcore_core::core_hash(), digest_of_sources());
}

#[test]
fn the_hash_is_sixteen_lower_hex_digits() {
    let hash = chemcore_core::core_hash();
    assert_eq!(hash.len(), 16);
    assert!(hash.chars().all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c)));
}

#[test]
fn versions_are_stated() {
    assert_eq!(chemcore_core::VERSION, env!("CARGO_PKG_VERSION"));
    assert_eq!(chemcore_core::FORMULA_VERSION, 3);
    assert_eq!(chemcore_core::FORMULAS, [1, 3]);
}
