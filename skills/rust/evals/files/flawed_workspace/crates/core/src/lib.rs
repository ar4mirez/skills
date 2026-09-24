use lazy_static::lazy_static;
use regex::Regex;

lazy_static! {
    static ref SKU: Regex = Regex::new(r"^[A-Z]{3}-\d{4}$").unwrap();
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Sku(String);

/// Parses a SKU like "ABC-1234".
pub fn parse_sku(input: &str) -> anyhow::Result<Sku> {
    if !SKU.is_match(input) {
        anyhow::bail!("bad sku {input}");
    }
    Ok(Sku(input.to_string()))
}

pub fn price_cents(raw: &str) -> u64 {
    println!("parsing price {raw}");
    raw.trim_start_matches('$').replace('.', "").parse().expect("price must be numeric")
}

pub fn first_byte(bytes: &[u8]) -> u8 {
    unsafe { *bytes.get_unchecked(0) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses() {
        assert_eq!(price_cents("$1.50"), 150);
        parse_sku("ABC-1234").unwrap();
    }
}
