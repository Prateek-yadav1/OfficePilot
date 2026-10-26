from crewai import Task

from .researcher import researcher_agent
from .analyst import analyst_agent
from .reviewer import reviewer_agent


research_task = Task(
    description="""
Research the following client and missing information.

Client:
{client}

Missing information:
{missing_information}

Identify useful information relevant to the client's upcoming
meeting.

Important rules:

- Do not invent facts.
- Focus only on the requested missing information.
- Clearly identify information that could not be verified.
- Produce concise research findings.
""",

    expected_output="""
A concise research report containing:

1. Client
2. Research topic
3. Verified findings
4. Information that could not be verified
5. Relevant observations
""",

    agent=researcher_agent,
)


analysis_task = Task(
    description="""
Analyze the research report produced by the Research Specialist.

Determine:

1. Important facts
2. Business implications
3. Potential concerns
4. Meeting-relevant insights
5. Any information that remains uncertain

Do not invent information.

Clearly distinguish facts from analysis.
""",

    expected_output="""
A structured analysis containing:

1. Important facts
2. Business implications
3. Potential concerns
4. Meeting insights
5. Remaining uncertainties
""",

    agent=analyst_agent,
)


review_task = Task(
    description="""
Review the complete research and analysis.

Check:

1. Accuracy
2. Relevance
3. Completeness
4. Unsupported claims
5. Missing information
6. Whether facts and assumptions are clearly distinguished

If problems are found, clearly identify them.

Produce the final verified research report.
""",

    expected_output="""
A final quality-reviewed research report containing:

1. Verified findings
2. Important analysis
3. Potential concerns
4. Meeting-relevant insights
5. Remaining uncertainties
6. Quality observations
""",

    agent=reviewer_agent,
)