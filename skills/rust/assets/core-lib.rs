//! Domain types for Acme short links.
//!
//! Parse, don't validate: every value here is checked once at construction, so code that
//! holds a [`Slug`] or [`ShortCode`] never re-checks it.
//!
//! ```
//! use acme_core::{ShortCode, Slug};
//!
//! let slug: Slug = "Hello, World!".parse()?;
//! assert_eq!(slug.as_str(), "hello-world");
//!
//! let code = ShortCode::from_id(125);
//! assert_eq!(code.as_str(), "21");
//! assert_eq!(code.to_id(), 125);
//! # Ok::<(), acme_core::Error>(())
//! ```
#![warn(missing_docs)]

mod code;
mod error;
mod slug;

pub use code::ShortCode;
pub use error::Error;
pub use slug::Slug;
