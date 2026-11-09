"""Pydantic output schemas used by OfficePilot agents."""

from pydantic import BaseModel, Field


class MeetingContext(BaseModel):
    """Validated meeting context aggregated from office research."""

    client: str = Field(
        description="The client name supported by the provided sources."
    )

    important_communication: list[str] = Field(
        description="Important email communication, requests, and dates."
    )

    client_concerns: list[str] = Field(
        description="Client concerns explicitly supported by the sources."
    )

    relevant_documents: list[str] = Field(
        description="Names or descriptions of relevant retrieved documents."
    )

    important_document_facts: list[str] = Field(
        description="Important facts extracted from relevant documents."
    )

    meeting_title: str = Field(
        description=(
            "Meeting title, or 'Not found in available sources' "
            "if no title is available."
        )
    )

    meeting_date: str = Field(
        description=(
            "Meeting date, or 'Not found in available sources' "
            "if no date is available."
        )
    )

    meeting_time: str = Field(
        description=(
            "Meeting time, or 'Not found in available sources' "
            "if no time is available."
        )
    )

    participants: list[str] = Field(
        description=(
            "Names of actual meeting participants explicitly supported "
            "by the sources. Never put missing-information messages or "
            "placeholder text in this list. Use an empty list when no "
            "participant names are available."
        )
    )

    missing_information: list[str] = Field(
        description=(
            "Information required for preparation that could not be "
            "verified from the supplied sources."
        )
    )
