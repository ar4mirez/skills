use std::fmt;
use std::str::FromStr;

use crate::Error;

/// A URL-safe, lowercase, hyphen-separated identifier (`hello-world`).
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
#[cfg_attr(feature = "serde", serde(try_from = "String", into = "String"))]
pub struct Slug(String);

impl Slug {
    /// Longest slug we accept, in bytes.
    pub const MAX_LEN: usize = 64;

    /// Normalizes free text into a slug: ASCII alphanumerics are kept (lowercased),
    /// every other run of characters becomes a single `-`.
    ///
    /// # Errors
    /// [`Error::EmptySlug`] when nothing survives normalization, and
    /// [`Error::SlugTooLong`] when the result exceeds [`Slug::MAX_LEN`].
    pub fn parse(input: &str) -> Result<Self, Error> {
        let mut out = String::with_capacity(input.len());
        let mut pending_dash = false;
        for ch in input.chars() {
            if ch.is_ascii_alphanumeric() {
                if pending_dash && !out.is_empty() {
                    out.push('-');
                }
                pending_dash = false;
                out.push(ch.to_ascii_lowercase());
            } else {
                pending_dash = true;
            }
        }
        if out.is_empty() {
            return Err(Error::EmptySlug);
        }
        if out.len() > Self::MAX_LEN {
            return Err(Error::SlugTooLong {
                len: out.len(),
                max: Self::MAX_LEN,
            });
        }
        Ok(Self(out))
    }

    /// Borrows the slug as a string slice.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl FromStr for Slug {
    type Err = Error;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::parse(s)
    }
}

impl TryFrom<String> for Slug {
    type Error = Error;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::parse(&value)
    }
}

impl From<Slug> for String {
    fn from(slug: Slug) -> Self {
        slug.0
    }
}

impl AsRef<str> for Slug {
    fn as_ref(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for Slug {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn collapses_separators_and_lowercases() {
        assert_eq!(
            Slug::parse("  Hello,   World!! ").unwrap().as_str(),
            "hello-world"
        );
    }

    #[test]
    fn rejects_empty() {
        assert_eq!(Slug::parse("!!!"), Err(Error::EmptySlug));
    }

    #[test]
    fn rejects_too_long() {
        let long = "a".repeat(Slug::MAX_LEN + 1);
        assert!(matches!(Slug::parse(&long), Err(Error::SlugTooLong { .. })));
    }
}
