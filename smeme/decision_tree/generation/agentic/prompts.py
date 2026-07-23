"""LLM prompts for agentic DecisionTree generation.

These are skeleton prompts - iterate based on real outputs during development.
See docs/AGENTIC_DECISION_TREE_GENERATION_PLAN.md for design rationale.

Prompt Design Principles:
1. Clear role and context for the LLM
2. Explicit output format requirements
3. Domain-specific guidance where relevant
4. Examples to anchor expectations

Conclusion Node Support:
- Research phase: Extract possible conclusions/outcomes
- Design phase: Reference predefined conclusions
- Build phase: Generate conclusion nodes with proper structure
"""

# =============================================================================
# Phase 1: Research Context (combined Tavily + LLM summarization)
# =============================================================================

# Soft cap — model should include fewer factors when the topic is narrow (no padding).
RESEARCH_FACTOR_CAP = 30

_RESEARCH_TASK_INTRO = f"""Identify as many decision-critical factors as the topic requires, up to **{RESEARCH_FACTOR_CAP}**. Include only factors that would change the recommendation, create branching logic, or carry legal/safety/high-stakes implications. Prefer fewer strong factors over padding to reach the cap."""

_RESEARCH_FACTOR_FIELDS = """
**Relevance to Decision-Making**:
- WHY this factor matters and HOW different values change the recommendation (2–4 sentences)
- Note thresholds or conditions where the factor becomes critical vs. negligible when relevant

**Typical Values/States**:
- Discrete options, ranges, or categories; note jurisdictional variations when relevant (brief)

**Interdependencies**:
- Key interactions, conditional logic, or combinatorial effects (Factor A + Factor B changes outcomes); or state "Operates independently." (1–2 sentences)

**Question Implications**:
- What questions would determine this factor's value for the decision tree? (1–2 sentences)"""

_RESEARCH_FACTOR_OUTPUT_EXAMPLE = """
**Relevance to Decision-Making:**
[2–4 sentences on how this factor influences the advice]

**Typical Values/States:**
[Brief options, ranges, or categories]

**Interdependencies:**
[1–2 sentences, or "Operates independently."]

**Question Implications:**
[1–2 sentences on questions needed to assess this factor]"""

_RESEARCH_QUALITY_CHECK = f"""
## Quality Check
Before submitting, verify:
- [ ] At most {RESEARCH_FACTOR_CAP} factors — use fewer when the topic is narrow; do not pad
- [ ] Each factor explains its IMPACT on advice, with Typical Values and Question Implications
- [ ] Interdependencies and combinatorial effects noted where they matter
- [ ] Domain-specific terminology is used precisely
- [ ] Factors are granular enough to inform specific questions"""

# Change this to make a list of factors with an explanation of their relevance to the reasoning process that leads to decisive advice.

ANALYZE_RESEARCH_FACTORS_PROMPT = f"""You are a Subject Matter Expert analyzing research to identify decision-critical factors.

## Context
**User's Goal**: {{user_prompt}}
{{research_corpus_section}}
**Research Results**: {{search_snippets}}

## Your Task
{_RESEARCH_TASK_INTRO} Omit minor edge cases unless the research highlights them as decisive.

## Critical Requirements

### 1. Coverage (focused, not exhaustive)
- Extract the highest-impact factors mentioned or clearly implied in the research
- Include factors that create branching logic (if X, then Y matters)
- Capture jurisdictional, temporal, and contextual variations when they change the advice
- Note source convergence briefly when multiple sources agree

### 2. Factor Structure
Each factor must include:
{_RESEARCH_FACTOR_FIELDS}

**Evidence Basis**:
- Cite web sources by title or domain; uploaded files as "Uploaded document (filename)"; pasted text only if present in User-Provided Reference (1 sentence)
- Note material disagreements between sources when they affect confidence in the factor

### 3. Analysis Standards

✅ **DO**:
- Analyze cause-and-effect relationships between factors and outcomes
- Explain nuanced variations (e.g., "thresholds at $X change the treatment")
- Identify when factors create entirely different advice pathways
- Note factors that require expert judgment vs. mechanical application
- Highlight factors with legal, safety, or high-stakes implications

❌ **DON'T**:
- Summarize what the sources say - analyze what the information MEANS for decision-making
- List factors without explaining their decision impact
- Ignore interactions between factors
- Provide general background information that doesn't affect the advice
- Pad the list to reach the factor cap

## Output Format

Use this structure:

---

### Factor 1: [Precise Factor Title]
{_RESEARCH_FACTOR_OUTPUT_EXAMPLE}

**Evidence Basis:**
[1 sentence citing sources; note disagreements if material]

---

### Factor 2: [Next Factor]
[Continue pattern...]

---

## Special Considerations Section

After all factors, include:

**Cross-Cutting Patterns:**
[Describe overarching themes where multiple factors cluster or interact systematically]

**Critical Decision Thresholds:**
[Identify specific values/conditions where advice fundamentally changes]

**Knowledge Gaps:**
[Note areas where research was unclear or contradictory, affecting confidence in certain factors]

---
{_RESEARCH_QUALITY_CHECK}

Generate the factor analysis now.
"""


