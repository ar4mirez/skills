#!/bin/sh
# kit.sh: scaffold, audit, trace, index and rotate an agentic project kit.
#
# Portable POSIX sh. It uses only awk, sed, grep, find, wc, date, mkdir, mv
# and rm, and needs no language runtime. It writes only inside the target repo
# (scaffold, rotate) and never deletes anything but its own temp file, behind
# a path guard. Run `sh kit.sh --help` for usage and exit codes.
#
# The awk programs below are single-quoted on purpose.
# shellcheck disable=SC2016
set -u
set -f

ME=kit.sh
KIT_VERSION=1.0.0
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd -P)
ASSETS=$(cd -- "$SCRIPT_DIR/../assets" 2>/dev/null && pwd -P) || ASSETS=
TODAY=${KIT_TODAY:-$(date +%Y-%m-%d)}

# Size caps in estimated tokens (bytes / 4). AGENTS.md loads into every
# session, so it gets the smallest cap.
CAP_AGENTS=2000
CAP_ROOT=8000
CAP_CHANGES=3000
CAP_DOCS=5000

ROOT_DOCS="PRODUCT.md TECH.md SECURITY.md AGENTIC.md CHANGES.md GLOSSARY.md EXTENSIONS.md"
KIT_DIRS="docs/decisions docs/milestones docs/prd docs/runbooks docs/security docs/changes docs/incidents docs/evals docs/tech"
STATUSES=" draft active proposed decided accepted superseded deprecated withdrawn not-started in-progress blocked done open resolved released "
ID_RE='[A-Z][A-Z0-9]*-[0-9][0-9]+'

usage() {
	cat <<'EOF'
Usage: sh kit.sh <command> [options] <repo>

Commands:
  scaffold   Create the kit files that are missing. Never overwrites a file.
               --profile lite|full   which files to create (default: lite)
               --extensions          also create EXTENSIONS.md
               --map                 also create docs/kit-map.md (repos that
                                     already have their own docs)
               --project NAME        project name for the templates
                                     (default: the repo directory name)
               --owner NAME          owner for the front matter
  audit      Gap report against the kit. Read-only; writes nothing.
               --profile auto|lite|full (default: auto)
               --extensions          require EXTENSIONS.md too
               --strict              warnings also fail the audit
  trace      Requirement traceability matrix as TSV. Read-only.
  index      Every kit document and its front matter as TSV. Read-only.
  rotate     Move the "Unreleased" section of CHANGES.md into
             docs/changes/<version>.md and list it under "Released".
               --version VERSION     the version being released (required)
  guard-check <repo> <path>
             Print whether the delete guard would allow removing <path>.
             Deletes nothing.

Exit codes:
  0  success (audit: no errors; warnings allowed unless --strict)
  1  audit found errors, or a command refused to act
  2  usage error (bad option, missing or unsafe repo path)

Environment:
  KIT_TODAY=YYYY-MM-DD  overrides today's date (risk-acceptance expiry, tests)
EOF
}

die() {
	printf '%s: %s\n' "$ME" "$*" >&2
	exit 2
}

refuse() {
	printf '%s: %s\n' "$ME" "$*" >&2
	exit 1
}

resolve_dir() { (cd -- "$1" 2>/dev/null && pwd -P); }

home_real() {
	if [ -n "${HOME:-}" ] && [ -d "$HOME" ]; then resolve_dir "$HOME"; fi
}

# set_repo <dir>: resolve the target repo; refuse /, $HOME and non-directories.
set_repo() {
	[ -n "$1" ] || die "missing <repo> (run with --help)"
	[ -d "$1" ] || die "not a directory: $1"
	REPO=$(resolve_dir "$1") || die "cannot resolve: $1"
	[ "$REPO" != / ] || die "refusing to use / as the target repo"
	sr_home=$(home_real)
	if [ -n "$sr_home" ] && [ "$REPO" = "$sr_home" ]; then
		die "refusing to use \$HOME as the target repo"
	fi
}

