const form = document.querySelector("#brief-form");
const requestInput = document.querySelector("#user-request");
const requestCount = document.querySelector("#request-count");
const submitButton = document.querySelector("#submit-button");
const formError = document.querySelector("#form-error");
const loadingPanel = document.querySelector("#loading-panel");
const loadingMessage = document.querySelector("#loading-message");
const progressEvents = document.querySelector("#progress-events");
const resultSection = document.querySelector("#result-section");
const resultStatus = document.querySelector("#result-status-label");
const resultTime = document.querySelector("#result-time");
const briefOutput = document.querySelector("#brief-output");
const copyButton = document.querySelector("#copy-button");
const briefingClient = document.querySelector("#briefing-client");
const clientMatchEvidence = document.querySelector("#client-match-evidence");
const briefingMeeting = document.querySelector("#briefing-meeting");
const missingInformation = document.querySelector("#missing-information");
const sourceReferences = document.querySelector("#source-references");
const integrationStatus = document.querySelector("#integration-status");
const partialResultsBlock = document.querySelector("#partial-results-block");
const partialResults = document.querySelector("#partial-results");
const executionWarning = document.querySelector("#execution-warning");
const executionIds = document.querySelector("#execution-ids");

const terminalStatuses = new Set([
  "completed",
  "completed_with_warnings",
  "failed",
]);

function updateCharacterCount() {
  requestCount.textContent = `${requestInput.value.length} / 4000`;
}

function appendParagraph(container, value) {
  const paragraph = document.createElement("p");
  paragraph.textContent = value;
  container.append(paragraph);
}

function renderBriefing(markdown) {
  briefOutput.replaceChildren();
  const lines = markdown.split(/\r?\n/);
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();

    if (!line) {
      index += 1;
      continue;
    }

    const heading = line.match(/^#{1,3}\s+(.+)$/);
    if (heading) {
      const element = document.createElement("h3");
      element.textContent = heading[1];
      briefOutput.append(element);
      index += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const list = document.createElement("ul");
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        const item = document.createElement("li");
        item.textContent = lines[index].trim().replace(/^[-*]\s+/, "");
        list.append(item);
        index += 1;
      }
      briefOutput.append(list);
      continue;
    }

    const paragraphLines = [];
    while (
      index < lines.length
      && lines[index].trim()
      && !/^#{1,3}\s+/.test(lines[index].trim())
      && !/^[-*]\s+/.test(lines[index].trim())
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    appendParagraph(briefOutput, paragraphLines.join(" "));
  }
}

function appendTextList(container, items, emptyText) {
  container.replaceChildren();
  const safeItems = Array.isArray(items) ? items : [];
  if (safeItems.length === 0) {
    const item = document.createElement("li");
    item.textContent = emptyText;
    container.append(item);
    return;
  }
  safeItems.forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    container.append(item);
  });
}