# =============================================================================
# Phase 1: Augmentation Factor Extraction
# =============================================================================

EXTRACT_AUGMENTATION_FACTORS_PROMPT = """You are a Subject Matter Expert extracting NEW factors from augmentation research.

## Context

**User's Goal**: {user_prompt}

**Existing Factors Already Identified**:
{existing_factors}

**New Augmentation Search Results**: {augmentation_snippets}

## Your Task

Analyze the augmentation search results and extract ONLY NEW factors that were NOT already covered in the existing factors above.

## Critical Requirements

### 1. Avoid Duplication
- Do NOT repeat factors already in the existing analysis
- Only extract factors that add genuinely new decision-making dimensions
- If an augmentation result simply confirms or elaborates on an existing factor, DO NOT extract it again

### 2. Factor Structure (Same as Initial Analysis)
Each NEW factor must include:

**[Factor Title]** (concise, specific noun phrase)

**Relevance to Decision-Making**:
- WHY this factor matters for determining the advice
- HOW different values/states of this factor change the recommendation
- What conditions or thresholds make this factor critical

**Typical Values/States**:
- List discrete options, ranges, or categories
- Include jurisdictional variations if relevant

**Interdependencies**:
- Which existing factors does this interact with?
- What conditional logic applies?

**Question Implications**:
- What specific questions would need to be asked to determine this factor's value?

### 3. Quality Standards
- Be selective - not every piece of information is a factor
- Factors must be decision-critical (they change what advice to give)
- Use domain-specific terminology precisely
- Maintain consistency with existing factor format

### 4. Output Format

If NO new factors are found:
**No new factors identified** - augmentation results confirm and elaborate on existing factors.

If new factors ARE found:
List them using the SAME format as existing factors, continuing the numbering sequence.

---

Extract NEW factors now. Be rigorous about avoiding duplication.
"""

# =============================================================================
# Phase 1.5: Conclusion Extraction (separate focused prompt)
# =============================================================================