# inside_repo <abs-dir>: true when the resolved directory is the repo or below it.
inside_repo() {
	case "$1/" in "$REPO"/*) return 0 ;; esac
	return 1
}

# guard_path <path>: succeed only for an existing non-directory strictly inside
# $REPO. Never /, $HOME, the repo root, or anything outside the repo. Sets GP_ABS.
guard_path() {
	gp=$1
	[ -n "$gp" ] || return 1
	case $gp in /*) ;; *) gp=$PWD/$gp ;; esac
	gp_dir=$(resolve_dir "$(dirname -- "$gp")") || return 1
	gp_base=$(basename -- "$gp")
	case $gp_base in . | .. | /) return 1 ;; esac
	if [ "$gp_dir" = / ]; then GP_ABS=/$gp_base; else GP_ABS=$gp_dir/$gp_base; fi
	[ "$GP_ABS" != / ] || return 1
	gp_home=$(home_real)
	if [ -n "$gp_home" ] && [ "$GP_ABS" = "$gp_home" ]; then return 1; fi
	[ "$GP_ABS" != "$REPO" ] || return 1
	case $GP_ABS in "$REPO"/*) ;; *) return 1 ;; esac
	[ -e "$GP_ABS" ] || [ -h "$GP_ABS" ] || return 1
	[ ! -d "$GP_ABS" ] || return 1
	return 0
}

guarded_rm() {
	guard_path "$1" || refuse "delete guard refused: $1"
	rm -f -- "$GP_ABS"
}

# relpath: strip "$REPO/" from each input line.
relpath() {
	awk -v p="$REPO/" '{ if (index($0, p) == 1) print substr($0, length(p) + 1); else print }'
}

# --- the kit: profile tag, asset file, target path -------------------------
kit_files() {
	cat <<'EOF'
lite AGENTS.md.tmpl AGENTS.md
lite CLAUDE.md.tmpl CLAUDE.md
lite PRODUCT.md PRODUCT.md
lite TECH.md TECH.md
lite SECURITY.md SECURITY.md
lite decisions-README.md docs/decisions/README.md
lite decision-TEMPLATE.md docs/decisions/TEMPLATE.md
full AGENTIC.md AGENTIC.md
full CHANGES.md CHANGES.md
full GLOSSARY.md GLOSSARY.md
full prd-README.md docs/prd/README.md
full milestones-README.md docs/milestones/README.md
full milestone-TEMPLATE.md docs/milestones/TEMPLATE.md
full runbooks-README.md docs/runbooks/README.md
full runbook-TEMPLATE.md docs/runbooks/TEMPLATE.md
full security-README.md docs/security/README.md
full changes-README.md docs/changes/README.md
full incidents-README.md docs/incidents/README.md
full incident-TEMPLATE.md docs/incidents/TEMPLATE.md
full evals-README.md docs/evals/README.md
full evals-agent-safety.md docs/evals/agent-safety.md
ext EXTENSIONS.md EXTENSIONS.md
map kit-map.md docs/kit-map.md
EOF
}

wanted() {
	case $1 in
	lite) return 0 ;;
	full) [ "$PROFILE" = full ] ;;
	ext) [ "$EXT" = 1 ] ;;
	map) [ "$MAP" = 1 ] ;;
	*) return 1 ;;
	esac
}

# kit_docs: repo-relative paths of the documents that carry front matter.
kit_docs() {
	for kd_f in $ROOT_DOCS; do
		if [ -f "$REPO/$kd_f" ]; then printf '%s\n' "$kd_f"; fi
	done
	for kd_d in $KIT_DIRS; do
		[ -d "$REPO/$kd_d" ] || continue
		find "$REPO/$kd_d" -type f -name '*.md' ! -name README.md ! -name TEMPLATE.md -print | relpath | sort
	done
}

# all_kit_md: every markdown file the kit owns, including indexes and templates.
all_kit_md() {
	for ak_f in AGENTS.md $ROOT_DOCS; do
		if [ -f "$REPO/$ak_f" ]; then printf '%s\n' "$ak_f"; fi
	done
	for ak_d in $KIT_DIRS; do
		[ -d "$REPO/$ak_d" ] || continue
		find "$REPO/$ak_d" -type f -name '*.md' -print | relpath | sort
	done
}

# --- docs/kit-map.md: kit file -> existing project doc, or n/a ------------
load_map() {
	MAPS=
	[ -f "$REPO/docs/kit-map.md" ] || return 0
	MAPS=$(awk -F'|' '
		/^[ \t]*\|/ {
			a = $2; b = $3
			gsub(/[ \t`]/, "", a); gsub(/[ \t`]/, "", b)
			if (!hdr) { if (tolower(a) == "kitfile") hdr = 1; next }
			if (a ~ /^:?-+:?$/ || a == "" || b == "" || b ~ /\{\{/) next
			print a "\t" b
			next
		}
		{ hdr = 0 }' "$REPO/docs/kit-map.md")
}

# map_target <rel>: print the mapped target of a kit file or of its folder.
map_target() {
	mt_dir=$(dirname -- "$1")
	printf '%s\n' "$MAPS" | awk -F'\t' -v r="$1" -v d="$mt_dir" '
		$1 == r || $1 == r "/" { print $2; found = 1; exit }
		$1 == d || $1 == d "/" { folder = $2 }
		END { if (found) exit 0; if (folder != "") { print folder; exit 0 }; exit 1 }'
}

mapped_files() {
	printf '%s\n' "$MAPS" | while IFS='	' read -r _ mf_target; do
		[ -n "$mf_target" ] && [ "$mf_target" != n/a ] || continue
		if [ -f "$REPO/$mf_target" ]; then printf '%s\n' "$mf_target"; fi
	done
}

# --- front matter -----------------------------------------------------------
# fm_dump <file>: "key<TAB>value" lines, or "!none" / "!open".
FM_AWK='
NR == 1 { if ($0 != "---") { state = "none"; exit } ; open = 1; next }
open && $0 == "---" { state = "ok"; exit }
NR > 60 { exit }
open {
	i = index($0, ":")
	if (i > 1) {
		k = substr($0, 1, i - 1); v = substr($0, i + 1)
		sub(/^[ \t]+/, "", v); sub(/[ \t]+$/, "", v)
		print k "\t" v
	}
}
END { if (NR == 0 || state == "none") print "!none"; else if (state != "ok") print "!open" }'

fm_dump() { awk "$FM_AWK" "$1"; }

fm_get() {
	fm_dump "$1" | awk -F'\t' -v k="$2" '$1 == k { sub(/^[^\t]*\t/, ""); print; exit }'
}

# fm_reqs <file>: requirement IDs listed in the front matter, one per line.
fm_reqs() {
	fm_get "$1" requirements | sed "s/[][\"']//g" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; /^$/d'
}

# --- requirements -------------------------------------------------------------
# A requirement is a row of a table whose header starts "| ID | Requirement".
DEFS_AWK='
FNR == 1 { intable = 0; sep = 0 }
/^[ \t]*\|/ {
	n = split($0, c, "|")
	first = c[2]; gsub(/[ \t`*]/, "", first)
	second = c[3]; gsub(/^[ \t]+|[ \t]+$/, "", second)
	if (!intable) {
		if (tolower(first) == "id" && tolower(second) ~ /^requirement/) { intable = 1; sep = 1 }
		next
	}
	if (first ~ /^:?-+:?$/) next
	state = (first ~ /^[A-Z][A-Z0-9]+-[0-9][0-9]+$/ && index(first, "-") <= 9 && length(first) <= 16) ? "ok" : "malformed"
	for (i = 4; state == "ok" && i <= n; i++) {
		cell = tolower(c[i]); gsub(/^[ \t]+|[ \t]+$/, "", cell)
		if (cell == "withdrawn" || cell == "deferred") state = "inactive"
	}
	f = FILENAME; if (index(f, root) == 1) f = substr(f, length(root) + 1)
	print first "\t" f "\t" FNR "\t" state
	next
}
{ intable = 0 }'

# TOK_AWK: every ID-shaped token in the input, as "token<TAB>file", deduplicated.
TOK_AWK='
{
	line = $0
	while (match(line, /[A-Z][A-Z0-9]*-[0-9][0-9]+/)) {
		t = substr(line, RSTART, RLENGTH)
		f = FILENAME; if (index(f, root) == 1) f = substr(f, length(root) + 1)
		if (!((t, f) in seen)) { seen[t, f] = 1; print t "\t" f }
		line = substr(line, RSTART + RLENGTH)
	}
}'

req_sources() {
	{
		kit_docs
		mapped_files
	} | sort -u
}

# collect_defs: sets DEFS ("id<TAB>file<TAB>line<TAB>state" lines).
collect_defs() {
	DEFS=$(req_sources | while IFS= read -r cd_f; do
		awk -v root="$REPO/" "$DEFS_AWK" "$REPO/$cd_f"
	done)
}

# code_tokens: ID tokens in every non-markdown file (code, tests, configs).
code_tokens() {
	find "$REPO" \( -type d \( -name .git -o -name .scratch -o -name node_modules -o -name vendor \
		-o -name .venv -o -name target -o -name dist -o -name build \) \) -prune \
		-o -type f ! -name '*.md' -print 2>/dev/null |
		while IFS= read -r ct_f; do
			if grep -q -E "$ID_RE" "$ct_f" 2>/dev/null; then
				awk -v root="$REPO/" "$TOK_AWK" "$ct_f"
			fi
		done
}

milestone_tokens() {
	[ -d "$REPO/docs/milestones" ] || return 0
	find "$REPO/docs/milestones" -type f -name '*.md' ! -name README.md ! -name TEMPLATE.md -print |
		while IFS= read -r mt_f; do awk -v root="$REPO/" "$TOK_AWK" "$mt_f"; done
}

has_milestones() {
	[ -d "$REPO/docs/milestones" ] || return 1
	[ -n "$(find "$REPO/docs/milestones" -type f -name '*.md' ! -name README.md ! -name TEMPLATE.md -print)" ]
}

# matrix: "id<TAB>state<TAB>source<TAB>test-files<TAB>milestones" for each requirement.
matrix() {
	{
		printf '%s\n' '#DEFS'
		printf '%s\n' "$DEFS"
		printf '%s\n' '#CODE'
		code_tokens
		printf '%s\n' '#MS'
		milestone_tokens
	} | awk -F'\t' '
		/^#DEFS$/ { s = 1; next } /^#CODE$/ { s = 2; next } /^#MS$/ { s = 3; next }
		$0 == "" { next }
		s == 1 && $4 != "malformed" && !($1 in st) { order[++n] = $1; st[$1] = $4; src[$1] = $2 ":" $3 }
		s == 2 { tests[$1]++ }
		s == 3 { m = $2; sub(/^.*\//, "", m); sub(/\.md$/, "", m); ms[$1] = (ms[$1] == "" ? m : ms[$1] "," m) }
		END {
			for (i = 1; i <= n; i++) {
				id = order[i]
				print id "\t" st[id] "\t" src[id] "\t" (tests[id] + 0) "\t" (ms[id] == "" ? "-" : ms[id])
			}
		}'
}

# --- findings -------------------------------------------------------------------
f() { printf '%s %s %s: %s\n' "$1" "$2" "$3" "$4"; }

tokens_of() {
	tk_b=$(wc -c <"$1" | tr -d ' ')
	echo $((tk_b / 4))
}

check_files() {
	kit_files | while read -r cf_tag cf_asset cf_rel; do
		: "$cf_asset"
		[ "$cf_tag" = map ] && continue
		wanted "$cf_tag" || continue
		if [ -e "$REPO/$cf_rel" ] || [ -h "$REPO/$cf_rel" ]; then continue; fi
		if cf_t=$(map_target "$cf_rel"); then
			[ "$cf_t" = n/a ] && continue
			if [ -e "$REPO/$cf_t" ]; then continue; fi
			f error K01 "$cf_rel" "mapped to $cf_t in docs/kit-map.md, but $cf_t does not exist"
		else
			f error K01 "$cf_rel" "missing for profile $PROFILE; scaffold it, or map it to an existing doc (or n/a) in docs/kit-map.md"
		fi
	done
}

check_claude() {
	cc=$REPO/CLAUDE.md
	if [ -h "$cc" ]; then
		f warn K02 CLAUDE.md "is a symlink; prefer a regular file whose only line is @AGENTS.md (symlinks break on some checkouts and tools)"
	elif [ -f "$cc" ]; then
		cc_body=$(sed -e 's/[[:space:]]*$//' -e '/^$/d' "$cc")
		if [ "$cc_body" != "@AGENTS.md" ]; then
			if grep -q '@AGENTS.md' "$cc"; then
				f error K02 CLAUDE.md "must contain only the line @AGENTS.md; move the other content into AGENTS.md"
			else
				f error K02 CLAUDE.md "must be the one-line import @AGENTS.md, not a copy (copies drift)"
			fi
		fi
	fi
}

check_agents() {
	[ -f "$REPO/AGENTS.md" ] || return 0
	if ! grep -E -i -q '^#+ .*safety' "$REPO/AGENTS.md"; then
		f error K16 AGENTS.md "has no agent safety section (scratch space, no writes outside the repo, guarded deletes, secrets)"
	fi
}

check_sizes() {
	all_kit_md | while IFS= read -r cs_f; do
		case $cs_f in
		AGENTS.md) cs_cap=$CAP_AGENTS ;;
		CHANGES.md) cs_cap=$CAP_CHANGES ;;
		*/*) cs_cap=$CAP_DOCS ;;
		*) cs_cap=$CAP_ROOT ;;
		esac
		cs_t=$(tokens_of "$REPO/$cs_f")
		if [ "$cs_t" -gt "$cs_cap" ]; then
			case $cs_f in
			CHANGES.md) cs_fix="rotate released versions into docs/changes/" ;;
			AGENTS.md) cs_fix="move detail into the spec files and link to it" ;;
			*) cs_fix="split it by area into docs/<kind>/<area>.md and keep this file as the index" ;;
			esac
			f error K03 "$cs_f" "~$cs_t tokens, over the cap of $cs_cap; $cs_fix"
		fi
	done
}

