use thiserror::Error as ThisError;

/// Everything that can go wrong when constructing a domain value.
///
/// A library exposes one concrete, matchable error type per failure domain.
/// `#[non_exhaustive]` lets us add variants without a breaking release.
#[derive(Debug, Clone, PartialEq, Eq, ThisError)]
#[non_exhaustive]
pub enum Error {
    /// The input had no characters that can appear in a slug.
    #[error("slug is empty after normalization")]
    EmptySlug,
    /// The normalized slug is longer than [`crate::Slug::MAX_LEN`].
    #[error("slug is {len} bytes; the maximum is {max}")]
    SlugTooLong {
        /// Length of the normalized slug.
        len: usize,
        /// The allowed maximum.
        max: usize,
    },
    /// A short code contained a character outside `[0-9A-Za-z]`.
    #[error("invalid short-code character {0:?}")]
    InvalidCodeChar(char),
    /// A short code was empty or would overflow a `u64`.
    #[error("short code {0:?} is empty or out of range")]
    CodeOutOfRange(String),
}