EXTRACT_CONCLUSIONS_PROMPT = """You are a Subject Matter Expert identifying the possible outcomes/conclusions for a decision-making questionnaire.

## Context

**User's Goal**: {user_prompt}

**Approved Factor Analysis**: {research_context_edited}

## Your Task

Based on the factors identified, determine the **possible conclusions** (2-6 distinct outcomes) that this questionnaire could reach. Each conclusion represents a different recommendation based on factor combinations.

## Requirements

1. **Mutually Exclusive**: Each conclusion represents a distinct outcome — only ONE applies per user
2. **Exhaustive**: The conclusions should cover all reasonable factor combinations
3. **Actionable**: Each conclusion leads to specific recommendations
4. **Discriminable**: The factors should be sufficient to determine which conclusion applies

## Output Format

For each conclusion, provide:

---

**CONCLUSION_[N]: [Short Title]**

**Summary**: [One paragraph explaining this outcome and what it means for the user]

**When this applies**: [What factor combinations lead to this conclusion]

**Key recommendations**:
1. [First actionable step]
2. [Second actionable step]
3. [Third actionable step (optional)]

**Severity**: [info | warning | critical]
- info: Standard recommendation, no urgency
- warning: Important considerations, some urgency
- critical: Urgent action required, significant consequences

---

## Example

**CONCLUSION_1: Form an LLC**

**Summary**: Based on your situation, forming a Limited Liability Company (LLC) provides the best balance of liability protection, tax flexibility, and operational simplicity.

**When this applies**: Small business with 1-5 owners, moderate revenue, wants liability protection, doesn't need outside investors

**Key recommendations**:
1. File articles of organization with your state
2. Create an operating agreement defining member responsibilities
3. Obtain an EIN from the IRS for tax purposes

**Severity**: info

---

Generate 2-6 conclusions that cover the factor space identified in the research.

**Output constraints (strict):**
- Output ONLY conclusion blocks in the format above — no preamble, summary paragraph, or closing remarks.
- Do NOT offer follow-up work (for example, do not offer to build a decision tree or flowchart; that happens in a later product step).
"""

# Used when Tavily search fails (degraded mode)
SUMMARIZE_RESEARCH_NO_SEARCH_PROMPT = f"""You are a Subject Matter Expert analyzing decision-critical factors.

## Context
**User's Goal**: {{user_prompt}}
{{research_corpus_section}}
**Important Note**: {{source_note}}

## Your Task
{_RESEARCH_TASK_INTRO} Use the SAME factor structure as when web research results are available. Prioritize branching logic and high-stakes dimensions. Omit minor edge cases unless domain knowledge marks them as decisive.

## Critical Requirements

### 1. Coverage (focused, not exhaustive)
- Draw on your knowledge for the highest-impact factors that could affect the recommendation
- Include factors that create branching logic (if X, then Y matters)
- Capture jurisdictional, temporal, and contextual variations when they change the advice
- Flag uncertainty where training knowledge may be incomplete or outdated

### 2. Factor Structure
Each factor must include:

**Factor [N]: [Factor Title]** (concise, specific noun phrase)
{_RESEARCH_FACTOR_FIELDS}

**Evidence Basis**:
- Cite User-Provided Reference when applicable; otherwise note reliance on domain knowledge (1 sentence)

### 3. Numbering
Number factors sequentially: Factor 1, Factor 2, Factor 3, etc.

## Output Format

Use this structure:

---

### Factor 1: [Precise Factor Title]
{_RESEARCH_FACTOR_OUTPUT_EXAMPLE}

**Evidence Basis:**
[1 sentence — corpus citation or domain-knowledge note]

---

### Factor 2: [Next Factor]
[Continue pattern...]

---

## Special Considerations Section

After all factors, include:

**Cross-Cutting Patterns:**
[Describe overarching themes where multiple factors cluster or interact systematically]

**Critical Decision Thresholds:**
[Identify specific values/conditions where advice fundamentally changes]

**Knowledge Gaps:**
⚠️ **Note areas where information may be outdated or where web research would be valuable**

---
{_RESEARCH_QUALITY_CHECK}
- [ ] Uncertainty flagged where web research would help

Generate the factor analysis now.
"""

# =============================================================================
# Phase 2: Design Questionnaire (Freeform Markdown)
# =============================================================================