check_frontmatter() {
	kit_docs | while IFS= read -r cm_f; do
		cm_dump=$(fm_dump "$REPO/$cm_f")
		case $cm_dump in
		'!none')
			f error K04 "$cm_f" "no front matter; start the file with a --- block (status, version, owner, requirements)"
			continue
			;;
		'!open')
			f error K04 "$cm_f" "front matter is not closed with a --- line"
			continue
			;;
		esac
		cm_status=$(fm_get "$REPO/$cm_f" status)
		cm_version=$(fm_get "$REPO/$cm_f" version)
		cm_owner=$(fm_get "$REPO/$cm_f" owner)
		cm_reqs=$(fm_get "$REPO/$cm_f" requirements)
		if [ -z "$cm_status" ]; then
			f error K05 "$cm_f" "front matter has no status"
		else
			case $STATUSES in
			*" $cm_status "*) ;;
			*) f error K05 "$cm_f" "status '$cm_status' is not one of:$STATUSES" ;;
			esac
		fi
		if ! printf '%s\n' "$cm_version" | grep -E -q '^[0-9]+\.[0-9]+(\.[0-9]+)?$'; then
			f error K05 "$cm_f" "version '$cm_version' is not MAJOR.MINOR[.PATCH]"
		fi
		case $cm_owner in
		'' | *'{{'*) f error K05 "$cm_f" "front matter needs an owner (a role or handle)" ;;
		esac
		case $cm_reqs in
		'['*']') ;;
		*) f error K05 "$cm_f" "requirements must be an inline list, e.g. requirements: [] or [AUTH-01, AUTH-02]" ;;
		esac
	done
}

