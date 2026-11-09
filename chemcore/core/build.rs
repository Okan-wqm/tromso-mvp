//! Writes CORE_HASH: the FNV-1a 64 digest of every file of src/ (sorted by name, carriage returns dropped so a
//! Windows checkout hashes as a Linux one), each fed as "name\n" + text + "\n". Not a security hash: it tells a
//! stale build from the source it claims to be (Django check core.E001 against chemcore/EXPECTED).
use std::env;
use std::fs;
use std::io;
use std::path::Path;

fn main() -> io::Result<()> {
    let source = Path::new("src");
    println!("cargo:rerun-if-changed=src");
    let mut names = Vec::new();
    for entry in fs::read_dir(source)? {
        names.push(entry?.file_name().to_string_lossy().into_owned());
    }
    names.sort();
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    let mut feed = |bytes: &[u8]| {
        for &byte in bytes {
            hash ^= u64::from(byte);
            hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
        }
    };
    for name in &names {
        let text: Vec<u8> = fs::read(source.join(name))?
            .into_iter()
            .filter(|&b| b != b'\r')
            .collect();
        feed(name.as_bytes());
        feed(b"\n");
        feed(&text);
        feed(b"\n");
    }
    let out =
        Path::new(&env::var_os("OUT_DIR").ok_or_else(|| io::Error::other("OUT_DIR is not set"))?).join("core_hash.rs");
    fs::write(out, format!("pub const CORE_HASH: &str = \"{hash:016x}\";\n"))
}