DESIGN_DECISION_TREE_PROMPT = """You are a Subject Matter Expert designing a decision-tree questionnaire to efficiently gather information and lead users to one of several predefined conclusions.

## Context

**User's Goal**: {user_prompt}

**Approved Factor Analysis with Conclusions**: {research_context_edited}

## Allowed Conclusions (closed list)

{allowed_conclusions}

## Your Task

Design an **efficient branching decision tree** — not a linear checklist. Users on different paths should skip irrelevant questions and reach conclusions as early as dispositive answers allow.

The server will validate structure and branching quality. Attempt to satisfy the constraints below; invalid designs will be rejected.

## Product Constraints

This product supports **only radio questions** (mutually exclusive options).

- Do not use checkbox, text, number, date, multi-select, or arithmetic conditions.
- Every question is **Required: yes**. If the user may not know, add an explicit option such as "Unsure" or "Not enough information".
- Each option must have **exactly one explicit branch** in the Branching section. Do **not** use Default branches in your design output (the build step emits explicit per-option edges; server-side defaults may exist for legacy traversal but must never target a conclusion).
- Required means the user must select an option — including explicit uncertainty options when they may not know.
- Only **conclusions** are terminal. **No question may be terminal** — every question must have a Branching section with outgoing routes.

## CRITICAL: Conclusion-Driven Design

1. **Every path must reach a conclusion** — no dead-end questions
2. **Questions discriminate among conclusions** — especially early gates (Q1–Q3)
3. **Multiple paths may reach the same conclusion**
4. **Every allowed conclusion must be reachable** from at least one path
5. **Conclusions are reached by specific answers** — never as implicit fallbacks

## Design Principles

### 1. Factor Coverage (on relevant paths only)
- Every factor must be **tested on at least one reachable path**, OR **explicitly skipped** because an earlier answer makes it irrelevant (state which branch skips it in "Why we ask")
- Do not ask every factor on every path — that creates bloated linear funnels
- Do not add questions about factors not in the approved research analysis

### 2. Question Flow Strategy
- **Start with dispositive filters** — answers that eliminate entire subtrees or reach a conclusion immediately
- **Progress general → specific** only on paths that still need discrimination
- **Group related factors** on the same path segment
- **End paths at conclusions** as soon as the outcome is determined

### 3. Branching Logic Efficiency
- **Skip irrelevant blocks**: If Factor X does not apply, do not route through Factor X questions
- **No redundant paths** — do not ask the same decision twice
- **Typical users should answer fewer than half of all questions** when branching is working

### 4. Anti-Funnel Rule and Node Kinds (critical)

**Routing questions** (default): answers should materially change the remaining path — different next questions, skipped factor groups, or terminal conclusions.

**collect_only questions** (rare exception): use only when every option must go to the same next node because the answer is needed later for explanation, evidence quality, or wording — not for routing. Mark with `- **Node kind**: collect_only` and explain in "Why we ask" why routing is deferred.

Do **not** route all options to the same next question on a **routing** question.

**Forbidden pattern:** Q1 options "Yes", "No", "Unsure" all → Q2 except one "No" → conclusion.

**Required for Q1–Q3 routing questions:** At least **two materially different routes** when acting as dispositive gates. A single early intake/classifier question may route to one next node if a **later** question (Q2 or Q3) performs the real split.

### 5. Unsure / Unknown Policy

"Unsure" must **not** automatically mean "continue to the next sequential question."

Choose deliberately:
- Route to a **conservative conclusion** when uncertainty should not proceed, OR
- Route to a **diagnostic follow-up** that moves **forward** (higher Q number or a conclusion) and resolves or accepts uncertainty, OR
- Route the same as a named non-unsure option when equivalent — say so in "Why we ask"

**Follow-up / refinement questions:** When Q5 refines or follows from Q4 (same factor block), Unsure on the **child** question must **never** route back to the **parent** — the user already answered the parent. Route forward to the next question in the block, or to a conservative conclusion.

**Ping-pong anti-pattern (forbidden):**
```
❌ Q4 Unsure → Q5, Q5 Unsure → Q4   (creates q4 ↔ q5 cycle; traps the user)
✅ Q4 Unsure → Q5, Q5 Unsure → Q6 or CONCLUSION_N   (forward-only)
```

## Question Format

For each question, use this exact structure:
```
#### Q{{n}}: {{Clear, specific question text}}
- **Type**: radio
- **Node kind**: routing | collect_only (default: routing)
- **Options**: {{Option1, Option2, Option3}} (2–7 mutually exclusive labels)
- **Required**: yes
- **Help text**: {{Brief guidance on how to answer accurately}}
- **Maps to factor**: {{Factor name from research analysis}}
- **Why we ask**: {{Decision impact; note if this factor is skipped on other branches}}
- **Branching**:
  - If "{{exact option text}}" → Q{{m}} OR {{allowed CONCLUSION_ID}}
  - If "{{exact option text}}" → Q{{m}} OR {{allowed CONCLUSION_ID}}
  - (one line per option — no Default line)
```

Branch targets must use only Q1, Q2, … or IDs from the **Allowed Conclusions** list above.

## Critical Rules

✅ **DO**:
- Q1 is the entry point (nothing branches TO Q1)
- Every question except Q1 is reachable from Q1
- Every path ends at an allowed CONCLUSION_N
- Branching conditions use **exact** option text
- Give **every option** an explicit branch

❌ **DON'T**:
- Create orphaned questions or unreachable conclusions
- Create loops (Q5 → Q3 → Q5) or backward edges between questions (Q5 → Q4)
- Route Unsure on a follow-up question back to its parent question
- Use Default branches
- Branch to "End" or "Advice" — use CONCLUSION_N only
- Create, rename, merge, or omit conclusions from the allowed list
- Use pseudo-branching on routing questions: multiple options with different labels all targeting the same next node (use collect_only if intentional)

## Quality Checklist (generation objectives)

**Factor coverage:**
- [ ] Each factor appears on at least one relevant path OR is explicitly skipped on other paths

**Conclusion coverage:**
- [ ] Every allowed conclusion is reachable
- [ ] Early questions (Q1–Q3) discriminate routes

**Flow efficiency:**
- [ ] High-impact filters appear early
- [ ] No question sends all options to the same target (anti-funnel)
- [ ] Unsure options have deliberate routes, not automatic "next question"

**Structure:**
- [ ] All questions reachable from Q1; all paths end at conclusions; no loops or backward edges (Qx → Qy where y < x)
- [ ] Unsure on follow-up questions routes forward or to a conclusion, never back to the parent
- [ ] Every question has a complete Branching section

## Example (illustrative — match your domain)
```
#### Q1: Have you held this cryptocurrency for more than one year?
- **Type**: radio
- **Options**: Yes - held over 1 year, No - held 1 year or less, Unsure of exact dates
- **Required**: yes
- **Help text**: Check acquisition and sale dates for your largest transaction.
- **Maps to factor**: Holding Period
- **Why we ask**: Short-term vs long-term treatment diverges completely; unsure dates need a separate path.
- **Branching**:
  - If "Yes - held over 1 year" → Q2
  - If "No - held 1 year or less" → Q4
  - If "Unsure of exact dates" → Q5

#### Q2: What was your total taxable income this year?
- **Type**: radio
- **Options**: Under $44,625, $44,625 - $492,300, Over $492,300, Not enough information yet
- **Required**: yes
- **Help text**: Use AGI from your return or a reasonable estimate.
- **Maps to factor**: Income Tax Bracket
- **Why we ask**: Bracket determines long-term capital gains rate on this path only.
- **Branching**:
  - If "Under $44,625" → CONCLUSION_1
  - If "$44,625 - $492,300" → Q3
  - If "Over $492,300" → Q3
  - If "Not enough information yet" → CONCLUSION_4
```

## Output Instructions

1. Number questions sequentially: Q1, Q2, Q3, …
2. Include all required fields for every question
3. Map factors in "Maps to factor" (on relevant paths)
4. Complete explicit Branching for **every** option on **every** question
5. Use branching so many users never see every question — aim for roughly 5–15 total questions with multiple early exits

Design the complete questionnaire now.
"""