check_placeholders() {
	all_kit_md | while IFS= read -r cp_f; do
		case $cp_f in */TEMPLATE.md) continue ;; esac
		cp_n=$(grep -c '{{' "$REPO/$cp_f")
		if [ "$cp_n" -gt 0 ]; then
			f warn K06 "$cp_f" "$cp_n line(s) with unfilled {{placeholders}}"
		fi
	done
}

check_requirements() {
	printf '%s\n' "$DEFS" | awk -F'\t' '
		$0 == "" { next }
		$4 == "malformed" { print "error K07 " $2 ":" $3 ": requirement ID \"" $1 "\" is malformed; use AREA-NN (e.g. AUTH-01)"; next }
		($1 in at) { print "error K07 " $2 ":" $3 ": requirement " $1 " is already defined at " at[$1] "; IDs are unique and never reused"; next }
		{ at[$1] = $2 ":" $3 }'

	# Front matter lists must agree with the tables they summarise (K11),
	# and every other doc may only reference defined IDs (K08).
	cr_known=$(printf '%s\n' "$DEFS" | awk -F'\t' '$4 != "malformed" && $1 != "" { print $1 }' | sort -u)
	kit_docs | while IFS= read -r cr_f; do
		cr_listed=$(fm_reqs "$REPO/$cr_f" | sort -u)
		cr_defined=$(printf '%s\n' "$DEFS" | awk -F'\t' -v f="$cr_f" '$2 == f && $4 != "malformed" { print $1 }' | sort -u)
		if [ -n "$cr_defined" ]; then
			if [ "$cr_listed" != "$cr_defined" ]; then
				cr_want=$(printf '%s\n' "$cr_defined" | tr '\n' ' ' | sed 's/ $//; s/ /, /g')
				f warn K11 "$cr_f" "front matter requirements do not match the requirement table; expected [$cr_want]"
			fi
		elif [ -n "$cr_listed" ]; then
			printf '%s\n' "$cr_listed" | while IFS= read -r cr_id; do
				if ! printf '%s\n' "$cr_known" | grep -F -x -q "$cr_id"; then
					f error K08 "$cr_f" "references $cr_id, which no requirement table defines"
				fi
			done
		fi
	done

	[ -n "$DEFS" ] || return 0
	cr_ms=0
	if has_milestones; then cr_ms=1; fi
	matrix | while IFS='	' read -r cr_id cr_state cr_src cr_tests cr_mlist; do
		[ "$cr_state" = ok ] || continue
		if [ "$cr_tests" -eq 0 ]; then
			f warn K09 "$cr_src" "$cr_id has no test or code that names it; put the ID in the test name or a comment"
		fi
		if [ "$cr_ms" = 1 ] && [ "$cr_mlist" = - ]; then
			f warn K10 "$cr_src" "$cr_id is not planned in any milestone plan"
		fi
	done
}

