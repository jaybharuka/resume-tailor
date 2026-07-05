import re

# Matches word-like chunks, keeping symbols that are part of common technology
# names attached to their letters (e.g. "C++", "C#", "Node.js") so a bare "C"
# or "Node" never matches as a substring of a different, more specific name.
_SKILL_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:\.[A-Za-z0-9+#]+)*")


def tokenize_for_skill_matching(text: str) -> list[str]:
    """Tokenize prose into word-like chunks for skill-matching purposes (see
    _SKILL_TOKEN_PATTERN)."""
    return _SKILL_TOKEN_PATTERN.findall(text)


def skill_mentioned_in_token_groups(skill: str, token_groups: list[list[str]]) -> bool:
    """True if `skill` is genuinely mentioned in `token_groups` - either as a
    standalone single-word technology name, or (for multi-word skills like
    "React Native") as the exact word sequence. Each group is the tokens of one
    bullet, kept separate so a skill at the end of one bullet is never treated
    as adjacent to the first (often-capitalized, sentence-initial) word of the
    next bullet.

    A single-word skill is NOT considered mentioned merely because it's the
    first word of an adjacent, differently-named two-word compound within the
    SAME bullet (e.g. "React" inside "React Native") unless it also appears on
    its own elsewhere - this is what prevents "Java" from matching inside
    "JavaScript" or "React" from matching inside "React Native" while still
    allowing genuine standalone mentions."""
    skill_tokens = skill.split()
    if not skill_tokens:
        return False

    if len(skill_tokens) == 1:
        skill_lower = skill_tokens[0].lower()
        for tokens in token_groups:
            for i, token in enumerate(tokens):
                if token.lower() != skill_lower:
                    continue
                next_token = tokens[i + 1] if i + 1 < len(tokens) else None
                if next_token is not None and next_token[:1].isupper():
                    # Immediately followed by another capitalized word within
                    # the SAME bullet - this occurrence could be the first
                    # half of a distinct two-word compound (e.g. "React" +
                    # "Native"); don't count it as a standalone mention, but
                    # keep looking for another occurrence.
                    continue
                return True
        return False

    skill_lower_tokens = [t.lower() for t in skill_tokens]
    n = len(skill_lower_tokens)
    for tokens in token_groups:
        for i in range(len(tokens) - n + 1):
            if [t.lower() for t in tokens[i:i + n]] == skill_lower_tokens:
                return True
    return False


def collect_earned_skills(resume_json: dict, matching_skills: list[str]) -> tuple[set[str], list[list[str]]]:
    """Return (earned_skill_strings, bullet_token_groups): the whitelist a
    code-level skills guard checks candidate skill mentions against, and the
    tokenized bullet prose (one token list per bullet) a skill can also be
    "earned" by appearing in (e.g. "Django" mentioned in a sentence but never
    listed in a dedicated skills/technologies field)."""
    earned = set(resume_json.get("skills", []))
    earned.update(matching_skills)
    bullet_texts = [
        bullet
        for entry in resume_json.get("work_experience", [])
        for bullet in entry.get("bullets", [])
    ]
    for project in resume_json.get("projects", []):
        earned.update(project.get("technologies", []))
        bullet_texts.extend(project.get("bullets", []))
    bullet_token_groups = [tokenize_for_skill_matching(bullet) for bullet in bullet_texts]
    return earned, bullet_token_groups