# =============================================================================
# Phase 3: Build DTGraph from Markdown
# =============================================================================

BUILD_GRAPH_PROMPT = """Convert the markdown questionnaire into a DTGraph JSON structure.

## Input Markdown
{decision_tree_design_edited}

## Output Structure

Generate a JSON object with: **nodes**, **edges**, and **metadata**.

### Node Types

There are TWO types of nodes:
1. **Question nodes**: Gather information, have outgoing edges
2. **Conclusion nodes**: Terminal outcomes, NO outgoing edges

Entry point is determined by no incoming edges (typically q1).
Conclusions are terminal - they have no outgoing edges.

### Node Structure (Flattened)
```json
{{
  "id": "q1",  // Use lowercase: q1, q2, q3, etc. for questions; conclusion_1, etc. for conclusions
  "type": "question",  // or "conclusion"

  // For question nodes:
  "text": "Question text from markdown",
  "question_type": "radio",  // always radio (exclusive finite choice)
  "options": ["Option1", "Option2"],  // non-empty; each edge condition must match one label
  "required": true,  // true | false
  "help_text": "Help text from markdown",

  // For conclusion nodes:
  "title": "Short title for the conclusion",
  "summary": "Explanation of what this conclusion means",
  "recommendations": ["Step 1", "Step 2", "Step 3"],
  "severity": "info"  // "info" | "warning" | "critical"
}}
```

**Note**: Use only the fields relevant to the node type. For questions, use text/question_type/options/required/help_text (question_type must be ``radio`` with a non-empty ``options`` list). For conclusions, use title/summary/recommendations/severity.

### Edges Array

Each branching rule becomes one or more edges connecting nodes:
```json
{{
  "source": "q1",      // Source node ID (always a question)
  "target": "q2",      // Target node ID (question or conclusion)
  "condition": "Yes"   // Exact option text, or null for default/unconditional
}}
```

**CRITICAL Edge Rules**:
- Edges can go from questions to questions OR from questions to conclusions
- Conclusion nodes have NO outgoing edges (they are terminal)
- **Edges to conclusions MUST have a condition** (no null/default edges to conclusions)
- Default edges (condition: null) can only target questions, not conclusions
- The first question (q1) should have no incoming edges

### Metadata Object (Required)
```json
{{
  "title": "Short descriptive title",
  "description": "One-sentence description of purpose",
  "category": null,  // Optional category
  "estimated_time": null,  // Minutes (optional)
  "version": "1.0.0",
  "tags": []  // Optional tags
}}
```

## Condition Parsing Rules

### 1. Single Option to Question
Markdown: `If "Yes" → Q5`
```json
{{"source": "q1", "target": "q5", "condition": "Yes"}}
```

### 2. Single Option to Conclusion
Markdown: `If "Yes" → CONCLUSION_1`
```json
{{"source": "q1", "target": "conclusion_1", "condition": "Yes"}}
```
**Note**: Edge to conclusion MUST have a condition (not null)

### 3. Multiple Options (OR logic)
Markdown: `If "Option A" or "Option B" → Q5`

Create **two separate edges**:
```json
{{"source": "q1", "target": "q5", "condition": "Option A"}}
{{"source": "q1", "target": "q5", "condition": "Option B"}}
```

### 4. Default/Fallback (Questions Only!)
Markdown: `Default → Q6`
```json
{{"source": "q1", "target": "q6", "condition": null}}
```
**CRITICAL**: Default edges can ONLY go to questions, NEVER to conclusions.

### 5. Conclusion References in Markdown
Convert CONCLUSION_N references to lowercase node IDs:
- `CONCLUSION_1` → `"conclusion_1"`
- `CONCLUSION_2` → `"conclusion_2"`
- `CONCLUSION_LLC` → `"conclusion_llc"`

## Required Graph Structure

1. **Entry point**: q1 has no incoming edges (is the starting question)
2. **Conclusion nodes**: Have no outgoing edges (terminal endpoints)
3. **Every path leads to a conclusion**: Question paths must end at conclusions
4. **At least 2 conclusions**: Minimum for meaningful discrimination
5. **Connectivity**: Every node must be reachable from q1
6. **Valid targets**: All edge targets must reference existing node IDs
7. **Conditional edges to conclusions**: No default edges to conclusions
8. **Acyclic question flow (DAG)**: No directed cycles among questions. Do not emit an edge from `qx` to `qy` when `y < x` (no backward edges). Unsure on a follow-up question must not target an earlier question the user already passed.

## Example Conversion

### Input Markdown:
```
#### Q1: Are you employed?
- **Type**: radio
- **Options**: Yes, No
- **Required**: yes
- **Help text**: Select your current status.
- **Branching**:
  - If "Yes" → Q2
  - If "No" → CONCLUSION_2

#### Q2: What is your annual income?
- **Type**: radio
- **Options**: Under $50,000, $50,000 or more
- **Required**: yes
- **Help text**: Select your income bracket.
- **Branching**:
  - If "Under $50,000" → CONCLUSION_1
  - If "$50,000 or more" → CONCLUSION_3

CONCLUSIONS (from research):
- CONCLUSION_1: Low Income Tax Strategy
- CONCLUSION_2: Unemployment Benefits Guide
- CONCLUSION_3: High Income Tax Strategy
```

### Output JSON:
```json
{{
  "nodes": [
    {{
      "id": "q1",
      "type": "question",
      "text": "Are you employed?",
      "question_type": "radio",
      "options": ["Yes", "No"],
      "required": true,
      "help_text": "Select your current status."
    }},
    {{
      "id": "q2",
      "type": "question",
      "text": "What is your annual income?",
      "question_type": "radio",
      "options": ["Under $50,000", "$50,000 or more"],
      "required": true,
      "help_text": "Select your income bracket."
    }},
    {{
      "id": "conclusion_1",
      "type": "conclusion",
      "title": "Low Income Tax Strategy",
      "summary": "Based on your employment and income, you may qualify for earned income tax credits and other benefits for lower-income workers.",
      "recommendations": [
        "Check eligibility for Earned Income Tax Credit (EITC)",
        "Consider contributing to a Roth IRA",
        "Review state-specific tax credits"
      ],
      "severity": "info"
    }},
    {{
      "id": "conclusion_2",
      "type": "conclusion",
      "title": "Unemployment Benefits Guide",
      "summary": "As you're currently not employed, here's guidance on unemployment benefits and job search resources.",
      "recommendations": [
        "File for unemployment benefits in your state",
        "Update your resume and LinkedIn profile",
        "Register with your state's job service"
      ],
      "severity": "warning"
    }},
    {{
      "id": "conclusion_3",
      "type": "conclusion",
      "title": "High Income Tax Strategy",
      "summary": "With higher income, you should focus on tax-advantaged retirement accounts and potential deductions.",
      "recommendations": [
        "Maximize 401(k) contributions",
        "Consider tax-loss harvesting",
        "Review itemized vs standard deduction"
      ],
      "severity": "info"
    }}
  ],
  "edges": [
    {{"source": "q1", "target": "q2", "condition": "Yes"}},
    {{"source": "q1", "target": "conclusion_2", "condition": "No"}},
    {{"source": "q2", "target": "conclusion_1", "condition": "Under $50,000"}},
    {{"source": "q2", "target": "conclusion_3", "condition": "$50,000 or more"}}
  ],
  "metadata": {{
    "title": "Employment and Tax Assessment",
    "description": "Determine optimal tax strategy based on employment status and income.",
    "category": null,
    "estimated_time": 2,
    "version": "1.0.0",
    "tags": ["tax", "employment"]
  }}
}}
```

**Note**:
- All edges to conclusions have conditions (not null)
- Conclusion nodes have `type: "conclusion"` and conclusion-specific data
- Every path from q1 reaches a conclusion

## Validation Checklist

Before generating, verify:
- [ ] Two node types: `"type": "question"` and `"type": "conclusion"`
- [ ] First question (q1) has no incoming edges
- [ ] Conclusion nodes have NO outgoing edges
- [ ] Every question ID in markdown becomes a question node
- [ ] Every CONCLUSION_N in markdown becomes a conclusion node
- [ ] At least 2 conclusion nodes exist
- [ ] **All edges to conclusions have conditions** (not null)
- [ ] Every path from q1 reaches a conclusion
- [ ] **No cycles or backward question edges** — no `qx → qy` where y < x; graph is a DAG ending at conclusions
- [ ] Condition text exactly matches a radio option label
- [ ] Every question has a non-empty `options` array
- [ ] Required field is boolean (true/false, not "yes"/"no")
- [ ] Metadata object with title is present
- [ ] Conclusion nodes have: title, summary, recommendations (list), severity

Generate the complete DTGraph JSON now.
"""
