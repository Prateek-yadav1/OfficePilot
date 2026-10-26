from backend.crewai_research.crew import research_crew


def main():

    print("\n" + "=" * 80)
    print("OFFICEPILOT - PHASE 6 CREWAI TEST")
    print("=" * 80)

    print("\nStarting CrewAI research crew...")

    result = research_crew.kickoff(
        inputs={
            "client": "ABC Technologies",
            "missing_information": (
                "deployment milestones and previous deployment concerns"
            ),
        }
    )

    print("\n" + "=" * 80)
    print("CREWAI RESEARCH RESULT")
    print("=" * 80)

    print(result)

    print("\n" + "=" * 80)
    print("CREWAI TEST COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    main()

    