# Risk acceptances: tables with an ID column and Accepted / Expires columns.
RISK_AWK='
function days(s,   y, m, d) {
	y = substr(s, 1, 4) + 0; m = substr(s, 6, 2) + 0; d = substr(s, 9, 2) + 0
	if (m <= 2) { y--; m += 12 }
	return 365 * y + int(y / 4) - int(y / 100) + int(y / 400) + int((153 * (m - 3) + 2) / 5) + d
}
function isdate(s) { return s ~ /^[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]$/ }
FNR == 1 { intable = 0; ca = 0; ce = 0 }
/^[ \t]*\|/ {
	n = split($0, c, "|")
	for (i = 1; i <= n; i++) { v = c[i]; gsub(/^[ \t`*]+|[ \t`*]+$/, "", v); c[i] = v }
	if (!intable) {
		ca = 0; ce = 0
		for (i = 2; i < n; i++) { l = tolower(c[i]); if (l == "accepted") ca = i; if (l == "expires") ce = i }
		if (tolower(c[2]) == "id" && ca && ce) intable = 1
		next
	}
	if (c[2] ~ /^:?-+:?$/ || c[2] == "") next
	id = c[2]; a = c[ca]; e = c[ce]
	where = FILENAME; if (index(where, root) == 1) where = substr(where, length(root) + 1)
	where = where ":" FNR
	if (!isdate(a) || !isdate(e)) { print "error K12 " where ": risk acceptance " id " needs Accepted and Expires dates as YYYY-MM-DD"; next }
	if (days(e) - days(a) > 90) print "error K12 " where ": risk acceptance " id " runs " (days(e) - days(a)) " days; the limit is 90, re-accept it with a new expiry"
	else if (days(e) < days(today)) print "error K12 " where ": risk acceptance " id " expired on " e "; fix the risk or re-accept it"
	else if (days(e) - days(today) <= 14) print "warn K12 " where ": risk acceptance " id " expires on " e "; review it"
	next
}
{ intable = 0 }'

check_risks() {
	{
		if [ -f "$REPO/SECURITY.md" ]; then printf '%s\n' SECURITY.md; fi
		if [ -d "$REPO/docs/security" ]; then
			find "$REPO/docs/security" -type f -name '*.md' ! -name TEMPLATE.md -print | relpath
		fi
		if ck_t=$(map_target SECURITY.md) && [ "$ck_t" != n/a ] && [ -f "$REPO/$ck_t" ]; then
			printf '%s\n' "$ck_t"
		fi
	} | sort -u | while IFS= read -r ck_f; do
		awk -v root="$REPO/" -v today="$TODAY" "$RISK_AWK" "$REPO/$ck_f"
	done
}