function renderMetadata(result, executionId) {
  const metadata = result.metadata || {};
  const meeting = metadata.meeting || {};
  const clientMatch = metadata.client_match || {};
  briefingClient.textContent = metadata.client || "Not identified";
  const evidence = Array.isArray(clientMatch.evidence)
    ? clientMatch.evidence
    : [];
  clientMatchEvidence.textContent = evidence.length
    ? `Client match (${clientMatch.confidence || "unverified"} confidence): ${evidence.join(", ").replaceAll("_", " ")}`
    : "";

  const details = [
    meeting.title,
    meeting.date,
    meeting.time,
    Array.isArray(meeting.participants) && meeting.participants.length
      ? `Participants: ${meeting.participants.join(", ")}`
      : "",
  ].filter((value) => value && value !== "Not found in available sources");
  briefingMeeting.textContent = details.length
    ? details.join(" · ")
    : "No meeting details were available from connected sources.";

  appendTextList(
    missingInformation,
    metadata.missing_information,
    "No additional missing information was reported.",
  );

  sourceReferences.replaceChildren();
  const references = Array.isArray(metadata.sources) ? metadata.sources : [];
  if (!references.length) {
    const item = document.createElement("li");
    item.textContent = "No source references were returned.";
    sourceReferences.append(item);
  } else {
    references.forEach((reference) => {
      const item = document.createElement("li");
      const label = `${reference.source}: ${reference.label || reference.id}`;
      let safeUrl = "";
      try {
        const parsed = new URL(reference.url);
        if (parsed.protocol === "https:") {
          safeUrl = parsed.href;
        }
      } catch {
        safeUrl = "";
      }
      if (safeUrl) {
        const link = document.createElement("a");
        link.href = safeUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = label;
        item.append(link);
      } else {
        item.textContent = label;
      }
      sourceReferences.append(item);
    });
  }

  integrationStatus.replaceChildren();
  const integrations = Array.isArray(metadata.integrations)
    ? metadata.integrations
    : [];
  if (!integrations.length) {
    const item = document.createElement("li");
    item.textContent = "Integration status is unavailable.";
    integrationStatus.append(item);
  } else {
    integrations.forEach((integration) => {
      const item = document.createElement("li");
      const status = String(integration.status || "unknown").replaceAll("_", " ");
      const backend = integration.backend
        ? ` (${integration.backend})`
        : "";
      const resultCount = Number.isInteger(integration.results)
        ? ` (${integration.results} result${integration.results === 1 ? "" : "s"})`
        : "";
      item.textContent = `${integration.name}${backend}: ${status}${resultCount}`;
      integrationStatus.append(item);
    });
  }

  partialResults.replaceChildren();
  if (result.incomplete === true) {
    const savedResults = metadata.partial_results || {};
    const availableResults = Object.entries(savedResults)
      .filter(([, value]) => typeof value === "string" && value.trim())
      .slice(0, 3);
    if (availableResults.length) {
      availableResults.forEach(([source, value]) => {
        const heading = document.createElement("h4");
        heading.textContent = source;
        const content = document.createElement("pre");
        content.className = "partial-result-content";
        content.textContent = value.slice(0, 8000);
        partialResults.append(heading, content);
      });
    } else {
      appendParagraph(
        partialResults,
        "No partial source content was saved before the workflow ended.",
      );
    }
    partialResultsBlock.hidden = false;
  } else {
    partialResultsBlock.hidden = true;
  }

  const warnings = Array.isArray(metadata.warnings) ? metadata.warnings : [];
  if (result.error) {
    warnings.push(result.error);
  }
  executionWarning.textContent = warnings.join(" ");
  executionWarning.hidden = warnings.length === 0;
  executionIds.textContent = [
    `Execution ${executionId}`,
    metadata.session_id ? `Session ${metadata.session_id}` : "",
  ].filter(Boolean).join(" · ");
}

function describeEvent(event) {
  const data = event.data || {};
  const duration = Number.isFinite(data.duration_ms)
    ? ` · ${(data.duration_ms / 1000).toFixed(1)}s`
    : "";
  switch (event.type) {
    case "queued":
      return "Request accepted and queued.";
    case "running":
      return "Workflow started.";
    case "agent_started":
      return `${data.agent || "Agent"} started.`;
    case "agent_completed":
      return `${data.agent || "Agent"} completed${duration}.`;
    case "agent_failed":
      return `${data.agent || "Agent"} failed (${data.error_type || "error"}).`;
    case "tool_started":
      return `${data.tool || "Tool"} started.`;
    case "tool_completed":
      return `${data.tool || "Tool"} completed${duration}.`;
    case "tool_failed":
      return `${data.tool || "Tool"} failed (${data.error_type || "error"}).`;
    case "model_completed":
      return `${data.agent || "Model"} response received${duration}.`;
    case "crewai_started":
      return "CrewAI research started.";
    case "crewai_completed":
      return `CrewAI research completed${duration}.`;
    case "a2a_started":
      return "Sending research context to the remote A2A reviewer.";
    case "a2a_completed":
      return `Remote A2A review response received${duration}.`;
    case "completed":
      return "Briefing completed.";
    case "completed_with_warnings":
      return "Briefing completed with warnings.";
    case "failed":
      return data.message || "Workflow failed.";
    default:
      return event.type.replaceAll("_", " ");
  }
}

