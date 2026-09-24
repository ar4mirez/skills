.PHONY: help validate validate-ref test check new link unlink

PYTHON ?= python3
TARGET ?= $(HOME)/.claude/skills

help: ## Show available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

validate: ## Validate all skills (spec + repo conventions)
	$(PYTHON) scripts/validate_skills.py

validate-ref: ## Validate with the reference skills-ref CLI (must be on PATH)
	@for d in skills/*/; do skills-ref validate "$$d" || exit 1; done

test: ## Run tests for bundled skill scripts
	$(PYTHON) -m unittest discover -s tests -v

check: validate test ## Everything CI runs locally

new: ## Scaffold a skill: make new name=my-skill desc="One line"
	scripts/new-skill.sh "$(name)" "$(desc)"

link: ## Symlink skills into TARGET (default ~/.claude/skills) for live local dev
	scripts/link-local.sh "$(TARGET)"

unlink: ## Remove symlinks created by 'make link'
	scripts/link-local.sh --unlink "$(TARGET)"
