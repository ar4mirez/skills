use std::fmt;
use std::str::FromStr;

use crate::Error;

const ALPHABET: &[u8; 62] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

/// A base62 short code derived from a numeric id (`125` <-> `"21"`).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
#[cfg_attr(feature = "serde", serde(try_from = "String", into = "String"))]
pub struct ShortCode {
    code: String,
    id: u64,
}

impl ShortCode {
    /// Encodes an id. Infallible: every `u64` has a code.
    pub fn from_id(id: u64) -> Self {
        let mut buf = [0u8; 11]; // 62^11 > u64::MAX
        let mut n = id;
        let mut i = buf.len();
        loop {
            i -= 1;
            buf[i] = ALPHABET[usize::try_from(n % 62).unwrap_or_default()];
            n /= 62;
            if n == 0 {
                break;
            }
        }
        let code = buf[i..].iter().map(|&b| char::from(b)).collect();
        Self { code, id }
    }

    /// The id this code encodes.
    pub fn to_id(&self) -> u64 {
        self.id
    }

    /// Borrows the code as a string slice.
    pub fn as_str(&self) -> &str {
        &self.code
    }
}

fn digit(ch: char) -> Result<u64, Error> {
    let value = match ch {
        '0'..='9' => u32::from(ch) - u32::from('0'),
        'A'..='Z' => u32::from(ch) - u32::from('A') + 10,
        'a'..='z' => u32::from(ch) - u32::from('a') + 36,
        _ => return Err(Error::InvalidCodeChar(ch)),
    };
    Ok(u64::from(value))
}

impl FromStr for ShortCode {
    type Err = Error;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        if s.is_empty() {
            return Err(Error::CodeOutOfRange(s.to_owned()));
        }
        let mut id: u64 = 0;
        for ch in s.chars() {
            id = id
                .checked_mul(62)
                .and_then(|v| v.checked_add(digit(ch).ok()?))
                .ok_or_else(|| match digit(ch) {
                    Err(e) => e,
                    Ok(_) => Error::CodeOutOfRange(s.to_owned()),
                })?;
        }
        // Canonical form only: "021" and "21" must not both map to id 125.
        let canonical = Self::from_id(id);
        if canonical.code != s {
            return Err(Error::CodeOutOfRange(s.to_owned()));
        }
        Ok(canonical)
    }
}

impl TryFrom<String> for ShortCode {
    type Error = Error;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        value.parse()
    }
}

impl From<ShortCode> for String {
    fn from(code: ShortCode) -> Self {
        code.code
    }
}

impl fmt::Display for ShortCode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.code)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_values() {
        assert_eq!(ShortCode::from_id(0).as_str(), "0");
        assert_eq!(ShortCode::from_id(61).as_str(), "z");
        assert_eq!(ShortCode::from_id(62).as_str(), "10");
        assert_eq!(ShortCode::from_id(u64::MAX).as_str(), "LygHa16AHYF");
    }

    #[test]
    fn rejects_bad_input() {
        assert_eq!(
            "ab-c".parse::<ShortCode>(),
            Err(Error::InvalidCodeChar('-'))
        );
        assert!("".parse::<ShortCode>().is_err());
        assert!(
            "021".parse::<ShortCode>().is_err(),
            "non-canonical leading zero"
        );
        assert!("zzzzzzzzzzzz".parse::<ShortCode>().is_err(), "overflow");
    }
}