check_changes() {
	[ -f "$REPO/CHANGES.md" ] || return 0
	if grep -E -q '^## +\[?v?[0-9]' "$REPO/CHANGES.md"; then
		f warn K13 CHANGES.md "holds released version sections; keep only Unreleased here and run: kit.sh rotate --version X <repo>"
	fi
}

check_milestones() {
	[ -d "$REPO/docs/milestones" ] || return 0
	find "$REPO/docs/milestones" -type f -name '*.md' ! -name README.md ! -name TEMPLATE.md -print | relpath | sort |
		while IFS= read -r cmi_f; do
			cmi_b=$(fm_get "$REPO/$cmi_f" budget_tokens)
			if ! printf '%s\n' "$cmi_b" | grep -E -q '^[0-9]+$'; then
				f warn K14 "$cmi_f" "front matter needs budget_tokens (a number); size milestones in tokens, never in time"
			fi
			if ! grep -E -i -q '^#+ +exit tests' "$REPO/$cmi_f"; then
				f warn K14 "$cmi_f" "has no Exit tests section"
			fi
			if grep -E -i -q 'deadline|due date|due by|target date|(^|[^A-Za-z])ETA([^A-Za-z]|$)|story points|(man|person)-(days|hours)|[0-9]+ (hours|days|weeks) of (work|effort)' "$REPO/$cmi_f"; then
				f error K14 "$cmi_f" "plans in calendar time; size work in tokens and exit tests, never dates or hours"
			fi
		done
}

check_decisions() {
	[ -d "$REPO/docs/decisions" ] || return 0
	find "$REPO/docs/decisions" -type f -name '*.md' ! -name README.md ! -name TEMPLATE.md -print | relpath | sort |
		while IFS= read -r cd_f; do
			for cd_h in Options Recommendation Decision; do
				if ! grep -E -q "^## +$cd_h" "$REPO/$cd_f"; then
					f warn K15 "$cd_f" "has no '## $cd_h' section"
				fi
			done
			case $(fm_get "$REPO/$cd_f" status) in
			decided | accepted)
				if ! awk '/^## +Decision/ { s = 1; next } /^## / { s = 0 } s && /^>/ { q = 1 } END { exit !q }' "$REPO/$cd_f"; then
					f warn K15 "$cd_f" "is decided but the Decision section does not quote the owner's exact words (a > line)"
				fi
				;;
			esac
		done
}

check_incidents() {
	[ -d "$REPO/docs/incidents" ] || return 0
	find "$REPO/docs/incidents" -type f -name '*.md' ! -name README.md ! -name TEMPLATE.md -print | relpath | sort |
		while IFS= read -r ci_f; do
			if ! grep -E -i -q '^## +guardrail' "$REPO/$ci_f"; then
				f warn K17 "$ci_f" "has no '## Guardrail' section; every incident must end in a rule, test or check"
			fi
		done
}

# --- commands -----------------------------------------------------------------
PROFILE=
EXT=0
MAP=0
STRICT=0
PROJECT=
OWNER=
VERSION=
POS1=
POS2=

parse_args() {
	while [ $# -gt 0 ]; do
		case $1 in
		--profile)
			[ $# -ge 2 ] || die "--profile needs a value"
			PROFILE=$2
			shift 2
			;;
		--project)
			[ $# -ge 2 ] || die "--project needs a value"
			PROJECT=$2
			shift 2
			;;
		--owner)
			[ $# -ge 2 ] || die "--owner needs a value"
			OWNER=$2
			shift 2
			;;
		--version)
			[ $# -ge 2 ] || die "--version needs a value"
			VERSION=$2
			shift 2
			;;
		--extensions) EXT=1 && shift ;;
		--map) MAP=1 && shift ;;
		--strict) STRICT=1 && shift ;;
		-h | --help) usage && exit 0 ;;
		--) shift && break ;;
		-*) die "unknown option: $1 (run with --help)" ;;
		*)
			if [ -z "$POS1" ]; then POS1=$1; elif [ -z "$POS2" ]; then POS2=$1; else die "too many arguments: $1"; fi
			shift
			;;
		esac
	done
	while [ $# -gt 0 ]; do
		if [ -z "$POS1" ]; then POS1=$1; elif [ -z "$POS2" ]; then POS2=$1; else die "too many arguments: $1"; fi
		shift
	done
}

sed_escape() { printf '%s' "$1" | sed 's/[|&\\]/\\&/g'; }

no_newline() {
	case $1 in *'
'*) die "$2 must be a single line" ;; esac
}

