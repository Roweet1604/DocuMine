"""Owner: P2. Fixed sections and instructions for each document type, used by generate.py.

Each template has a purpose and an ordered list of (heading, instructions).
The user never writes a prompt: these instructions are the prompt. Keys must match generate.DOC_TYPES.
"""

NOT_MENTIONED = "Not mentioned in the sources"

TEMPLATES = {
    "Meeting Minutes": {
        "purpose": "Formal minutes of a team meeting or chat discussion.",
        "sections": [
            ("Meeting Details",
             "Date, time, attendees (names exactly as written) and purpose of the meeting, as a short bulleted list."),
            ("Discussion Summary",
             "A few paragraphs or bullets summarising what was discussed, topic by topic, in formal English."),
            ("Decisions",
             "Bulleted list of decisions that were clearly agreed. Do not list proposals or open questions as decisions."),
            ("Action Items",
             f"A Markdown table with the columns Task | Owner | Due Date, one row per action item. "
             f"Write '{NOT_MENTIONED}' in any cell whose value is not stated in the sources."),
            ("Open Questions",
             "Bulleted list of questions or issues that were raised but not resolved."),
        ],
    },
    "Technical Design Document": {
        "purpose": "A technical design document describing a system for engineers and reviewers.",
        "sections": [
            ("Overview", "What the system is, who it is for and the problem it solves."),
            ("Goals and Scope", "Goals of the current version, and what is explicitly out of scope."),
            ("Architecture", "Main components and how data flows between them. Use a bulleted list."),
            ("Data Model", "Tables, fields, retention and storage details."),
            ("Interfaces and APIs", "Endpoints, message formats, external services and integrations."),
            ("Security", "Authentication, authorisation, secrets and data protection."),
            ("Key Decisions", "Bulleted list of design decisions and, if stated, the reason for each."),
            ("Risks and Open Questions", "Known risks, limitations, unresolved questions and contradictions."),
        ],
    },
    "Code Documentation": {
        "purpose": "Developer documentation for a code base, written for a new team member.",
        "sections": [
            ("Overview", "What the code does and its main responsibilities."),
            ("Setup and Usage", "How to install, configure and run the code, and how to run its tests."),
            ("Module Reference",
             "For each file or module: its purpose, then its main functions and classes with a one-line "
             "description each. Use a sub-heading (###) per module and format names as `code`."),
            ("Configuration", "Settings, constants and environment values with their meaning and default values."),
            ("Testing", "What the tests cover."),
            ("Known Limitations", "Limitations, TODOs and missing features visible in the sources."),
        ],
    },
    "Project Report": {
        "purpose": "A formal project status report for a supervisor or stakeholders.",
        "sections": [
            ("Executive Summary", "One short paragraph: what the project is and its current status."),
            ("Objectives", "The goals of the project."),
            ("Progress and Achievements", "Work completed so far, with dates where stated."),
            ("Issues and Incidents", "Problems and incidents, their impact, root cause and resolution."),
            ("Decisions", "Bulleted list of important decisions made."),
            ("Next Steps",
             f"A Markdown table with the columns Task | Owner | Due Date. "
             f"Write '{NOT_MENTIONED}' in any cell whose value is not stated in the sources."),
            ("Risks", "Risks, open questions and contradictions between sources."),
        ],
    },
}
