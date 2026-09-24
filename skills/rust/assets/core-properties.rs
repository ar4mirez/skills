//! Property tests: invariants that must hold for *every* input, not just the examples.
use acme_core::{ShortCode, Slug};
use proptest::prelude::*;

proptest! {
    #[test]
    fn short_code_round_trips(id in any::<u64>()) {
        let code = ShortCode::from_id(id);
        let parsed: ShortCode = code.as_str().parse().unwrap();
        prop_assert_eq!(parsed.to_id(), id);
    }

    #[test]
    fn slug_is_idempotent(input in "\\PC{0,80}") {
        if let Ok(slug) = Slug::parse(&input) {
            let again = Slug::parse(slug.as_str()).unwrap();
            prop_assert_eq!(again, slug);
        }
    }

    #[test]
    fn slug_charset(input in "\\PC{0,80}") {
        if let Ok(slug) = Slug::parse(&input) {
            prop_assert!(slug.as_str().bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-'));
            prop_assert!(!slug.as_str().starts_with('-') && !slug.as_str().ends_with('-'));
        }
    }
}