write_new() {
	wn_asset=$1
	wn_rel=$2
	case $wn_rel in /* | *..*) refuse "bad target path: $wn_rel" ;; esac
	wn_dst=$REPO/$wn_rel
	if [ -e "$wn_dst" ] || [ -h "$wn_dst" ]; then
		printf 'skip    %s (exists)\n' "$wn_rel"
		return 0
	fi
	wn_dir=$(dirname -- "$wn_dst")
	wn_up=$wn_dir
	while [ ! -d "$wn_up" ]; do wn_up=$(dirname -- "$wn_up"); done
	wn_real=$(resolve_dir "$wn_up") || refuse "cannot resolve $wn_up"
	inside_repo "$wn_real" || refuse "refusing to write outside the repo: $wn_rel"
	mkdir -p -- "$wn_dir" || refuse "cannot create $wn_dir"
	wn_real=$(resolve_dir "$wn_dir") || refuse "cannot resolve $wn_dir"
	inside_repo "$wn_real" || refuse "refusing to write outside the repo: $wn_rel"
	if [ -n "$wn_asset" ]; then
		sed -e "s|{{project}}|$S_PROJECT|g" -e "s|{{date}}|$S_DATE|g" -e "$S_OWNER_EXPR" \
			"$ASSETS/$wn_asset" >"$wn_dst" || refuse "cannot write $wn_rel"
	else
		printf '*\n' >"$wn_dst" || refuse "cannot write $wn_rel"
	fi
	printf 'create  %s\n' "$wn_rel"
}

cmd_scaffold() {
	[ -n "$POS2" ] && die "scaffold takes one <repo>"
	set_repo "$POS1"
	if [ -z "$ASSETS" ] || [ ! -f "$ASSETS/AGENTS.md.tmpl" ]; then
		refuse "templates not found next to the script (expected ../assets)"
	fi
	PROFILE=${PROFILE:-lite}
	case $PROFILE in lite | full) ;; *) die "--profile must be lite or full" ;; esac
	[ -n "$PROJECT" ] || PROJECT=$(basename -- "$REPO")
	no_newline "$PROJECT" --project
	no_newline "$OWNER" --owner
	S_PROJECT=$(sed_escape "$PROJECT")
	S_DATE=$(sed_escape "$TODAY")
	if [ -n "$OWNER" ]; then
		S_OWNER_EXPR="s|{{owner}}|$(sed_escape "$OWNER")|g"
	else
		S_OWNER_EXPR='s|^$|&|'
	fi
	kit_files | while read -r sc_tag sc_asset sc_rel; do
		wanted "$sc_tag" || continue
		write_new "$sc_asset" "$sc_rel" || exit 1
	done || exit 1
	write_new "" .scratch/.gitignore || exit 1
	printf 'scaffold: profile %s into %s. Next: fill the {{placeholders}}, then run audit.\n' "$PROFILE" "$REPO"
}

cmd_audit() {
	[ -n "$POS2" ] && die "audit takes one <repo>"
	set_repo "$POS1"
	load_map
	PROFILE=${PROFILE:-auto}
	if [ "$PROFILE" = auto ]; then
		PROFILE=lite
		for au_f in AGENTIC.md CHANGES.md docs/milestones docs/runbooks docs/incidents; do
			if [ -e "$REPO/$au_f" ] || { au_t=$(map_target "$au_f") && [ "$au_t" != n/a ]; }; then PROFILE=full; fi
		done
	fi
	case $PROFILE in lite | full) ;; *) die "--profile must be auto, lite or full" ;; esac
	collect_defs
	au_out=$({
		check_files
		check_claude
		check_agents
		check_sizes
		check_frontmatter
		check_placeholders
		check_requirements
		check_risks
		check_changes
		check_milestones
		check_decisions
		check_incidents
	} | sed '/^$/d')
	if [ -n "$au_out" ]; then printf '%s\n' "$au_out"; fi
	au_e=$(printf '%s\n' "$au_out" | grep -c '^error ')
	au_w=$(printf '%s\n' "$au_out" | grep -c '^warn ')
	printf 'audit: %s errors, %s warnings (profile %s, kit %s, %s)\n' "$au_e" "$au_w" "$PROFILE" "$KIT_VERSION" "$REPO"
	[ "$au_e" -eq 0 ] || exit 1
	if [ "$STRICT" = 1 ] && [ "$au_w" -gt 0 ]; then exit 1; fi
	exit 0
}

cmd_trace() {
	[ -n "$POS2" ] && die "trace takes one <repo>"
	set_repo "$POS1"
	load_map
	collect_defs
	printf 'id\tstate\tdefined_at\ttest_files\tmilestones\n'
	if [ -n "$DEFS" ]; then matrix; fi
}

cmd_index() {
	[ -n "$POS2" ] && die "index takes one <repo>"
	set_repo "$POS1"
	printf 'path\tstatus\tversion\towner\trequirements\n'
	kit_docs | while IFS= read -r ix_f; do
		printf '%s\t%s\t%s\t%s\t%s\n' "$ix_f" "$(fm_get "$REPO/$ix_f" status)" "$(fm_get "$REPO/$ix_f" version)" \
			"$(fm_get "$REPO/$ix_f" owner)" "$(fm_get "$REPO/$ix_f" requirements)"
	done
}

cmd_rotate() {
	[ -n "$POS2" ] && die "rotate takes one <repo>"
	set_repo "$POS1"
	[ -n "$VERSION" ] || die "rotate needs --version VERSION"
	case $VERSION in
	*[!0-9A-Za-z.+_-]* | [!0-9A-Za-z]*) die "version may only use letters, digits and . + _ -" ;;
	esac
	ro_changes=$REPO/CHANGES.md
	[ -f "$ro_changes" ] || refuse "no CHANGES.md in $REPO"
	ro_rel=docs/changes/$VERSION.md
	if [ -e "$REPO/$ro_rel" ] || [ -h "$REPO/$ro_rel" ]; then refuse "$ro_rel already exists"; fi
	grep -E -i -q '^## +unreleased' "$ro_changes" || refuse "CHANGES.md has no '## Unreleased' section"

	ro_body=$(awk 'tolower($0) ~ /^## +unreleased/ { s = 1; next } /^## / { s = 0 } s' "$ro_changes")
	ro_real=$(printf '%s\n' "$ro_body" | sed -e 's/<!--.*-->//g' -e '/^[[:space:]]*$/d' -e '/^[[:space:]]*-[[:space:]]*$/d')
	[ -n "$ro_real" ] || refuse "nothing under '## Unreleased' to release"

	load_map
	collect_defs
	ro_ids=$(printf '%s\n' "$ro_body" | awk -v root="" "$TOK_AWK" | cut -f1 | sort -u | while IFS= read -r ro_id; do
		if printf '%s\n' "$DEFS" | cut -f1 | grep -F -x -q "$ro_id"; then printf '%s\n' "$ro_id"; fi
	done | tr '\n' ' ' | sed 's/ $//; s/ /, /g')
	ro_owner=$(fm_get "$ro_changes" owner)
	[ -n "$ro_owner" ] || ro_owner='{{owner}}'

	mkdir -p -- "$REPO/docs/changes" || refuse "cannot create docs/changes"
	inside_repo "$(resolve_dir "$REPO/docs/changes")" || refuse "docs/changes resolves outside the repo"
	{
		printf '%s\n' '---' 'status: released' "version: $VERSION" "owner: $ro_owner" "requirements: [$ro_ids]" '---' ''
		printf '# %s\n\nReleased %s.\n\n' "$VERSION" "$TODAY"
		printf '%s\n' "$ro_body" | sed -e '/./,$!d'
	} >"$REPO/$ro_rel" || refuse "cannot write $ro_rel"

	ro_scratch_new=0
	if [ ! -d "$REPO/.scratch" ]; then ro_scratch_new=1; fi
	mkdir -p -- "$REPO/.scratch" || refuse "cannot create .scratch"
	inside_repo "$(resolve_dir "$REPO/.scratch")" || refuse ".scratch resolves outside the repo"
	ro_tmp=$REPO/.scratch/CHANGES.md.$$
	if ! awk -v ver="$VERSION" -v file="$ro_rel" '
		function row() { return "| " ver " | [" file "](" file ") |" }
		tolower($0) ~ /^## +unreleased/ { print; print ""; skip = 1; next }
		skip && /^## / { skip = 0 }
		skip { next }
		tolower($0) ~ /^\| *version *\|/ { print; hdr = 1; next }
		hdr && /^\| *:?-/ { print; print row(); hdr = 0; done = 1; next }
		{ hdr = 0; print }
		END {
			if (!done) { print ""; print "## Released"; print ""; print "| Version | Notes |"; print "| --- | --- |"; print row() }
		}' "$ro_changes" >"$ro_tmp"; then
		guarded_rm "$ro_tmp"
		refuse "cannot rewrite CHANGES.md"
	fi
	mv -- "$ro_tmp" "$ro_changes" || {
		guarded_rm "$ro_tmp"
		refuse "cannot replace CHANGES.md"
	}
	if [ "$ro_scratch_new" = 1 ]; then rmdir -- "$REPO/.scratch" 2>/dev/null || :; fi
	printf 'rotate: Unreleased -> %s; CHANGES.md now lists %s under Released.\n' "$ro_rel" "$VERSION"
}

cmd_guard_check() {
	[ -n "$POS2" ] || die "guard-check needs <repo> <path>"
	set_repo "$POS1"
	if guard_path "$POS2"; then
		printf 'allow %s\n' "$GP_ABS"
		exit 0
	fi
	printf 'refuse %s\n' "$POS2"
	exit 1
}

main() {
	[ $# -gt 0 ] || {
		usage >&2
		exit 2
	}
	mn_cmd=$1
	shift
	case $mn_cmd in
	-h | --help | help)
		usage
		exit 0
		;;
	--version)
		printf '%s\n' "$KIT_VERSION"
		exit 0
		;;
	esac
	parse_args "$@"
	case $mn_cmd in
	scaffold) cmd_scaffold ;;
	audit) cmd_audit ;;
	trace) cmd_trace ;;
	index) cmd_index ;;
	rotate) cmd_rotate ;;
	guard-check) cmd_guard_check ;;
	*) die "unknown command: $mn_cmd (run with --help)" ;;
	esac
}

main "$@"