function addProgressEvents(events) {
  events.forEach((event) => {
    const item = document.createElement("li");
    item.textContent = describeEvent(event);
    progressEvents.append(item);
  });
  while (progressEvents.children.length > 60) {
    progressEvents.firstElementChild.remove();
  }
  progressEvents.scrollTop = progressEvents.scrollHeight;
}

function sleep(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function pollExecution(accepted) {
  let lastEventId = 0;
  let interval = 1500;
  const startedAt = Date.now();

  while (true) {
    try {
      const eventResponse = await fetch(
        `${accepted.events_url}?after=${lastEventId}`,
      );
      if (!eventResponse.ok) {
        throw new Error("Unable to retrieve workflow progress.");
      }
      const eventData = await eventResponse.json();
      addProgressEvents(eventData.events || []);
      lastEventId = eventData.latest_event_id || lastEventId;

      const statusResponse = await fetch(accepted.status_url);
      if (!statusResponse.ok) {
        throw new Error("Unable to retrieve workflow status.");
      }
      const execution = await statusResponse.json();
      const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
      loadingMessage.textContent = elapsedSeconds > 60
        ? `Still working · ${Math.floor(elapsedSeconds / 60)}m ${elapsedSeconds % 60}s elapsed. You can leave this page and retrieve the execution later.`
        : "OfficePilot is preparing your briefing.";

      if (terminalStatuses.has(execution.status)) {
        return execution;
      }
      interval = Math.min(interval * 1.3, 5000);
    } catch (error) {
      throw new Error(
        `${error instanceof Error ? error.message : "Progress polling failed"} Execution ${accepted.execution_id} continues on the server; reload and check it again.`,
      );
    }
    await sleep(interval);
  }
}

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    requestInput.value = button.dataset.prompt;
    updateCharacterCount();
    requestInput.focus();
  });
});

requestInput.addEventListener("input", updateCharacterCount);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.hidden = true;
  formError.textContent = "";
  resultSection.hidden = true;
  progressEvents.replaceChildren();
  loadingPanel.hidden = false;
  submitButton.disabled = true;
  submitButton.querySelector(".button-label").textContent = "Preparing…";

  try {
    const response = await fetch("/executions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({ user_request: requestInput.value.trim() }),
    });
    const accepted = await response.json();

    if (!response.ok || !accepted.execution_id) {
      throw new Error(
        accepted.error
        || accepted.detail
        || "OfficePilot could not accept this briefing request.",
      );
    }

    executionIds.textContent = `Execution ${accepted.execution_id}`;
    addProgressEvents([{
      type: "queued",
      data: { message: "Request accepted and queued." },
    }]);

    const execution = await pollExecution(accepted);
    const result = execution.result || {};
    if (result.response) {
      renderBriefing(result.response);
    } else {
      briefOutput.replaceChildren();
    }

    const statusLabels = {
      completed: "BRIEFING READY",
      completed_with_warnings: "COMPLETED WITH WARNINGS",
      failed: "WORKFLOW FAILED",
    };
    resultStatus.textContent = statusLabels[execution.status] || "UNKNOWN";
    resultTime.textContent = execution.completed_at
      ? new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(execution.completed_at))
      : "";
    renderMetadata({
      ...result,
      error: execution.error,
    }, accepted.execution_id);
    resultSection.hidden = false;
    resultSection.scrollIntoView({ behavior: "smooth", block: "start" });

    if (execution.status === "failed") {
      formError.textContent = execution.error
        || "The workflow failed before a briefing was approved.";
      formError.hidden = false;
    }
  } catch (error) {
    formError.textContent = error instanceof Error
      ? error.message
      : "Something went wrong while preparing your briefing.";
    formError.hidden = false;
  } finally {
    loadingPanel.hidden = true;
    submitButton.disabled = false;
    submitButton.querySelector(".button-label").textContent = "Create my briefing";
  }
});

copyButton.addEventListener("click", async () => {
  const text = briefOutput.innerText.trim();
  if (!text) {
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    copyButton.textContent = "✓ Copied";
    window.setTimeout(() => {
      copyButton.textContent = "▢ Copy brief";
    }, 1800);
  } catch {
    copyButton.textContent = "Clipboard unavailable";
  }
});

updateCharacterCount();
